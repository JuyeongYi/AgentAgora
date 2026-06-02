"""채널 어댑터·봇 SDK용 인박스 감지 HTTP 엔드포인트 — GET /channel/wait.

agora-channel 어댑터와 AgoraBot SDK가 워커 인박스 도착을 감지하는 always-on
경로. 블로킹 long-poll 도구 agora.wait_notify를 워커 MCP 도구 표면에서 들어내고
이 HTTP 라우트로 대체한다. localhost 전용·토큰 없음 — 서버 127.0.0.1 바인딩에
의존. wait_notify는 advisory·비파괴 peek이라(pending 개수·sources 목록만 노출)
always-on이어도 안전하다.

spec: docs/superpowers/specs/2026-05-18-wait-tool-gating-design.md.
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_agora.dispatcher import DispatcherClosed

# Upper bound for a single long-poll wait. Caps unbounded waits (a forged/huge
# timeout_ms can't pin a waiter indefinitely). Must exceed the channel adapter's
# heartbeat (30000ms). Omitted timeout still falls through to the server default.
_MAX_WAIT_MS = 60_000


def register(app: Starlette, *, dispatcher) -> None:
    """app에 GET /channel/wait 라우트를 등록한다."""

    async def wait_endpoint(request: Request) -> JSONResponse:
        instance_id = request.query_params.get("instance_id")
        if not instance_id:
            return JSONResponse(
                {"error": "instance_id query parameter is required"},
                status_code=400)
        raw_timeout = request.query_params.get("timeout_ms")
        timeout_ms = None
        if raw_timeout is not None and raw_timeout != "":
            try:
                timeout_ms = int(raw_timeout)
            except ValueError:
                return JSONResponse(
                    {"error": "timeout_ms must be an integer"},
                    status_code=400)
            # Cap only the upper bound; omitted timeout (None) keeps the server
            # default, and small/0/negative values are passed through unchanged.
            timeout_ms = min(timeout_ms, _MAX_WAIT_MS)
        try:
            result = await dispatcher.wait_notify(
                instance_id=instance_id, timeout_ms=timeout_ms)
        except DispatcherClosed:
            return JSONResponse(
                {"error": "server is shutting down"}, status_code=503)
        return JSONResponse(result)

    app.router.routes.append(
        Route("/channel/wait", wait_endpoint, methods=["GET"]))
