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
    parser.add_argument("--port", type=int, default=8420, help="HTTPS port (default: 8420)")
    parser.add_argument("--dir", type=Path, default=Path("."), help="Project directory containing .agentagora/")
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=Path.home() / ".agent-agora" / "certs",
        help="Certificate storage directory",
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


async def run_server(args: argparse.Namespace) -> None:
    import uvicorn

    from agent_agora.certs import ensure_certs
    from agent_agora.dispatcher import Dispatcher
    from agent_agora.registry import InstanceRegistry
    from agent_agora.schema import SchemaRegistry
    from agent_agora.server import create_agora_app
    from agent_agora.store import AgoraStore

    agora_dir = args.dir / ".agentagora"
    if not agora_dir.is_dir():
        print(f"Error: .agentagora/ not found in {args.dir.resolve()}", file=sys.stderr)
        sys.exit(1)

    registry = SchemaRegistry.load(agora_dir)
    store = AgoraStore(agora_dir, registry)
    cert_path, key_path = ensure_certs(args.cert_dir)
    instance_registry = InstanceRegistry()
    default_timeout = 0 if args.no_timeout else args.default_wait_timeout_ms
    dispatcher = Dispatcher(instance_registry, default_timeout_ms=default_timeout)
    from agent_agora.session_hook import SessionCloseMiddleware

    mcp, queue = create_agora_app(agora_dir, store, registry, instance_registry, dispatcher, args.port)

    print(f"AgentAgora starting on https://127.0.0.1:{args.port}/mcp")
    print(f"  Data dir : {agora_dir.resolve()}")
    print(f"  Schemas  : {', '.join(sorted(registry.names()))}")
    print(f"  Cert     : {cert_path}")

    starlette_app = mcp.streamable_http_app()
    starlette_app.add_middleware(SessionCloseMiddleware, registry=instance_registry)
    config = uvicorn.Config(
        starlette_app,
        host="127.0.0.1",
        port=args.port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        log_level="info",
    )
    server = uvicorn.Server(config)

    async with queue:
        try:
            await server.serve()
        finally:
            await dispatcher.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_server(args))


if __name__ == "__main__":
    main()
