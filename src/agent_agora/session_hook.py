# src/agent_agora/session_hook.py
from __future__ import annotations

from agent_agora.registry import InstanceRegistry


class SessionCloseMiddleware:
    """ASGI middleware that calls `registry.unregister_session(session_id)` when an
    HTTP connection associated with that session id receives an `http.disconnect`.

    The session id is read from a configurable request header (default: mcp-session-id).
    Non-HTTP scopes (lifespan, websocket) pass through untouched.
    """

    def __init__(self, app, registry: InstanceRegistry, header_name: str = "mcp-session-id") -> None:
        self._app = app
        self._registry = registry
        self._header_lower = header_name.lower().encode("latin-1")

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        session_id = self._extract_session_id(scope)
        disconnected = {"value": False}

        async def _wrapped_receive():
            msg = await receive()
            if msg.get("type") == "http.disconnect":
                disconnected["value"] = True
            return msg

        try:
            await self._app(scope, _wrapped_receive, send)
        finally:
            if session_id and disconnected["value"]:
                self._registry.unregister_session(session_id)

    def _extract_session_id(self, scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name.lower() == self._header_lower:
                return value.decode("latin-1")
        return None
