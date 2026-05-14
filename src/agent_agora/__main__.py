# src/agent_agora/__main__.py
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-agora",
        description="AgentAgora -- shared state MCP server for independent agents",
    )
    parser.add_argument("--port", type=int, default=8420, help="Listen port (default: 8420)")
    parser.add_argument("--dir", type=Path, default=Path("."), help="Project directory containing .agentagora/")
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=Path.home() / ".agent-agora" / "certs",
        help="Certificate storage directory (unused when --no-tls is set)",
    )
    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="Serve over plain HTTP instead of HTTPS. Localhost-only testing convenience; skips cert generation.",
    )
    timeout_group = parser.add_mutually_exclusive_group()
    timeout_group.add_argument(
        "--default-wait-timeout-ms",
        type=int,
        default=60000,
        help="Default timeout for agora.wait when caller does not specify (ms). Default: 60000",
    )
    timeout_group.add_argument(
        "--no-timeout",
        action="store_true",
        help="Unbounded blocking. Mutually exclusive with --default-wait-timeout-ms.",
    )
    return parser.parse_args(argv)


def _warn_legacy_schemas_json(agora_dir: Path) -> None:
    """Detect leftover v1 schemas.json and warn (v3 ignores it)."""
    legacy = agora_dir / "schemas.json"
    if legacy.exists():
        print(
            f"[agora] WARNING: detected legacy v1 schemas.json at {legacy} — "
            f"v3 ignores it (KV removed). You may delete or rename this file.",
            file=sys.stderr,
        )


def _build_app(
    agora_dir: Path,
    port: int,
    no_tls: bool = False,
    default_wait_timeout_ms: int = 60000,
):
    """Construct the FastMCP app + supporting state. Used by both CLI and tests.

    Returns the FastMCP instance. The caller is responsible for wrapping it in
    a Starlette/uvicorn server. `no_tls` is accepted for API compatibility but
    has no effect on app construction itself — TLS is configured by the CLI
    layer in `run_server`.
    """
    _warn_legacy_schemas_json(agora_dir)
    from agent_agora.dispatcher import Dispatcher
    from agent_agora.registry import InstanceRegistry
    from agent_agora.server import create_agora_app

    instance_registry = InstanceRegistry()
    dispatcher = Dispatcher(instance_registry, default_timeout_ms=default_wait_timeout_ms)
    mcp = create_agora_app(
        agora_dir=agora_dir,
        instance_registry=instance_registry,
        dispatcher=dispatcher,
        port=port,
    )
    # Attach the supporting state so CLI callers can drive lifecycle. Tests that
    # only inspect tool registration can ignore these attributes.
    mcp._agora_instance_registry = instance_registry  # type: ignore[attr-defined]
    mcp._agora_dispatcher = dispatcher  # type: ignore[attr-defined]
    return mcp


async def run_server(args: argparse.Namespace) -> None:
    import uvicorn

    from agent_agora.auto_register import AutoRegisterMiddleware
    from agent_agora.certs import ensure_certs

    agora_dir = args.dir / ".agentagora"
    # v3: auto-create the state directory (KV's schemas.json prerequisite is gone;
    # the dir will hold the M1 agora.db).
    agora_dir.mkdir(parents=True, exist_ok=True)

    if args.no_tls:
        cert_path, key_path = None, None
    else:
        cert_path, key_path = ensure_certs(args.cert_dir)

    default_timeout = 0 if args.no_timeout else args.default_wait_timeout_ms
    mcp = _build_app(
        agora_dir=agora_dir,
        port=args.port,
        no_tls=args.no_tls,
        default_wait_timeout_ms=default_timeout,
    )
    instance_registry = mcp._agora_instance_registry  # type: ignore[attr-defined]
    dispatcher = mcp._agora_dispatcher  # type: ignore[attr-defined]

    scheme = "http" if args.no_tls else "https"
    print(f"AgentAgora starting on {scheme}://127.0.0.1:{args.port}/mcp")
    print(f"  Data dir : {agora_dir.resolve()}")
    print(f"  Cert     : {cert_path if cert_path else '(none -- HTTP mode, localhost only)'}")

    starlette_app = mcp.streamable_http_app()
    starlette_app.add_middleware(AutoRegisterMiddleware, registry=instance_registry)
    config_kwargs = {
        "host": "127.0.0.1",
        "port": args.port,
        "log_level": "info",
    }
    if not args.no_tls:
        config_kwargs["ssl_certfile"] = str(cert_path)
        config_kwargs["ssl_keyfile"] = str(key_path)
    config = uvicorn.Config(starlette_app, **config_kwargs)
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await dispatcher.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_server(args))


if __name__ == "__main__":
    main()
