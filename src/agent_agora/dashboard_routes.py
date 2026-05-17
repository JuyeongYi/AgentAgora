"""팀 현황 대시보드 HTTP 라우트 — GET /dashboard(HTML) + GET /dashboard/data(JSON).

읽기 전용 운영 데이터. localhost 전용·토큰 없음 — 서버의 127.0.0.1 바인딩에 의존.
향후 인증이 필요하면 register에 token 인자를 더하고 핸들러 앞에 게이트를 끼운다.
spec: docs/superpowers/specs/2026-05-17-team-dashboard-design.md.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

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


def register(app: Starlette, *, dispatcher, instance_registry, bot_registry, comm_matrix) -> None:
    """app에 대시보드 라우트 2개를 등록한다."""

    async def data_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(build_dashboard_data(
            dispatcher=dispatcher, instance_registry=instance_registry,
            bot_registry=bot_registry, comm_matrix=comm_matrix))

    async def page_endpoint(request: Request) -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))

    app.router.routes.append(Route("/dashboard", page_endpoint, methods=["GET"]))
    app.router.routes.append(Route("/dashboard/data", data_endpoint, methods=["GET"]))
