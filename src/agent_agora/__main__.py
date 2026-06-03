# src/agent_agora/__main__.py
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-agora",
        description="AgentAgora -- multi-agent message-routing MCP server",
    )
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument(
        "--bind-host",
        default=os.environ.get("AGORA_BIND_HOST", "127.0.0.1"),
        help="uvicorn이 바인딩할 호스트. 기본 127.0.0.1(로컬 전용). "
             "여러 PC에서 접속하는 테스트는 0.0.0.0(전 인터페이스)으로 둔다. "
             "인증이 없으므로 신뢰된 사설망에서만. 환경변수 AGORA_BIND_HOST로도 "
             "지정 가능(플래그가 우선). 정식 remote 배포는 별도 spec 참조.",
    )
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
    parser.add_argument("--gc-retention-days", type=int, default=90)
    parser.add_argument("--gc-hour", type=int, default=3)
    parser.add_argument("--file-retention-days", type=int, default=7,
                        help="공유 파일 보관 기간(일). 기본 7.")
    timeout_group = parser.add_mutually_exclusive_group()
    timeout_group.add_argument("--default-wait-timeout-ms", type=int, default=60000)
    timeout_group.add_argument("--no-timeout", action="store_true")
    parser.add_argument(
        "--restore",
        action="store_true",
        help="재시작 시 이전 미배달 메시지를 인박스로 복구한다 "
             "(크래시 내구성). 미지정 시 클린 스타트 - 미배달 메시지는 drop된다.",
    )
    parser.add_argument(
        "--add-wait",
        action="store_true",
        help="레거시·디버깅용 - agora.wait_notify MCP 도구를 등록한다. "
             "기본 미등록. 채널 어댑터·봇 SDK는 GET /channel/wait를 쓴다.",
    )
    parser.add_argument(
        "--bot-emit-recheck-acl",
        action="store_true",
        help="라우팅 봇의 agora.bot_emit(target=...) 직접 전달도 comm-matrix ACL을 "
             "재검사한다. 기본 미적용(봇은 신뢰 인프라로 우회). 켜면 매트릭스에 봇 "
             "instance_id 패턴을 포함해야 봇 전달이 허용된다.",
    )
    return parser.parse_args(argv)


def _warn_legacy_schemas_json(agora_dir: Path) -> None:
    legacy = agora_dir / "schemas.json"
    if legacy.exists():
        print(
            f"[agora] WARNING: detected legacy v1 schemas.json at {legacy} - "
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
    close_timeout_ms: int = 300_000,
    dead_session_timeout_ms: int = 1_800_000,
    gc_retention_days: int = 90,
    file_retention_days: int = 7,
    add_wait: bool = False,
    bot_emit_recheck_acl: bool = False,
):
    """Construct FastMCP app + supporting state. Used by CLI and tests.

    Returns the FastMCP instance. State (registry, persistence, dispatcher,
    write_queue) is attached as private `_agora_*` attributes for lifecycle.
    Note: this helper does NOT start AsyncWriteQueue's worker task — tests
    that only inspect tool registration don't need it.
    """
    from agent_agora.registry import BotRegistry
    from agent_agora.comm_matrix import load_comm_matrix
    from agent_agora.dispatcher import Dispatcher
    from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
    from agent_agora.registry import InstanceRegistry
    from agent_agora.storage.schemas import SchemaRegistry, ensure_schemas_file, load_schemas_into
    from agent_agora.server import create_agora_app

    _warn_legacy_schemas_json(agora_dir)

    instance_registry = InstanceRegistry()
    bot_registry = BotRegistry()
    comm_matrix = load_comm_matrix(agora_dir / "comm-matrix.csv")
    persistence = Persistence(db_path or (agora_dir / "agora.db"))
    persistence.migrate()

    # Schema 로드: (1) .agentagora/schemas.jsonl 빌트인 로드, (2) schema_conflict 시스템 스키마.
    # 런타임 등록 스키마는 복원하지 않는다 — ref-counting 하에서 holder가 죽어 고아 ref가
    # 되므로(spec §3 재시작 동작). 봇·워커는 재접속 시 스스로 재등록한다.
    from agent_agora.storage.schemas import (SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY,
                                     FILE_SHARE_NAME, FILE_SHARE_BODY)
    schema_registry = SchemaRegistry()
    schemas_file = ensure_schemas_file(agora_dir / "schemas.jsonl")
    try:
        load_schemas_into(schema_registry, schemas_file)
    except Exception as e:  # noqa: BLE001
        print(f"[agora] WARNING: {schemas_file} 로드 중 일부 schema 충돌: {e}", file=sys.stderr)
    # schema_conflict — 시스템 스키마, permanent (registered_by 미지정)
    schema_registry.register(
        SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY,
        kind="conversation", purpose="스키마 이름 충돌 통지")
    # file_share — 파일 공유 핸들 통지, permanent
    schema_registry.register(
        FILE_SHARE_NAME, FILE_SHARE_BODY,
        kind="conversation", purpose="파일 공유 핸들 통지")
    # 빌트인 schema를 SQLite에도 영속 (idempotent, audit용)
    for entry in schema_registry.list_all():
        persistence.save_schema(entry.name, entry.body, kind=entry.kind,
                                purpose=entry.purpose, registered_by=entry.registered_by)

    from agent_agora.files import FileStore, load_file_policy
    file_store = FileStore(agora_dir, persistence)
    file_policy = load_file_policy(agora_dir / "file-policy.json")
    write_queue = AsyncWriteQueue(persistence)
    dispatcher = Dispatcher(
        registry=instance_registry,
        persistence=persistence,
        write_queue=write_queue,
        schema_registry=schema_registry,
        bot_registry=bot_registry,
        comm_matrix=comm_matrix,
        default_timeout_ms=default_wait_timeout_ms,
        max_inbox_depth=max_inbox_depth if max_inbox_depth > 0 else 10**9,
        close_timeout_ms=close_timeout_ms,
        dead_session_timeout_ms=dead_session_timeout_ms,
        gc_retention_days=gc_retention_days,
        file_store=file_store,
        file_retention_days=file_retention_days,
        bot_emit_recheck_acl=bot_emit_recheck_acl,
    )
    mcp = create_agora_app(
        agora_dir=agora_dir,
        instance_registry=instance_registry,
        schema_registry=schema_registry,
        bot_registry=bot_registry,
        comm_matrix=comm_matrix,
        persistence=persistence,
        dispatcher=dispatcher,
        port=port,
        file_store=file_store,
        file_policy=file_policy,
        add_wait=add_wait,
    )
    mcp._agora_instance_registry = instance_registry  # type: ignore[attr-defined]
    mcp._agora_schema_registry = schema_registry  # type: ignore[attr-defined]
    mcp._agora_bot_registry = bot_registry  # type: ignore[attr-defined]
    mcp._agora_comm_matrix = comm_matrix  # type: ignore[attr-defined]
    mcp._agora_dispatcher = dispatcher  # type: ignore[attr-defined]
    mcp._agora_persistence = persistence  # type: ignore[attr-defined]
    mcp._agora_write_queue = write_queue  # type: ignore[attr-defined]
    mcp._agora_file_store = file_store  # type: ignore[attr-defined]
    mcp._agora_file_policy = file_policy  # type: ignore[attr-defined]
    return mcp


def _setup_console_logging() -> None:
    """agent_agora.* 로그를 stdout에 bare 포맷으로 보낸다 — dispatcher 라우팅 배너
    (과거 print(flush=True))를 보존하고 warning/exception을 콘솔에 노출. 멱등."""
    log = logging.getLogger("agent_agora")
    if any(getattr(h, "_agora_console", False) for h in log.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._agora_console = True  # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


async def run_server(args: argparse.Namespace) -> None:
    import uvicorn
    _setup_console_logging()

    from agent_agora.http.auto_register import AutoRegisterMiddleware
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
        close_timeout_ms=args.close_timeout_ms,
        dead_session_timeout_ms=args.dead_session_timeout_ms,
        gc_retention_days=args.gc_retention_days,
        file_retention_days=args.file_retention_days,
        add_wait=args.add_wait,
        bot_emit_recheck_acl=args.bot_emit_recheck_acl,
    )
    instance_registry = mcp._agora_instance_registry  # type: ignore[attr-defined]
    dispatcher = mcp._agora_dispatcher  # type: ignore[attr-defined]
    persistence = mcp._agora_persistence  # type: ignore[attr-defined]
    write_queue = mcp._agora_write_queue  # type: ignore[attr-defined]
    schema_registry = mcp._agora_schema_registry  # type: ignore[attr-defined]

    scheme = "http" if args.no_tls else "https"
    print(f"AgentAgora starting on {scheme}://{args.bind_host}:{args.port}/mcp")
    if args.bind_host not in ("127.0.0.1", "localhost"):
        print(f"  Bind     : {args.bind_host} (non-local bind - no auth, "
              f"trusted private network only)")
    print(f"  Data dir : {agora_dir.resolve()}")
    print(f"  DB       : {db_path.resolve()}")
    print(f"  Cert     : {cert_path if cert_path else '(none -- HTTP mode, localhost only)'}")

    async with write_queue:
        if args.restore:
            dispatcher.restore_from_persistence()
        else:
            dispatcher.drop_inflight_on_restart()

        # M2 background tasks
        sweep_task = asyncio.create_task(_sweep_loop_60s(dispatcher))
        gc_task = asyncio.create_task(_message_gc_loop(dispatcher, args.gc_hour))

        starlette_app = mcp.streamable_http_app()
        starlette_app.add_middleware(
            AutoRegisterMiddleware,
            registry=instance_registry,
            dispatcher=dispatcher,
        )
        from agent_agora.http.admin_routes import maybe_register, make_file_policy_route
        _admin_token = os.environ.get("AGORA_ADMIN_TOKEN")
        if maybe_register(
            starlette_app, mcp._agora_comm_matrix,  # type: ignore[attr-defined]
            _admin_token,
        ):
            print("  Admin    : POST/GET /admin/comm-matrix (AGORA_ADMIN_TOKEN set)")
        if _admin_token:
            starlette_app.router.routes.append(
                make_file_policy_route(mcp._agora_file_policy, _admin_token))  # type: ignore[attr-defined]
            print("  Admin    : POST/GET /admin/file-policy (AGORA_ADMIN_TOKEN set)")
        import time as _time
        from agent_agora.dashboard import (
            HealthCollector,
            EventBroker,
            DashboardAuthMiddleware,
            parse_tokens,
            parse_basic_users,
            register as register_dashboard,
            DASHBOARD_PROTECTED_PATHS,
            DASHBOARD_QUERY_PARAM_PATHS,
        )

        _dash_auth_mode = os.environ.get("AGORA_DASHBOARD_AUTH_MODE", "trust")
        try:
            _dash_tokens = parse_tokens(os.environ.get("AGORA_DASHBOARD_TOKENS", ""))
        except ValueError as e:
            print(
                f"[agent_agora] error: AGORA_DASHBOARD_TOKENS is malformed: {e}",
                file=sys.stderr,
            )
            print(
                "  Expected format: 'user1:token1,user2:token2'",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            _dash_users = parse_basic_users(
                os.environ.get("AGORA_DASHBOARD_BASIC_USERS", ""))
        except ValueError as e:
            print(
                f"[agent_agora] error: AGORA_DASHBOARD_BASIC_USERS is malformed: {e}",
                file=sys.stderr,
            )
            print(
                "  Expected format: 'user1:{SHA256}<b64>,user2:pbkdf2_sha256$...'",
                file=sys.stderr,
            )
            sys.exit(1)
        _inbox_isolation = os.environ.get(
            "AGORA_DASHBOARD_INBOX_ISOLATION", "").strip().lower() in (
                "1", "true", "yes", "on")

        _health = HealthCollector(
            started_at=_time.time(),
            db_path=db_path,
            persistence=write_queue,
            sweeper=dispatcher.sweeper,
        )
        _event_broker = EventBroker(max_queue=1000)
        _event_broker.attach_to_dispatcher(dispatcher)

        # 대시보드 로그 패널 — agent_agora.* 의 WARNING+ 를 ring buffer에 모은다.
        from agent_agora.dashboard.logbuffer import RingBufferLogHandler
        _log_buffer = RingBufferLogHandler(capacity=500, level=logging.WARNING)
        logging.getLogger("agent_agora").addHandler(_log_buffer)

        starlette_app.add_middleware(
            DashboardAuthMiddleware,
            mode=_dash_auth_mode,
            tokens=_dash_tokens,
            users=_dash_users,
            protected_paths=DASHBOARD_PROTECTED_PATHS,
            query_param_paths=DASHBOARD_QUERY_PARAM_PATHS,
        )

        register_dashboard(
            starlette_app,
            dispatcher=dispatcher,
            instance_registry=instance_registry,
            bot_registry=mcp._agora_bot_registry,  # type: ignore[attr-defined]
            comm_matrix=mcp._agora_comm_matrix,  # type: ignore[attr-defined]
            persistence=persistence,
            write_queue=write_queue,
            schema_registry=schema_registry,
            health_collector=_health,
            event_broker=_event_broker,
            log_buffer=_log_buffer,
            inbox_isolation=_inbox_isolation,
            auth_mode=_dash_auth_mode,
        )
        print("  Dashboard: GET /dashboard, GET /dashboard/data, GET /dashboard/auth-mode")
        print("  Dashboard: GET /dashboard/stream (SSE)")
        print("  Dashboard: POST /dashboard/dispatch, POST /dashboard/broadcast")
        print("  Dashboard: GET /dashboard/operator/inbox, POST /dashboard/operator/inbox/ack")
        print("  Dashboard: GET /dashboard/logs (recent WARNING+ events)")
        print(f"  Dashboard: auth mode = {_dash_auth_mode}"
              + (f", basic users = {len(_dash_users)}" if _dash_auth_mode == "basic" else "")
              + (", inbox isolation = on" if _inbox_isolation else ""))
        from agent_agora.files import register as register_files
        register_files(starlette_app, file_store=mcp._agora_file_store,  # type: ignore[attr-defined]
                       file_policy=mcp._agora_file_policy)  # type: ignore[attr-defined]
        print("  Files    : POST /files, GET /files/<id>")
        # GET /channel/wait는 --add-wait와 무관하게 항상 등록한다 — 채널
        # 어댑터·봇 SDK의 인박스 감지가 이 라우트에 의존하기 때문.
        from agent_agora.http.channel_routes import register as register_channel
        register_channel(starlette_app, dispatcher=dispatcher)
        print("  Channel  : GET /channel/wait")
        config_kwargs = {
            "host": args.bind_host,
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
            sweep_task.cancel()
            gc_task.cancel()
            for t in (sweep_task, gc_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            await dispatcher.close()
            persistence.close()


async def _sweep_loop_60s(dispatcher) -> None:
    """60-second close TTL + dead-session + dead-bot sweeps."""
    while True:
        await asyncio.sleep(60)
        try:
            dispatcher.sweeper.close_ttl_sweep()
            dispatcher.sweeper.dead_session_sweep()
            dispatcher.sweeper.dead_bot_sweep()
            await dispatcher.sweeper.deadline_sweep()
        except Exception as e:
            print(f"[agora] sweep error: {e}", file=sys.stderr)


async def _message_gc_loop(dispatcher, gc_hour: int) -> None:
    """Run message_gc_sweep once daily at gc_hour UTC."""
    import datetime as _dt
    while True:
        now = _dt.datetime.now(_dt.timezone.utc)
        next_run = now.replace(hour=gc_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += _dt.timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            dispatcher.sweeper.message_gc_sweep()
            dispatcher.sweeper.file_gc_sweep()
            dispatcher.sweeper.vacuum()
        except Exception as e:
            print(f"[agora] message_gc error: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_server(args))


if __name__ == "__main__":
    main()
