"""대시보드 SSE 이벤트 브로커 — in-process pub/sub.

각 SSE 구독자마다 asyncio.Queue. publisher는 모든 큐에 broadcast.
operator_inbox_message는 target_operator 매칭 구독자에게만 전달.
큐 overflow 시 가장 오래된 이벤트를 drop.

attach_to_dispatcher로 dispatcher의 event hook에 자동 구독 — dispatch·
register·unregister 이벤트를 SSE 이벤트로 변환해 publish.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Subscriber:
    operator_user: str
    queue: asyncio.Queue

    async def get(self) -> dict:
        return await self.queue.get()


class EventBroker:
    def __init__(self, *, max_queue: int = 1000) -> None:
        self._subscribers: list[Subscriber] = []
        self._max_queue = max_queue

    def subscribe(self, *, operator_user: str) -> Subscriber:
        q: asyncio.Queue = asyncio.Queue()
        sub = Subscriber(operator_user=operator_user, queue=q)
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        try:
            self._subscribers.remove(sub)
        except ValueError:
            pass

    def publish(self, event: dict) -> None:
        """이벤트를 모든 매칭 구독자에게 비동기 broadcast.

        operator_inbox_message는 target_operator 매칭 구독자에게만.
        큐 만원이면 가장 오래된 이벤트 drop.
        """
        target = event.get("target_operator") if event.get("type") == "operator_inbox_message" else None
        for sub in list(self._subscribers):
            if target is not None and sub.operator_user != target:
                continue
            self._push(sub, event)

    def _push(self, sub: Subscriber, event: dict) -> None:
        q = sub.queue
        if q.qsize() >= self._max_queue:
            # drop oldest non-blockingly
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(event)

    def attach_to_dispatcher(self, dispatcher) -> None:
        """dispatcher의 event hook에 자동 구독."""
        dispatcher.register_dispatch_hook(self._on_dispatch)
        dispatcher.register_register_hook(self._on_register)
        dispatcher.register_unregister_hook(self._on_unregister)

    def _on_dispatch(self, envelope) -> None:
        # Envelope에 'schema' 필드는 없다 — 스키마는 payload['msgtype']로 식별된다
        # (agora 규약: schemas.py SchemaRegistry는 msgtype property를 강제하는
        # 카탈로그이고, dispatcher는 payload['msgtype']로 schema entry를 조회한다).
        payload = getattr(envelope, "payload", None)
        msgtype = payload.get("msgtype") if isinstance(payload, dict) else None
        self.publish({
            "type": "message_dispatched",
            "from": getattr(envelope, "source", None),
            "to": getattr(envelope, "target", None),
            "schema": msgtype,
            "conversation_id": getattr(envelope, "conversation_id", None),
            "timestamp": getattr(envelope, "created_at", None),
        })
        # 운영자 대상 메시지면 별도 이벤트로도 publish
        recipient = getattr(envelope, "target", "") or ""
        if recipient.startswith("operator:"):
            self.publish({
                "type": "operator_inbox_message",
                "target_operator": recipient[len("operator:"):],
                "sender": getattr(envelope, "source", None),
                "schema": msgtype,
                "timestamp": getattr(envelope, "created_at", None),
            })

    def _on_register(self, info) -> None:
        self.publish({
            "type": "instance_registered",
            "instance_id": getattr(info, "instance_id", None),
            "role": getattr(info, "role", None),
        })

    def _on_unregister(self, instance_id: str) -> None:
        self.publish({
            "type": "instance_unregistered",
            "instance_id": instance_id,
        })
