"""팀 현황 대시보드 HTTP 라우트 — GET /dashboard(HTML) + GET /dashboard/data(JSON).

읽기 전용 운영 데이터. localhost 전용·토큰 없음 — 서버의 127.0.0.1 바인딩에 의존.
향후 인증이 필요하면 register에 token 인자를 더하고 핸들러 앞에 게이트를 끼운다.
spec: docs/superpowers/specs/2026-05-17-team-dashboard-design.md.
"""
from __future__ import annotations

import asyncio
import datetime
import json as _json
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from agent_agora.dispatcher import DispatcherClosed
from agent_agora.errors import AgoraError
from agent_agora.registry import NotRegisteredError, operator_id

logger = logging.getLogger(__name__)

_DASHBOARD_HTML = Path(__file__).with_name("dashboard.html")

# 대시보드 대화 목록에 싣는 최근 대화 수 (전체가 아닌 최근 N개).
_RECENT_CONVERSATIONS = 50

# 인증이 필요한 대시보드 라우트 — 단일 소스. __main__의 미들웨어 배선과 테스트가
# 이 상수를 import해 production 설정과 테스트가 절대 drift하지 않게 한다.
DASHBOARD_PROTECTED_PATHS = [
    "/dashboard/data",
    "/dashboard/dispatch",
    "/dashboard/broadcast",
    "/dashboard/operator",
    "/dashboard/conversation",
    "/dashboard/instance",
    "/dashboard/schemas",
    "/dashboard/coverage",
    "/dashboard/logs",
    "/dashboard/stream",
]
# 인증 토큰을 query param으로도 받는 보호 라우트 (SSE: EventSource는 Authorization
# 헤더를 못 실어서). DASHBOARD_PROTECTED_PATHS의 부분집합이어야 한다.
DASHBOARD_QUERY_PARAM_PATHS = ["/dashboard/stream"]


async def _parse_json_body(request):
    """Parse the request JSON body. Returns (body, None) or (None, 422 response).
    Narrow to ValueError (JSONDecodeError/UnicodeDecodeError are subclasses)."""
    try:
        return await request.json(), None
    except ValueError:
        return None, JSONResponse({"error": "invalid JSON body"}, status_code=422)


def _inject_msgtype(payload, schema):
    """Inject msgtype into a dict payload when absent (non-dict passed through)."""
    if isinstance(payload, dict) and "msgtype" not in payload:
        return {**payload, "msgtype": schema}
    return payload


def _error_detail(exc: Exception) -> dict:
    """{'error': msg} plus 'code' when the exception carries one (AgoraError)."""
    detail = {"error": str(exc)}
    code = getattr(exc, "code", None)
    if code:
        detail["code"] = code
    return detail


def _error_to_response(exc: Exception) -> JSONResponse:
    """Map a broker/dispatch exception to an HTTP response without leaking internal
    text. AgoraError (a ValueError subclass) is checked first to keep its .code;
    NotRegisteredError -> 404, DispatcherClosed -> 503, other ValueError -> 422,
    anything else -> logged + generic 500."""
    if isinstance(exc, AgoraError):
        return JSONResponse(_error_detail(exc), status_code=422)
    if isinstance(exc, NotRegisteredError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, DispatcherClosed):
        return JSONResponse({"error": "server is shutting down"}, status_code=503)
    if isinstance(exc, ValueError):
        return JSONResponse({"error": str(exc)}, status_code=422)
    logger.exception("dashboard request failed unexpectedly")
    return JSONResponse({"error": "internal error"}, status_code=500)


def build_dashboard_data(*, dispatcher, instance_registry, bot_registry,
                         comm_matrix, health_collector=None) -> dict:
    """팀 현황 JSON 스냅샷을 조립한다."""
    instances = instance_registry.list_instances()
    peek = dispatcher.peek([i.instance_id for i in instances])
    inst_rows = []
    total_inbox = 0
    for info in instances:
        p = peek.get(info.instance_id, {})
        depth = p.get("queue_depth") or 0
        total_inbox += depth
        inst_rows.append({
            "instance_id": info.instance_id,
            "role": info.role,
            "description": info.description,
            "inbox_depth": depth,
            "in_flight": p.get("in_flight") or 0,
            "last_seen_at": info.last_seen_at,
            "accepting": info.accepting,
        })
    bot_rows = [
        {"instance_id": b.instance_id, "bot_mode": b.bot_mode,
         "subscribe_schemas": list(b.subscribe_schemas)}
        for b in bot_registry.list_bots()
    ]
    convs = dispatcher.conversations_list(limit=_RECENT_CONVERSATIONS)
    open_convs = sum(1 for c in convs if c.get("status") == "open")
    data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "instances": len(inst_rows),
            "bots": len(bot_rows),
            "open_conversations": open_convs,
            "total_inbox_depth": total_inbox,
        },
        "instances": inst_rows,
        "bots": bot_rows,
        "conversations": convs,
        "comm_matrix": {
            "active": comm_matrix.active,
            "matrix": comm_matrix.snapshot(),
            "cycles": comm_matrix.cycles(),  # 진단 — 라우팅 루프(SCC/self-loop). 거부 아님.
        },
    }
    if health_collector is not None:
        data["server"] = health_collector.snapshot()
    return data


def register(
    app: Starlette,
    *,
    dispatcher,
    instance_registry,
    bot_registry,
    comm_matrix,
    persistence=None,
    write_queue=None,
    schema_registry=None,
    health_collector=None,
    event_broker=None,
    log_buffer=None,
    auth_mode: str = "trust",
) -> None:
    """app에 대시보드 라우트를 등록한다.

    persistence + write_queue가 모두 제공된 경우 /dispatch, /broadcast,
    /operator/inbox 엔드포인트도 추가된다. write_queue는 ack 경로의 sync 쓰기
    회피용으로 필요하다 (Persistence 클래스 invariant: 쓰기는 큐를 경유).

    health_collector: HealthCollector 인스턴스 (선택). 제공 시 /data에 server 헬스 포함.
    event_broker: EventBroker 인스턴스 (선택). 제공 시 /stream SSE 엔드포인트 활성화.
    log_buffer: RingBufferLogHandler 인스턴스 (선택). 제공 시 /logs 엔드포인트 활성화.
    auth_mode: 현재 인증 모드 ("trust" | "token"). /auth-mode 엔드포인트에 노출.
    """

    async def data_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(build_dashboard_data(
            dispatcher=dispatcher, instance_registry=instance_registry,
            bot_registry=bot_registry, comm_matrix=comm_matrix,
            health_collector=health_collector))

    async def page_endpoint(request: Request) -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))

    async def auth_mode_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/auth-mode — 인증 없이 접근 가능."""
        return JSONResponse({"mode": auth_mode})

    app.router.routes.append(Route("/dashboard", page_endpoint, methods=["GET"]))
    app.router.routes.append(Route("/dashboard/data", data_endpoint, methods=["GET"]))
    # /auth-mode는 보호 경로 목록에 포함시키지 않는다 — 누구나 읽을 수 있어야 함.
    app.router.routes.append(Route("/dashboard/auth-mode", auth_mode_endpoint, methods=["GET"]))

    # ------------------------------------------------------------------
    # logs endpoint (log_buffer 제공 시 활성화) — 최근 WARNING+ 운영 이벤트.
    # ------------------------------------------------------------------
    if log_buffer is not None:

        async def logs_endpoint(request: Request) -> JSONResponse:
            """GET /dashboard/logs — RingBufferLogHandler에 쌓인 최근 로그.

            ?min_level=ERROR(이름 또는 numeric), ?limit=N 쿼리 지원."""
            min_level = request.query_params.get("min_level")
            limit_param = request.query_params.get("limit")
            try:
                limit = int(limit_param) if limit_param is not None else None
            except ValueError:
                return JSONResponse({"error": "limit must be an integer"}, status_code=422)
            return JSONResponse(
                {"logs": log_buffer.records(min_level=min_level, limit=limit)})

        app.router.routes.append(Route("/dashboard/logs", logs_endpoint, methods=["GET"]))

    # ------------------------------------------------------------------
    # SSE stream endpoint (event_broker 제공 시 활성화)
    # ------------------------------------------------------------------
    if event_broker is not None:

        async def stream_endpoint(request: Request) -> StreamingResponse:
            """GET /dashboard/stream — SSE real-time event stream."""
            # operator_user는 middleware가 설정함; fallback은 "anonymous"
            user = getattr(request.state, "operator_user", "anonymous")
            sub = event_broker.subscribe(operator_user=user)

            async def gen():
                # 초기 hydration snapshot
                snapshot = build_dashboard_data(
                    dispatcher=dispatcher,
                    instance_registry=instance_registry,
                    bot_registry=bot_registry,
                    comm_matrix=comm_matrix,
                    health_collector=health_collector,
                )
                yield f"data: {_json.dumps({'type': 'data_snapshot', 'payload': snapshot})}\n\n"
                try:
                    while True:
                        # 큐 이벤트 대기 (짧은 timeout으로 CancelledError 신속 처리)
                        # disconnect 감지는 asyncio.wait_for의 CancelledError로 처리한다.
                        # request.is_disconnected()를 루프에서 직접 await하면
                        # httpx.ASGITransport에서 receive() 블로킹이 발생한다.
                        try:
                            evt = await asyncio.wait_for(sub.get(), timeout=30.0)
                            yield f"data: {_json.dumps(evt)}\n\n"
                        except asyncio.TimeoutError:
                            yield ": ping\n\n"
                        except asyncio.CancelledError:
                            break
                finally:
                    event_broker.unsubscribe(sub)

            return StreamingResponse(gen(), media_type="text/event-stream")

        app.router.routes.append(
            Route("/dashboard/stream", stream_endpoint, methods=["GET"])
        )

    # ------------------------------------------------------------------
    # StaticFiles mount (dashboard_static 디렉터리가 있을 때만)
    # Tasks 13-18에서 실제 파일이 채워진다.
    # ------------------------------------------------------------------
    static_dir = Path(__file__).with_name("dashboard_static")
    if static_dir.exists():
        try:
            app.router.routes.append(
                Mount("/dashboard/static", app=StaticFiles(directory=static_dir))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashboard_static StaticFiles mount 실패: %s", exc)

    # ------------------------------------------------------------------
    # operator action endpoints (require persistence + write_queue)
    # ------------------------------------------------------------------
    if persistence is None or write_queue is None:
        return

    def _lazy_register_operator(user: str) -> None:
        """operator:<user> 가 레지스트리에 없으면 pseudo-instance로 등록한다."""
        sender = operator_id(user)
        try:
            instance_registry.resolve_instance_id(sender)
        except NotRegisteredError:
            instance_registry.register(
                session_id=f"dashboard:{user}",
                instance_id=sender,
                role="operator",
                description=f"Dashboard operator {user}",
            )

    async def dispatch_endpoint(request: Request) -> JSONResponse:
        """POST /dashboard/dispatch — 운영자 → 특정 워커."""
        body, _err = await _parse_json_body(request)
        if _err:
            return _err

        to = body.get("to")
        schema = body.get("schema")
        payload = body.get("payload", {})
        reply_only = bool(body.get("reply_only", False))
        conv = body.get("conversation_id")

        if not to:
            return JSONResponse({"error": "to required"}, status_code=422)
        if not schema:
            return JSONResponse({"error": "schema required"}, status_code=422)

        user = request.state.operator_user
        sender = operator_id(user)
        _lazy_register_operator(user)

        # 워커 존재 확인
        try:
            instance_registry.resolve_instance_id(to)
        except NotRegisteredError:
            return JSONResponse({"error": "recipient not registered"}, status_code=404)

        payload = _inject_msgtype(payload, schema)

        try:
            result = await dispatcher.dispatch(
                source=sender,
                target=to,
                payload=payload,
                conversation_id=conv,
                reply_only=reply_only,
            )
        except Exception as exc:  # noqa: BLE001 — mapped to status by _error_to_response
            return _error_to_response(exc)

        return JSONResponse(
            {
                "message_id": result["command_id"],
                "conversation_id": result["conversation_id"],
                "deliveries": result.get("deliveries", []),
                "skipped_full": result.get("skipped_full", []),
                "target_inbox_depth_after": result.get("target_inbox_depth_after", {}),
            },
            status_code=201,
        )

    async def broadcast_endpoint(request: Request) -> JSONResponse:
        """POST /dashboard/broadcast — 운영자 → 여러 워커."""
        body, _err = await _parse_json_body(request)
        if _err:
            return _err

        targets = body.get("targets") or []
        schema = body.get("schema")
        payload = body.get("payload", {})
        reply_only = bool(body.get("reply_only", False))

        if not targets:
            return JSONResponse({"error": "targets required"}, status_code=422)
        if not schema:
            return JSONResponse({"error": "schema required"}, status_code=422)

        user = request.state.operator_user
        sender = operator_id(user)
        _lazy_register_operator(user)

        results = []
        for to in targets:
            msg_payload = _inject_msgtype(payload, schema)
            try:
                r = await dispatcher.dispatch(
                    source=sender, target=to, payload=msg_payload,
                    reply_only=reply_only,
                )
                results.append({"to": to, "message_id": r["command_id"],
                                 "conversation_id": r["conversation_id"],
                                 "deliveries": r.get("deliveries", []),
                                 "skipped_full": r.get("skipped_full", [])})
            except Exception as exc:  # noqa: BLE001
                results.append({"to": to, **_error_detail(exc)})

        return JSONResponse({"results": results})

    async def operator_inbox_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/operator/inbox — 운영자 인박스 조회."""
        user = request.state.operator_user
        recipient = operator_id(user)
        include_acked = request.query_params.get("include_acked") == "true"
        msgs = persistence.fetch_messages_for(recipient=recipient, include_acked=include_acked)
        return JSONResponse({"messages": msgs})

    async def operator_inbox_ack_endpoint(request: Request) -> JSONResponse:
        """POST /dashboard/operator/inbox/ack — 메시지 acked_at 설정."""
        body, _err = await _parse_json_body(request)
        if _err:
            return _err

        ids = body.get("message_ids") or []
        count = await persistence.mark_messages_acked(ids, write_queue=write_queue)
        return JSONResponse({"acked": count})

    app.router.routes.append(Route("/dashboard/dispatch", dispatch_endpoint, methods=["POST"]))
    app.router.routes.append(Route("/dashboard/broadcast", broadcast_endpoint, methods=["POST"]))
    app.router.routes.append(
        Route("/dashboard/operator/inbox", operator_inbox_endpoint, methods=["GET"])
    )
    app.router.routes.append(
        Route("/dashboard/operator/inbox/ack", operator_inbox_ack_endpoint, methods=["POST"])
    )

    # ------------------------------------------------------------------
    # drilldown endpoints (conversation thread, instance inbox, schemas)
    # ------------------------------------------------------------------

    async def conversation_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/conversation/{conversation_id} — 대화 스레드 전체."""
        conv_id = request.path_params["conversation_id"]
        msgs = persistence.fetch_messages_for(conversation_id=conv_id, include_acked=True)
        return JSONResponse({"messages": msgs})

    async def instance_inbox_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/instance/{instance_id}/inbox — 워커 인박스 조회."""
        instance_id = request.path_params["instance_id"]
        msgs = persistence.fetch_messages_for(recipient=instance_id, include_acked=True)
        return JSONResponse({"messages": msgs})

    async def schemas_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/schemas — 스키마 카탈로그 (메타 + ref holder 사용통계 근사).

        id/schema는 dispatch 모달 dropdown 하위호환용으로 보존하고, kind·purpose·
        registered_by·registered_at·refs(ref holder 집합)·ref_count를 함께 노출해
        read-only explorer가 소비한다."""
        if schema_registry is None:
            return JSONResponse({"schemas": []})
        items = []
        for entry in schema_registry.list_all():
            refs = sorted(schema_registry.refs_of(entry.name))
            items.append({
                "id": entry.name,
                "name": entry.name,
                "kind": entry.kind,
                "purpose": entry.purpose,
                "registered_by": entry.registered_by,
                "registered_at": entry.registered_at,
                "refs": refs,
                "ref_count": len(refs),
                "schema": entry.body,
            })
        return JSONResponse({"schemas": items})

    async def coverage_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/coverage/{command_id} — expect_result 응답 커버리지
        (pending/responded/deadline_ts/expired). 운영자가 dispatch 받은 command_id로
        '누가 아직 응답 안 했나/deadline 넘겼나'를 추적."""
        command_id = request.path_params["command_id"]
        return JSONResponse(dispatcher.coverage(command_id))

    app.router.routes.append(
        Route("/dashboard/conversation/{conversation_id}", conversation_endpoint, methods=["GET"])
    )
    app.router.routes.append(
        Route("/dashboard/instance/{instance_id}/inbox", instance_inbox_endpoint, methods=["GET"])
    )
    app.router.routes.append(Route("/dashboard/schemas", schemas_endpoint, methods=["GET"]))
    app.router.routes.append(
        Route("/dashboard/coverage/{command_id}", coverage_endpoint, methods=["GET"])
    )
