# src/agent_agora/dispatcher.py
from __future__ import annotations

import asyncio
import datetime
import uuid
from collections import defaultdict
from typing import Any

from agent_agora.registry import InstanceRegistry, NotRegisteredError


class DispatcherClosed(Exception):
    pass


class Dispatcher:
    """Per-instance command queues with future-based wake. Broadcast target fans out
    to all OTHER registered instances (excludes sender)."""

    BROADCAST_TARGET = "_broadcast"

    def __init__(self, registry: InstanceRegistry, default_timeout_ms: int = 60000) -> None:
        self._registry = registry
        self._default_timeout_ms = default_timeout_ms
        self._queues: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._waiters: dict[str, list[asyncio.Future]] = defaultdict(list)
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def default_timeout_ms(self) -> int:
        return self._default_timeout_ms

    async def dispatch(
        self,
        source: str,
        target: str,
        payload: Any,
        expect_result: bool = False,
    ) -> str:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        cmd_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with self._lock:
            if target == self.BROADCAST_TARGET:
                targets = [
                    info.instance_id
                    for info in self._registry.list_instances()
                    if info.instance_id != source
                ]
            else:
                # Validate the target exists; raises NotRegisteredError if not
                self._registry.resolve_instance_id(target)
                targets = [target]
            for t in targets:
                command = {
                    "id": cmd_id,
                    "source": source,
                    "target": t,
                    "payload": payload,
                    "created_at": now,
                    "expect_result": expect_result,
                }
                self._queues[t].append(command)
                self._wake(t)
        return cmd_id

    def _wake(self, target: str) -> None:
        waiters = self._waiters.pop(target, [])
        for f in waiters:
            if not f.done():
                f.set_result(None)

    async def wait(self, instance_id: str, timeout_ms: int | None = None) -> list[dict[str, Any]]:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        # Validate caller; raises NotRegisteredError if not
        self._registry.resolve_instance_id(instance_id)
        effective = self._default_timeout_ms if timeout_ms is None else timeout_ms
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._queues[instance_id]:
                drained = self._queues.pop(instance_id, [])
                return drained
            fut: asyncio.Future = loop.create_future()
            self._waiters[instance_id].append(fut)

        try:
            if effective <= 0:
                await fut
            else:
                await asyncio.wait_for(fut, timeout=effective / 1000.0)
        except asyncio.TimeoutError:
            async with self._lock:
                if fut in self._waiters.get(instance_id, []):
                    self._waiters[instance_id].remove(fut)
            return []

        # Future was set — commands arrived OR dispatcher closed
        if self._closed:
            raise DispatcherClosed("Dispatcher closed")
        async with self._lock:
            drained = self._queues.pop(instance_id, [])
        return drained

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            all_waiters = self._waiters
            self._waiters = defaultdict(list)
        for target, futs in all_waiters.items():
            for f in futs:
                if not f.done():
                    f.set_exception(DispatcherClosed("Dispatcher closed"))
