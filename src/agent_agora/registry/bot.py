"""v4 BotRegistry — bot-only namespace, parallel to InstanceRegistry (결정 16).

Plan E: 공통 베이스 _BidirectionalRegistry를 상속한다. 봇 고유의 subscribe/observer
파생 인덱스는 _on_store_locked/_on_detach_locked 훅으로만 베이스에 붙인다.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Literal

from agent_agora.registry.core import NotRegisteredError, _BidirectionalRegistry

__all__ = ["BotInfo", "BotMode", "BotRegistry", "NotRegisteredError"]

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


class BotRegistry(_BidirectionalRegistry[BotInfo]):
    """봇 전용 네임스페이스. subscribe schema -> 봇 역인덱스(fan-out 라우팅용)를 보관한다.
    재시작 시 복원하지 않는다 — 봇은 살아있는 MCP client 세션이라 재접속 시 재등록한다."""

    _SESSION_LABEL = "Bot session"
    _INSTANCE_LABEL = "Bot"

    def __init__(self) -> None:
        super().__init__()
        self._subscribers: dict[str, set[str]] = {}   # schema_name -> {handler bot id}
        self._observers: set[str] = set()

    def _on_store_locked(self, info: BotInfo) -> None:
        if info.bot_mode == "observer":
            self._observers.add(info.instance_id)
        else:
            for s in info.subscribe_schemas:
                self._subscribers.setdefault(s, set()).add(info.instance_id)

    def _on_detach_locked(self, info: BotInfo) -> None:
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
        return self.register_info(info)

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
        return self._list_all()
