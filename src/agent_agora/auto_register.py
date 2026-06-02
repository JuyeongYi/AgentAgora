# src/agent_agora/auto_register.py
from __future__ import annotations

from agent_agora.registry import InstanceRegistry, NotRegisteredError


SESSION_ID_HEADER = b"mcp-session-id"
INSTANCE_ID_HEADER = b"x-agora-instance-id"
ROLE_HEADER = b"x-agora-role"
DESCRIPTION_HEADER = b"x-agora-description"
CWD_HEADER = b"x-agora-cwd"
WAIT_MODE_HEADER = b"x-agora-wait-mode"
DEFAULT_ROLE = "worker"


class AutoRegisterMiddleware:
    """ASGI middleware. If a request carries both `Mcp-Session-Id` and
    `X-Agora-Instance-Id` headers, auto-register (or update) the session.

    Bots (registered via agora.register_bot) must NOT send X-Agora-Instance-Id
    headers — this middleware registers workers only. A bot session that sent
    those headers would be wrongly mirrored into InstanceRegistry as a worker.
    """

    def __init__(self, app, registry: InstanceRegistry, dispatcher=None) -> None:
        self._app = app
        self._registry = registry
        # dispatcher는 register hook 트리거 용도. Optional — 테스트나 stand-alone
        # 미들웨어 사용 시 None이어도 동작한다 (hook 만 비활성).
        self._dispatcher = dispatcher

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            session_id, instance_id, role, description, cwd, wait_mode = self._extract(scope)
            if session_id and instance_id:
                fired_info = None
                try:
                    existing = self._registry.resolve_session(session_id)
                    # Empty CWD header means "no info", not "clear cwd": preserve a
                    # cwd already set (by the agora.register tool or an earlier header).
                    effective_cwd = cwd or existing.cwd
                    if (
                        existing.instance_id != instance_id
                        or existing.role != role
                        or existing.description != description
                        or existing.cwd != effective_cwd
                        or (wait_mode is not None and existing.wait_mode != wait_mode)
                    ):
                        fired_info = self._registry.register(
                            session_id=session_id,
                            instance_id=instance_id,
                            role=role,
                            description=description,
                            cwd=effective_cwd,
                            wait_mode=wait_mode,
                        )
                except NotRegisteredError:
                    fired_info = self._registry.register(
                        session_id=session_id,
                        instance_id=instance_id,
                        role=role,
                        description=description,
                        cwd=cwd,
                        wait_mode=wait_mode,
                    )
                if fired_info is not None and self._dispatcher is not None:
                    self._dispatcher.notify_registered(fired_info)
        await self._app(scope, receive, send)

    def _extract(self, scope) -> tuple[str | None, str | None, str, str, str, str | None]:
        session_id: str | None = None
        instance_id: str | None = None
        role = DEFAULT_ROLE
        description = ""
        cwd = ""
        wait_mode: str | None = None
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
            elif lname == CWD_HEADER:
                cwd = value.decode("latin-1")
            elif lname == WAIT_MODE_HEADER:
                wm = value.decode("latin-1")
                if wm in ("auto", "manual"):
                    wait_mode = wm
        return session_id, instance_id, role, description, cwd, wait_mode
