# src/agent_agora/dispatcher.py
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any

from agent_agora.registry import InstanceRegistry, NotRegisteredError


def _fmt_payload(payload: Any) -> str:
    """Compact one-line JSON. Not truncated — full content for the log line."""
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(payload)


# 12 ANSI foreground colors (standard + bright). Stable hash → same instance always
# gets the same color across the server's lifetime.
_COLOR_PALETTE = (
    "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[35m", "\033[36m",
    "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m",
)
_RESET = "\033[0m"


def _color_for(instance_id: str) -> str:
    h = hashlib.md5(instance_id.encode("utf-8")).digest()[0]
    return _COLOR_PALETTE[h % len(_COLOR_PALETTE)]


def _colored(instance_id: str) -> str:
    return f"{_color_for(instance_id)}{instance_id}{_RESET}"


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
        target: list[str],
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
    ) -> dict[str, str]:
        """Dispatch a command to one or more registered instances.

        `target` is always a non-empty list of instance_ids. Pass `["_broadcast"]`
        (length 1) to fan out to all other registered instances. Mixing `_broadcast`
        with explicit instance_ids is a ValueError.

        `reply_to`: instance_id that should receive the recipient's reply. None means
        the recipient defaults to replying to `source`. Useful for multi-hop chains
        where you want a downstream worker to short-circuit the reply back to the
        original requester instead of going back through the broker. Validated at
        dispatch time: an unregistered reply_to raises NotRegisteredError.

        `in_reply_to`: command_id of the message this dispatch is answering. When
        sending a reply, set this to the original envelope's `id`. Used by the
        original requester (or any waiter) to correlate replies.

        Returns `{"command_id": <uuid>, "created_at": <ISO-8601 UTC>}`.
        """
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        if not isinstance(target, list) or not target:
            raise ValueError("target must be a non-empty list of instance_ids")
        if self.BROADCAST_TARGET in target and target != [self.BROADCAST_TARGET]:
            raise ValueError(
                f"'{self.BROADCAST_TARGET}' cannot be mixed with explicit instance_ids"
            )
        cmd_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            if reply_to is not None:
                self._registry.resolve_instance_id(reply_to)
            if target == [self.BROADCAST_TARGET]:
                targets = [
                    info.instance_id
                    for info in self._registry.list_instances()
                    if info.instance_id != source
                ]
            else:
                for t in target:
                    self._registry.resolve_instance_id(t)
                targets = list(target)
            for t in targets:
                command = {
                    "id": cmd_id,
                    "source": source,
                    "target": t,
                    "payload": payload,
                    "created_at": now,
                    "expect_result": expect_result,
                    "reply_to": reply_to,
                    "in_reply_to": in_reply_to,
                }
                self._queues[t].append(command)
                self._wake(t)
                print(
                    f"[agora] {_colored(source)} -> {_colored(t)} : {_fmt_payload(payload)}",
                    flush=True,
                )
        return {"command_id": cmd_id, "created_at": now}

    def _wake(self, target: str) -> None:
        waiters = self._waiters.pop(target, [])
        for f in waiters:
            if not f.done():
                f.set_result(None)

    async def wait(
        self,
        instance_id: str,
        timeout_ms: int | None = None,
        from_sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Drain pending commands for `instance_id`.

        If `from_sources` is provided, only commands whose `source` matches one of
        the names in the list are drained; other commands stay in the queue for a
        subsequent unfiltered (or differently-filtered) `wait`.
        """
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        # Validate caller; raises NotRegisteredError if not
        self._registry.resolve_instance_id(instance_id)
        effective = self._default_timeout_ms if timeout_ms is None else timeout_ms
        loop = asyncio.get_running_loop()

        def _drain_matching() -> list[dict[str, Any]]:
            queued = self._queues.get(instance_id, [])
            if not queued:
                return []
            if from_sources is None:
                self._queues[instance_id] = []
                return list(queued)
            allowed = set(from_sources)
            matched = [c for c in queued if c["source"] in allowed]
            if not matched:
                return []
            self._queues[instance_id] = [c for c in queued if c["source"] not in allowed]
            return matched

        async with self._lock:
            # Re-check under lock: close() may have run fully between the pre-lock
            # check above and acquiring the lock, leaving a dangling future otherwise.
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            drained = _drain_matching()
            if drained:
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

        # Future was set with a result. DispatcherClosed propagated already.
        async with self._lock:
            drained = _drain_matching()
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
