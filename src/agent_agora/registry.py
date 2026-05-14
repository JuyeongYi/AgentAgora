# src/agent_agora/registry.py
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass


class NotRegisteredError(Exception):
    pass


@dataclass(frozen=True)
class InstanceInfo:
    instance_id: str
    session_id: str
    role: str
    registered_at: str


class InstanceRegistry:
    """Bidirectional mapping between MCP session_id and user-chosen instance_id.
    Re-registering the same instance_id from a new session replaces the prior session's entry.
    """

    def __init__(self) -> None:
        self._by_session: dict[str, InstanceInfo] = {}
        self._by_instance: dict[str, InstanceInfo] = {}
        self._lock = threading.Lock()

    def register(self, session_id: str, instance_id: str, role: str) -> InstanceInfo:
        info = InstanceInfo(
            instance_id=instance_id,
            session_id=session_id,
            role=role,
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        with self._lock:
            existing_by_inst = self._by_instance.get(instance_id)
            if existing_by_inst is not None:
                self._by_session.pop(existing_by_inst.session_id, None)
            existing_by_sess = self._by_session.get(session_id)
            if existing_by_sess is not None:
                self._by_instance.pop(existing_by_sess.instance_id, None)
            self._by_session[session_id] = info
            self._by_instance[instance_id] = info
        return info

    def unregister_session(self, session_id: str) -> None:
        with self._lock:
            info = self._by_session.pop(session_id, None)
            if info is not None:
                self._by_instance.pop(info.instance_id, None)

    def resolve_session(self, session_id: str) -> InstanceInfo:
        with self._lock:
            info = self._by_session.get(session_id)
        if info is None:
            raise NotRegisteredError(f"Session '{session_id}' is not registered")
        return info

    def resolve_instance_id(self, instance_id: str) -> InstanceInfo:
        with self._lock:
            info = self._by_instance.get(instance_id)
        if info is None:
            raise NotRegisteredError(f"Instance '{instance_id}' is not registered")
        return info

    def list_instances(self) -> list[InstanceInfo]:
        with self._lock:
            return list(self._by_instance.values())
