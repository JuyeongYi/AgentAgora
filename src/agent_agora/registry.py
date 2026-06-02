# src/agent_agora/registry.py
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, replace
from typing import Generic, Literal, TypeVar


class NotRegisteredError(Exception):
    pass


OPERATOR_PREFIX = "operator:"


def is_operator(instance_id: str) -> bool:
    """True iff instance_id is a dashboard operator pseudo-instance.

    Pseudo-instances use the `operator:<username>` namespace and are
    exempt from sweeper GC and comm-matrix ACL.
    """
    if not instance_id.startswith(OPERATOR_PREFIX):
        return False
    return len(instance_id) > len(OPERATOR_PREFIX)


def operator_id(user: str) -> str:
    """Build the operator pseudo-instance id for a dashboard user."""
    return OPERATOR_PREFIX + user


def strip_operator_prefix(instance_id: str) -> str | None:
    """Return the username for an operator pseudo-instance, else None.

    None for non-operators and for the bare 'operator:' prefix (no username) —
    matches is_operator's length guard.
    """
    if not is_operator(instance_id):
        return None
    return instance_id[len(OPERATOR_PREFIX):]


InfoT = TypeVar("InfoT")


class _BidirectionalRegistry(Generic[InfoT]):
    """session_id <-> instance_id 양방향 매핑의 공통 베이스 (Plan E).

    InfoT는 `.session_id`/`.instance_id`/`.last_seen_at`를 갖는 frozen dataclass로
    가정한다. 봇 고유 로직(파생 인덱스)은 _on_store_locked/_on_detach_locked 훅으로만
    노출 — 베이스는 봇/워커 구분을 모른다. 등록 충돌 해소는 _detach_locked로 통일
    (워커는 파생 인덱스가 없어 _on_detach_locked가 no-op → 기존 2-pop과 동일 동작).
    """

    _SESSION_LABEL: str = "Session"
    _INSTANCE_LABEL: str = "Instance"

    def __init__(self) -> None:
        self._by_session: dict[str, InfoT] = {}
        self._by_instance: dict[str, InfoT] = {}
        self._lock = threading.Lock()

    # --- 서브클래스 훅 (모두 _lock 보유 상태에서 호출) ---
    def _on_store_locked(self, info: InfoT) -> None:
        """info를 양쪽 dict에 저장한 직후. 봇: observer/subscriber 인덱스 채움."""

    def _on_detach_locked(self, info: InfoT) -> None:
        """info를 떼어낼 때. 봇: observer/subscriber 인덱스 정리."""

    def _detach_locked(self, info: InfoT) -> None:
        self._by_session.pop(info.session_id, None)  # type: ignore[attr-defined]
        self._by_instance.pop(info.instance_id, None)  # type: ignore[attr-defined]
        self._on_detach_locked(info)

    def register_info(self, info: InfoT) -> InfoT:
        with self._lock:
            prior = self._by_instance.get(info.instance_id)  # type: ignore[attr-defined]
            if prior is not None:
                self._detach_locked(prior)
            prior_sess = self._by_session.get(info.session_id)  # type: ignore[attr-defined]
            if prior_sess is not None:
                self._detach_locked(prior_sess)
            self._by_session[info.session_id] = info  # type: ignore[attr-defined]
            self._by_instance[info.instance_id] = info  # type: ignore[attr-defined]
            self._on_store_locked(info)
        return info

    def unregister_session(self, session_id: str) -> None:
        with self._lock:
            info = self._by_session.get(session_id)
            if info is not None:
                self._detach_locked(info)

    def resolve_session(self, session_id: str) -> InfoT:
        with self._lock:
            info = self._by_session.get(session_id)
        if info is None:
            raise NotRegisteredError(f"{self._SESSION_LABEL} '{session_id}' is not registered")
        return info

    def resolve_instance_id(self, instance_id: str) -> InfoT:
        with self._lock:
            info = self._by_instance.get(instance_id)
        if info is None:
            raise NotRegisteredError(f"{self._INSTANCE_LABEL} '{instance_id}' is not registered")
        return info

    def _replace_and_store_locked(self, instance_id: str, **changes) -> InfoT | None:
        """_lock 보유 상태에서 frozen info를 replace로 갱신하고 양쪽 dict 동기화."""
        info = self._by_instance.get(instance_id)
        if info is None:
            return None
        updated = replace(info, **changes)  # type: ignore[type-var]
        self._by_instance[instance_id] = updated
        self._by_session[updated.session_id] = updated  # type: ignore[attr-defined]
        return updated

    def touch_last_seen(self, instance_id: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            self._replace_and_store_locked(instance_id, last_seen_at=now)

    def _list_all(self) -> list[InfoT]:
        with self._lock:
            return list(self._by_instance.values())


@dataclass(frozen=True)
class InstanceInfo:
    instance_id: str
    session_id: str
    role: str
    registered_at: str
    description: str = ""
    cwd: str = ""
    wait_mode: Literal["auto", "manual", "unknown"] = "unknown"
    last_seen_at: str | None = None
    accepting: bool = True


class InstanceRegistry(_BidirectionalRegistry[InstanceInfo]):
    """Bidirectional mapping between MCP session_id and user-chosen instance_id.
    Re-registering the same instance_id from a new session replaces the prior session's entry.
    """

    _SESSION_LABEL = "Session"
    _INSTANCE_LABEL = "Instance"

    def register(
        self,
        session_id: str,
        instance_id: str,
        role: str = "worker",
        description: str = "",
        cwd: str = "",
        wait_mode: Literal["auto", "manual"] | None = None,
    ) -> InstanceInfo:
        info = InstanceInfo(
            instance_id=instance_id,
            session_id=session_id,
            role=role,
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            description=description,
            cwd=cwd,
            wait_mode=wait_mode if wait_mode is not None else "unknown",
        )
        return self.register_info(info)

    def list_instances(self) -> list[InstanceInfo]:
        return self._list_all()

    def set_accepting(self, instance_id: str, accepting: bool) -> None:
        with self._lock:
            updated = self._replace_and_store_locked(instance_id, accepting=accepting)
        if updated is None:
            raise NotRegisteredError(f"Instance '{instance_id}' is not registered")
