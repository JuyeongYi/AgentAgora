"""팀 현황 대시보드 HTTP 라우트 — GET /dashboard(HTML) + GET /dashboard/data(JSON).

읽기 전용 운영 데이터. localhost 전용·토큰 없음 — 서버의 127.0.0.1 바인딩에 의존.
향후 인증이 필요하면 register에 token 인자를 더하고 핸들러 앞에 게이트를 끼운다.
spec: docs/superpowers/specs/2026-05-17-team-dashboard-design.md.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from agent_agora.registry import NotRegisteredError

logger = logging.getLogger(__name__)

_DASHBOARD_HTML = Path(__file__).with_name("dashboard.html")

# 대시보드 대화 목록에 싣는 최근 대화 수 (전체가 아닌 최근 N개).
_RECENT_CONVERSATIONS = 50


def build_dashboard_data(*, dispatcher, instance_registry, bot_registry, comm_matrix) -> dict:
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
    return {
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
        "comm_matrix": {"active": comm_matrix.active, "matrix": comm_matrix.snapshot()},
    }


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
) -> None:
    """app에 대시보드 라우트를 등록한다.

    persistence + write_queue가 모두 제공된 경우 /dispatch, /broadcast,
    /operator/inbox 엔드포인트도 추가된다. write_queue는 ack 경로의 sync 쓰기
    회피용으로 필요하다 (Persistence 클래스 invariant: 쓰기는 큐를 경유).
    """

    async def data_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(build_dashboard_data(
            dispatcher=dispatcher, instance_registry=instance_registry,
            bot_registry=bot_registry, comm_matrix=comm_matrix))

    async def page_endpoint(request: Request) -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))

    app.router.routes.append(Route("/dashboard", page_endpoint, methods=["GET"]))
    app.router.routes.append(Route("/dashboard/data", data_endpoint, methods=["GET"]))

    # ------------------------------------------------------------------
    # operator action endpoints (require persistence + write_queue)
    # ------------------------------------------------------------------
    if persistence is None or write_queue is None:
        return

    def _lazy_register_operator(user: str) -> None:
        """operator:<user> 가 레지스트리에 없으면 pseudo-instance로 등록한다."""
        sender = f"operator:{user}"
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
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=422)

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
        sender = f"operator:{user}"
        _lazy_register_operator(user)

        # 워커 존재 확인
        try:
            instance_registry.resolve_instance_id(to)
        except NotRegisteredError:
            return JSONResponse({"error": "recipient not registered"}, status_code=404)

        # msgtype을 payload에 주입
        if isinstance(payload, dict) and "msgtype" not in payload:
            payload = {**payload, "msgtype": schema}

        try:
            result = await dispatcher.dispatch(
                source=sender,
                target=to,
                payload=payload,
                conversation_id=conv,
                reply_only=reply_only,
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

        return JSONResponse(
            {
                "message_id": result["command_id"],
                "conversation_id": result["conversation_id"],
            },
            status_code=201,
        )

    async def broadcast_endpoint(request: Request) -> JSONResponse:
        """POST /dashboard/broadcast — 운영자 → 여러 워커."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=422)

        targets = body.get("targets") or []
        schema = body.get("schema")
        payload = body.get("payload", {})
        reply_only = bool(body.get("reply_only", False))

        if not targets:
            return JSONResponse({"error": "targets required"}, status_code=422)
        if not schema:
            return JSONResponse({"error": "schema required"}, status_code=422)

        user = request.state.operator_user
        sender = f"operator:{user}"
        _lazy_register_operator(user)

        results = []
        for to in targets:
            msg_payload = dict(payload) if isinstance(payload, dict) else payload
            if isinstance(msg_payload, dict) and "msgtype" not in msg_payload:
                msg_payload = {**msg_payload, "msgtype": schema}
            try:
                r = await dispatcher.dispatch(
                    source=sender, target=to, payload=msg_payload,
                    reply_only=reply_only,
                )
                results.append({"to": to, "message_id": r["command_id"],
                                 "conversation_id": r["conversation_id"]})
            except Exception as exc:
                results.append({"to": to, "error": str(exc)})

        return JSONResponse({"results": results})

    async def operator_inbox_endpoint(request: Request) -> JSONResponse:
        """GET /dashboard/operator/inbox — 운영자 인박스 조회."""
        user = request.state.operator_user
        recipient = f"operator:{user}"
        include_acked = request.query_params.get("include_acked") == "true"
        msgs = persistence.fetch_messages_for(recipient=recipient, include_acked=include_acked)
        return JSONResponse({"messages": msgs})

    async def operator_inbox_ack_endpoint(request: Request) -> JSONResponse:
        """POST /dashboard/operator/inbox/ack — 메시지 acked_at 설정."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=422)

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
        """GET /dashboard/schemas — 등록된 스키마 카탈로그."""
        if schema_registry is None:
            return JSONResponse({"schemas": []})
        items = [
            {"id": entry.name, "schema": entry.body}
            for entry in schema_registry.list_all()
        ]
        return JSONResponse({"schemas": items})

    app.router.routes.append(
        Route("/dashboard/conversation/{conversation_id}", conversation_endpoint, methods=["GET"])
    )
    app.router.routes.append(
        Route("/dashboard/instance/{instance_id}/inbox", instance_inbox_endpoint, methods=["GET"])
    )
    app.router.routes.append(Route("/dashboard/schemas", schemas_endpoint, methods=["GET"]))
