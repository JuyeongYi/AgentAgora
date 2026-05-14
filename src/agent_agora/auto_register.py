# src/agent_agora/auto_register.py
from __future__ import annotations

from agent_agora.registry import InstanceRegistry, NotRegisteredError


SESSION_ID_HEADER = b"mcp-session-id"
INSTANCE_ID_HEADER = b"x-agora-instance-id"
ROLE_HEADER = b"x-agora-role"
DESCRIPTION_HEADER = b"x-agora-description"
DEFAULT_ROLE = "worker"


class AutoRegisterMiddleware:
    """ASGI middleware. If an HTTP request carries both `Mcp-Session-Id` and
    `X-Agora-Instance-Id` headers, and the session is not yet registered, auto-register it.

    Allows `.mcp.json` clients to declare their identity once via `headers` and skip
    the explicit `agora.register` tool call. Existing registrations are never overwritten
    by the middleware.
    """

    def __init__(self, app, registry: InstanceRegistry) -> None:
        self._app = app
        self._registry = registry

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            session_id, instance_id, role, description = self._extract(scope)
            if session_id and instance_id:
                try:
                    existing = self._registry.resolve_session(session_id)
                    # Update if the client changed any registered attribute on this session
                    if (
                        existing.instance_id != instance_id
                        or existing.role != role
                        or existing.description != description
                    ):
                        self._registry.register(
                            session_id=session_id,
                            instance_id=instance_id,
                            role=role,
                            description=description,
                        )
                except NotRegisteredError:
                    self._registry.register(
                        session_id=session_id,
                        instance_id=instance_id,
                        role=role,
                        description=description,
                    )
        await self._app(scope, receive, send)

    def _extract(self, scope) -> tuple[str | None, str | None, str, str]:
        session_id: str | None = None
        instance_id: str | None = None
        role = DEFAULT_ROLE
        description = ""
        for name, value in scope.get("headers", []):
            lname = name.lower()
            if lname == SESSION_ID_HEADER:
                session_id = value.decode("latin-1")
            elif lname == INSTANCE_ID_HEADER:
                instance_id = value.decode("latin-1")
            elif lname == ROLE_HEADER:
                role = value.decode("latin-1")
            elif lname == DESCRIPTION_HEADER:
                description = value.decode("latin-1")
        return session_id, instance_id, role, description
