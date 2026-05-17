"""운영자 전용 admin HTTP 엔드포인트 — comm-matrix 런타임 교체.

워커가 보는 MCP 도구 표면이 아니다. AGORA_ADMIN_TOKEN으로 게이팅되며,
토큰을 가진 운영자만 호출한다.
spec: docs/superpowers/specs/2026-05-17-comm-matrix-governance-design.md.
"""
from __future__ import annotations

import hmac

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_agora.comm_matrix import CommMatrix
from agent_agora.errors import AgoraError

_BEARER_PREFIX = "Bearer "


def _authorized(request: Request, token: str) -> bool:
    """Authorization: Bearer <token> 헤더가 token과 상수시간 일치하는가."""
    header = request.headers.get("authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        return False
    return hmac.compare_digest(header[len(_BEARER_PREFIX):], token)


def make_admin_route(comm_matrix: CommMatrix, token: str) -> Route:
    """comm-matrix admin 라우트를 만든다. comm_matrix·token을 클로저로 캡처.

    POST /admin/comm-matrix — 바디 CSV로 in-memory 매트릭스 교체.
    GET  /admin/comm-matrix — 현재 매트릭스 상태 조회.
    """

    async def endpoint(request: Request) -> JSONResponse:
        if not _authorized(request, token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.method == "GET":
            return JSONResponse({
                "active": comm_matrix.active,
                "matrix": comm_matrix.snapshot(),
            })
        # POST — 바디 CSV로 매트릭스 in-memory 교체
        csv_text = (await request.body()).decode("utf-8")
        try:
            comm_matrix.load_csv(csv_text)
        except AgoraError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "ok", "active": comm_matrix.active})

    return Route("/admin/comm-matrix", endpoint, methods=["GET", "POST"])


def maybe_register(
    app: Starlette, comm_matrix: CommMatrix, token: str | None,
) -> bool:
    """token이 truthy면 app에 admin 라우트를 등록한다. 등록 여부를 반환.

    token이 없으면(env 미설정) admin 엔드포인트는 아예 존재하지 않는다 —
    기본 비활성 = 기본 안전."""
    if not token:
        return False
    app.router.routes.append(make_admin_route(comm_matrix, token))
    return True
