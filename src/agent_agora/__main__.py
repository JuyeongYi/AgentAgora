# src/agent_agora/__main__.py
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-agora",
        description="AgentAgora -- multi-agent message-routing MCP server",
    )
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--dir", type=Path, default=Path("."))
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=Path.home() / ".agent-agora" / "certs",
    )
    parser.add_argument("--no-tls", action="store_true")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="SQLite path (default: <dir>/.agentagora/agora.db)")
    parser.add_argument("--max-inbox-depth", type=int, default=100,
                        help="Per-instance pending queue cap. 0 = unbounded.")
    parser.add_argument("--close-timeout-ms", type=int, default=300000)
    parser.add_argument("--dead-session-timeout-ms", type=int, default=1800000)
    parser.add_argument("--squat-window-ms", type=int, default=30000)
    parser.add_argument("--gc-retention-days", type=int, default=90)
    parser.add_argument("--gc-hour", type=int, default=3)
    parser.add_argument("--redact-payloads", action="store_true")
    timeout_group = parser.add_mutually_exclusive_group()
    timeout_group.add_argument("--default-wait-timeout-ms", type=int, default=60000)
    timeout_group.add_argument("--no-timeout", action="store_true")
    return parser.parse_args(argv)


def _warn_legacy_schemas_json(agora_dir: Path) -> None:
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
    max_inbox_depth: int = 100,
    db_path: Path | None = None,
):
    """Construct FastMCP app + supporting state. Used by CLI and tests.

    Returns the FastMCP instance. State (registry, persistence, dispatcher,
    write_queue) is attached as private `_agora_*` attributes for lifecycle.
    Note: this helper does NOT start AsyncWriteQueue's worker task — tests
    that only inspect tool registration don't need it.
    """
    from agent_agora.dispatcher import Dispatcher
    from agent_agora.persistence import AsyncWriteQueue, Persistence
    from agent_agora.registry import InstanceRegistry
    from agent_agora.server import create_agora_app

    _warn_legacy_schemas_json(agora_dir)

    instance_registry = InstanceRegistry()
    persistence = Persistence(db_path or (agora_dir / "agora.db"))
    persistence.migrate()
    write_queue = AsyncWriteQueue(persistence)
    dispatcher = Dispatcher(
        registry=instance_registry,
        persistence=persistence,
        write_queue=write_queue,
        default_timeout_ms=default_wait_timeout_ms,
        max_inbox_depth=max_inbox_depth if max_inbox_depth > 0 else 10**9,
    )
    mcp = create_agora_app(
        agora_dir=agora_dir,
        instance_registry=instance_registry,
        dispatcher=dispatcher,
        port=port,
    )
    mcp._agora_instance_registry = instance_registry  # type: ignore[attr-defined]
    mcp._agora_dispatcher = dispatcher  # type: ignore[attr-defined]
    mcp._agora_persistence = persistence  # type: ignore[attr-defined]
    mcp._agora_write_queue = write_queue  # type: ignore[attr-defined]
    return mcp


async def run_server(args: argparse.Namespace) -> None:
    import uvicorn

    from agent_agora.auto_register import AutoRegisterMiddleware
    from agent_agora.certs import ensure_certs

    agora_dir = args.dir / ".agentagora"
    agora_dir.mkdir(parents=True, exist_ok=True)

    db_path = args.db_path or (agora_dir / "agora.db")

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
        max_inbox_depth=args.max_inbox_depth,
        db_path=db_path,
    )
    instance_registry = mcp._agora_instance_registry  # type: ignore[attr-defined]
    dispatcher = mcp._agora_dispatcher  # type: ignore[attr-defined]
    persistence = mcp._agora_persistence  # type: ignore[attr-defined]
    write_queue = mcp._agora_write_queue  # type: ignore[attr-defined]

    scheme = "http" if args.no_tls else "https"
    print(f"AgentAgora starting on {scheme}://127.0.0.1:{args.port}/mcp")
    print(f"  Data dir : {agora_dir.resolve()}")
    print(f"  DB       : {db_path.resolve()}")
    print(f"  Cert     : {cert_path if cert_path else '(none -- HTTP mode, localhost only)'}")

    async with write_queue:
        dispatcher.restore_from_persistence()

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
            persistence.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_server(args))


if __name__ == "__main__":
    main()
