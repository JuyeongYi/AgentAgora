"""v4 BotRegistry — bot-only namespace, parallel to InstanceRegistry (결정 16)."""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, replace
from typing import Literal

from agent_agora.registry import NotRegisteredError

BotMode = Literal["handler", "observer"]


@dataclass(frozen=True)
class BotInfo:
    instance_id: str
    session_id: str
    description: str
    bot_mode: BotMode
    subscribe_schemas: tuple[str, ...] = ()
    emit_schemas: tuple[str, ...] = ()
    registered_at: str = ""
    last_seen_at: str | None = None


class BotRegistry:
    """봇 전용 네임스페이스. subscribe schema -> 봇 역인덱스(fan-out 라우팅용)를 보관한다.
    재시작 시 복원하지 않는다 — 봇은 살아있는 MCP client 세션이라 재접속 시 재등록한다."""

    def __init__(self) -> None:
        self._by_session: dict[str, BotInfo] = {}
        self._by_instance: dict[str, BotInfo] = {}
        self._subscribers: dict[str, set[str]] = {}   # schema_name -> {handler bot id}
        self._observers: set[str] = set()
        self._lock = threading.Lock()

    def _detach_locked(self, info: BotInfo) -> None:
        """인덱스에서 한 봇을 떼어낸다. _lock 보유 상태에서 호출."""
        self._by_session.pop(info.session_id, None)
        self._by_instance.pop(info.instance_id, None)
        self._observers.discard(info.instance_id)
        for s in info.subscribe_schemas:
            subs = self._subscribers.get(s)
            if subs is not None:
                subs.discard(info.instance_id)
                if not subs:
                    self._subscribers.pop(s, None)

    def register(
        self,
        session_id: str,
        instance_id: str,
        description: str,
        bot_mode: BotMode,
        subscribe_schemas: tuple[str, ...] | list[str] = (),
        emit_schemas: tuple[str, ...] | list[str] = (),
    ) -> BotInfo:
        info = BotInfo(
            instance_id=instance_id, session_id=session_id, description=description,
            bot_mode=bot_mode,
            subscribe_schemas=tuple(subscribe_schemas),
            emit_schemas=tuple(emit_schemas),
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        with self._lock:
            prior = self._by_instance.get(instance_id)
            if prior is not None:
                self._detach_locked(prior)
            prior_sess = self._by_session.get(session_id)
            if prior_sess is not None:
                self._detach_locked(prior_sess)
            self._by_session[session_id] = info
            self._by_instance[instance_id] = info
            if bot_mode == "observer":
                self._observers.add(instance_id)
            else:
                for s in info.subscribe_schemas:
                    self._subscribers.setdefault(s, set()).add(instance_id)
        return info

    def unregister_session(self, session_id: str) -> None:
        with self._lock:
            info = self._by_session.get(session_id)
            if info is not None:
                self._detach_locked(info)

    def resolve_session(self, session_id: str) -> BotInfo:
        with self._lock:
            info = self._by_session.get(session_id)
        if info is None:
            raise NotRegisteredError(f"Bot session '{session_id}' is not registered")
        return info

    def resolve_instance_id(self, instance_id: str) -> BotInfo:
        with self._lock:
            info = self._by_instance.get(instance_id)
        if info is None:
            raise NotRegisteredError(f"Bot '{instance_id}' is not registered")
        return info

    def is_bot(self, instance_id: str) -> bool:
        with self._lock:
            return instance_id in self._by_instance

    def subscribers_of(self, schema_name: str) -> set[str]:
        """schema_name을 구독하는 handler 봇 instance_id 집합 (다봇 fan-out용)."""
        with self._lock:
            return set(self._subscribers.get(schema_name, set()))

    def observers(self) -> set[str]:
        with self._lock:
            return set(self._observers)

    def list_bots(self) -> list[BotInfo]:
        with self._lock:
            return list(self._by_instance.values())

    def touch_last_seen(self, instance_id: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            info = self._by_instance.get(instance_id)
            if info is None:
                return
            updated = replace(info, last_seen_at=now)
            self._by_instance[instance_id] = updated
            self._by_session[updated.session_id] = updated
