# src/agent_agora/dispatcher.py
from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import uuid
from collections import defaultdict
from typing import Any, Literal

from agent_agora.envelope import (
    Envelope,
    _PRIORITY_RANK,
    make_envelope,
    validate_payload_size,
    validate_priority,
)
from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.errors import AgoraError
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.schemas import SchemaRegistry
from agent_agora.dispatch_console import _colored, _fmt_payload


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _envelope_to_dict(env: Envelope) -> dict[str, Any]:
    return dataclasses.asdict(env)


class DispatcherClosed(Exception):
    pass


class Dispatcher:
    """v3 message router. In-memory hot path + SQLite cold path via AsyncWriteQueue."""

    def __init__(
        self,
        registry: InstanceRegistry,
        persistence: Persistence,
        write_queue: AsyncWriteQueue,
        *,
        schema_registry: SchemaRegistry,
        bot_registry: BotRegistry,
        comm_matrix: CommMatrix,
        default_timeout_ms: int = 60000,
        max_inbox_depth: int = 100,
        close_timeout_ms: int = 300_000,
        dead_session_timeout_ms: int = 1_800_000,
        gc_retention_days: int = 90,
        file_store=None,
        file_retention_days: int = 7,
    ) -> None:
        self._registry = registry
        self._persistence = persistence
        self._write_queue = write_queue
        self._schema_registry = schema_registry
        self._bot_registry = bot_registry
        self._comm_matrix = comm_matrix
        self._default_timeout_ms = default_timeout_ms
        self._max_inbox_depth = max_inbox_depth
        # close_timeout_ms·dead_session_timeout_ms·gc_retention_days·file_store·
        # file_retention_days는 Sweeper로만 전달된다 — Dispatcher 자신은 쓰지 않으므로
        # 인스턴스 속성으로 보관하지 않는다.
        self._queues: dict[str, list[Envelope]] = defaultdict(list)
        self._waiters: dict[str, list[asyncio.Future]] = defaultdict(list)
        self._closed = False
        self._lock = asyncio.Lock()
        # v3 state
        from agent_agora.conversation_store import ConversationStore
        self._conv = ConversationStore(persistence)
        # _in_flight[source][cmd_id] = set of primary replyers still pending
        self._in_flight: dict[str, dict[str, set[str]]] = {}
        self._last_dispatch_to: dict[str, str] = {}
        from agent_agora.sweeper import Sweeper
        self.sweeper = Sweeper(
            self._conv, registry, bot_registry, schema_registry, persistence,
            close_timeout_ms=close_timeout_ms,
            dead_session_timeout_ms=dead_session_timeout_ms,
            gc_retention_days=gc_retention_days,
            file_store=file_store,
            file_retention_days=file_retention_days,
        )
        from agent_agora.dispatch_persistence import DispatchPersistence
        self._dispatch_persistence = DispatchPersistence(persistence, write_queue)

    @property
    def default_timeout_ms(self) -> int:
        return self._default_timeout_ms

    def _wake(self, target: str) -> None:
        waiters = self._waiters.pop(target, [])
        for f in waiters:
            if not f.done():
                f.set_result(None)

    def _validate_payload(self, payload: Any) -> str:
        """payload의 msgtype을 검증하고 schema validate. msgtype 문자열을 반환.
        실패 시 AgoraError(payload_missing_msgtype | unknown_msgtype | schema_violation)."""
        if not isinstance(payload, dict) or "msgtype" not in payload:
            raise AgoraError("payload_missing_msgtype")
        msgtype = payload["msgtype"]
        validator = self._schema_registry.validator(msgtype)
        if validator is None:
            raise AgoraError("unknown_msgtype", msgtype=msgtype)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
        if errors:
            detail = "; ".join(e.message for e in errors[:3])
            raise AgoraError("schema_violation", detail=detail)
        return msgtype

    async def dispatch(
        self,
        source: str,
        target: str | None,
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low", "normal", "high"] = "normal",
        deadline_ts: str | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        if target is not None and (not isinstance(target, str) or not target):
            raise ValueError("target must be a non-empty instance_id string or None")
        msgtype = self._validate_payload(payload)
        payload_bytes = validate_payload_size(payload)
        priority_rank = validate_priority(priority)

        # target resolution — worker or bot (결정 22: 봇 체커 우선)
        target_kind: str | None = None  # "worker" | "bot"
        if target is not None:
            if self._bot_registry.is_bot(target):
                target_kind = "bot"
                bot_info = self._bot_registry.resolve_instance_id(target)
                if bot_info.bot_mode == "handler" and msgtype not in bot_info.subscribe_schemas:
                    raise AgoraError("unhandled_schema", bot=target, msgtype=msgtype)
            else:
                self._registry.resolve_instance_id(target)  # raises NotRegisteredError
                target_kind = "worker"
        if reply_to is not None:
            self._registry.resolve_instance_id(reply_to)
        cc_list = list(cc) if cc else []
        cc_list = [c for c in cc_list if c != source and c != target]
        if reply_to is not None and reply_to in cc_list:
            raise ValueError("instance cannot be both reply_to and cc")
        for c in cc_list:
            self._registry.resolve_instance_id(c)

        # comm-matrix ACL — worker→worker primary dispatch만 검사 (봇·schema-routed·cc 제외)
        if target_kind == "worker" and not self._comm_matrix.is_allowed(source, target):
            raise AgoraError("comm_denied", from_=source, to=target)

        # 봇 체커 — msgtype 구독 handler 봇 + observer
        subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
        observer_bots = sorted(self._bot_registry.observers())
        if target is None and not subscriber_bots:
            raise AgoraError("no_route", msgtype=msgtype)

        cmd_id = str(uuid.uuid4())
        now = _now_iso()
        conv_id, is_new_conv, substituted = self._conv.resolve_conversation_id(conversation_id, in_reply_to)

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            # primary inbox depth (target 있을 때만)
            if target is not None and len(self._queues[target]) >= self._max_inbox_depth:
                raise ValueError(f"inbox_full: {target} has {len(self._queues[target])} pending")
            cc_deliver: list[str] = []
            skipped_full: list[str] = []
            for c in cc_list:
                if len(self._queues[c]) >= self._max_inbox_depth:
                    skipped_full.append(c)
                else:
                    cc_deliver.append(c)

            if is_new_conv or not self._conv.has(conv_id):
                self._conv.put(conv_id, self._conv.new_state(kind="direct"))
            state = self._conv.get(conv_id)
            self._conv.add_participant(state, source, role="primary", delivered=True)
            if target is not None:
                self._conv.add_participant(state, target, role="primary", delivered=True)
            for c in cc_deliver:
                self._conv.add_participant(state, c, role="cc", delivered=True)
            for c in skipped_full:
                self._conv.add_participant(state, c, role="cc", delivered=False)
            state["last_message_at"] = now
            state["message_count"] += 1

            self._conv.record_command(cmd_id, conv_id, source)

            def _make(tid: str, das: str, *, er: bool, cl: bool) -> Envelope:
                return make_envelope(
                    cmd_id=cmd_id, source=source, target=tid, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=er, reply_to=reply_to,
                    cc=(cc_list if cc_list else None),
                    delivered_as=das, dispatch_kind="direct",
                    in_reply_to=in_reply_to,
                    closing=cl,
                    priority=priority, deadline_ts=deadline_ts,
                )

            # primary envelope (target 있을 때만). primary/cc observer는 closing 플래그를
            # 그대로 싣는다(기존 동작 유지). 봇 fan-out 봉투는 closing=False — 봇은
            # conversation 종결 참가자가 아니다.
            primary_env: Envelope | None = None
            if target is not None:
                primary_env = _make(target, "primary", er=expect_result, cl=closing)
                self._queues[target].append(primary_env)
                self._last_dispatch_to[target] = now
                self._wake(target)

            if expect_result and target is not None and target != source and target_kind != "bot":
                self._in_flight.setdefault(source, {}).setdefault(cmd_id, set()).add(target)

            # cc observer envelopes (명시 cc)
            cc_envs: list[Envelope] = []
            for c in cc_deliver:
                e = _make(c, "cc", er=expect_result, cl=closing)
                cc_envs.append(e)
                self._queues[c].append(e)
                self._last_dispatch_to[c] = now
                self._wake(c)

            # subscriber 봇 fan-out (delivered_as=subscribed). target과 같은 봇은 중복 제외.
            sub_envs: list[Envelope] = []
            for bot_id in subscriber_bots:
                if bot_id == target:
                    continue
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                e = _make(bot_id, "subscribed", er=False, cl=False)
                sub_envs.append(e)
                self._queues[bot_id].append(e)
                self._conv.add_participant(state, bot_id, role="cc", delivered=True)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)

            # observer 봇 fan-out (delivered_as=cc)
            obs_envs: list[Envelope] = []
            for bot_id in observer_bots:
                if bot_id == target or bot_id in subscriber_bots:
                    continue
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                e = _make(bot_id, "cc", er=False, cl=False)
                obs_envs.append(e)
                self._queues[bot_id].append(e)
                self._conv.add_participant(state, bot_id, role="cc", delivered=True)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)

            # reply correlation: decrement in_flight for original source
            if in_reply_to is not None:
                original_conv = self._conv.conv_id_of(in_reply_to)
                if original_conv is not None:
                    for _original_sender, pending_map in self._in_flight.items():
                        s = pending_map.get(in_reply_to)
                        if s is not None and source in s:
                            s.discard(source)
                            if not s:
                                pending_map.pop(in_reply_to, None)

            # closing handling (primary source only)
            if closing and state["participants"].get(source, {}).get("role") == "primary":
                if source not in state["closed_by"]:
                    state["closed_by"].append(source)
                if state["status"] == "open":
                    state["status"] = "half_closed"
                self._conv.maybe_close(conv_id, state)

            await self._dispatch_persistence.persist_dispatch_txn(
                state=state, conv_id=conv_id, is_new_conv=is_new_conv,
                env=primary_env, cc_envs=cc_envs + sub_envs + obs_envs,
                skipped_full=skipped_full,
                payload_bytes=payload_bytes, priority_rank=priority_rank,
            )

            _to = _colored(target) if target is not None else "(schema-routed)"
            print(
                f"[agora] {_colored(source)} -> {_to}"
                + (f" (cc: {','.join(_colored(c) for c in cc_deliver)})" if cc_deliver else "")
                + (f" (bots: {','.join(_colored(b) for b in subscriber_bots)})" if subscriber_bots else "")
                + f" : {_fmt_payload(payload)}",
                flush=True,
            )

        dispatched_to: list[dict[str, str]] = []
        if target is not None:
            dispatched_to.append({"instance_id": target, "as": "primary"})
        dispatched_to += [{"instance_id": c, "as": "cc"} for c in cc_deliver]
        dispatched_to += [{"instance_id": b, "as": "subscribed"}
                          for b in subscriber_bots if b != target]
        return {
            "command_id": cmd_id,
            "created_at": now,
            "conversation_id": conv_id,
            "conversation_id_substituted": substituted,
            "dispatched_to": dispatched_to,
            "target_inbox_depth_after": (
                {target: len(self._queues[target])} if target is not None else {}),
            "skipped_full": skipped_full,
        }

    async def broadcast(
        self,
        source: str,
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low", "normal", "high"] = "normal",
        deadline_ts: str | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        msgtype = self._validate_payload(payload)
        payload_bytes = validate_payload_size(payload)
        priority_rank = validate_priority(priority)
        if reply_to is not None:
            self._registry.resolve_instance_id(reply_to)

        targets = [
            info.instance_id for info in self._registry.list_instances()
            if info.instance_id != source
        ]
        # comm-matrix ACL — 금지된 worker target은 fan-out에서 제외, denied로 보고
        denied: list[str] = []
        allowed_targets: list[str] = []
        for t in targets:
            (allowed_targets if self._comm_matrix.is_allowed(source, t) else denied).append(t)
        targets = allowed_targets
        denied.sort()
        subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
        observer_bots = sorted(self._bot_registry.observers())
        cmd_id = str(uuid.uuid4())
        now = _now_iso()
        conv_id, is_new_conv, substituted = self._conv.resolve_conversation_id(conversation_id, in_reply_to)

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            # inbox depth on broadcast: skip full targets
            deliverable: list[str] = []
            skipped_full: list[str] = []
            for t in targets:
                if len(self._queues[t]) >= self._max_inbox_depth:
                    skipped_full.append(t)
                else:
                    deliverable.append(t)

            if is_new_conv or not self._conv.has(conv_id):
                self._conv.put(conv_id, self._conv.new_state(kind="broadcast"))
            state = self._conv.get(conv_id)
            state["kind"] = "broadcast"
            self._conv.add_participant(state, source, role="primary", delivered=True)
            for t in deliverable:
                self._conv.add_participant(state, t, role="primary", delivered=True)
            for t in skipped_full:
                self._conv.add_participant(state, t, role="primary", delivered=False)
            state["last_message_at"] = now
            state["message_count"] += 1

            envs: list[Envelope] = []
            for t in deliverable:
                env = make_envelope(
                    cmd_id=cmd_id, source=source, target=t, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=expect_result, reply_to=reply_to,
                    cc=None, delivered_as="primary", dispatch_kind="broadcast",
                    in_reply_to=in_reply_to,
                    closing=closing, priority=priority, deadline_ts=deadline_ts,
                )
                envs.append(env)
                self._queues[t].append(env)
                self._conv.set_conv_of(cmd_id, conv_id)
                self._last_dispatch_to[t] = now
                self._wake(t)
                if expect_result:
                    self._in_flight.setdefault(source, {}).setdefault(cmd_id, set()).add(t)

            # subscriber 봇 fan-out (delivered_as=subscribed)
            for bot_id in subscriber_bots:
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                s_env = make_envelope(
                    cmd_id=cmd_id, source=source, target=bot_id, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=False, reply_to=reply_to, cc=None,
                    delivered_as="subscribed", dispatch_kind="broadcast",
                    in_reply_to=in_reply_to,
                    closing=False, priority=priority, deadline_ts=deadline_ts,
                )
                envs.append(s_env)
                self._queues[bot_id].append(s_env)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)
            # observer 봇 fan-out (delivered_as=cc)
            for bot_id in observer_bots:
                if bot_id in subscriber_bots:
                    continue
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                o_env = make_envelope(
                    cmd_id=cmd_id, source=source, target=bot_id, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=False, reply_to=reply_to, cc=None,
                    delivered_as="cc", dispatch_kind="broadcast",
                    in_reply_to=in_reply_to,
                    closing=False, priority=priority, deadline_ts=deadline_ts,
                )
                envs.append(o_env)
                self._queues[bot_id].append(o_env)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)
            self._conv.record_command(cmd_id, conv_id, source)
            # closing → if broadcast announcement, close immediately
            if closing:
                state["status"] = "closed"
                state["closed_at"] = _now_iso()
                state["closed_by"] = list(state["participants"].keys())

            await self._dispatch_persistence.persist_dispatch_txn(
                state=state, conv_id=conv_id, is_new_conv=is_new_conv,
                env=None, cc_envs=envs, skipped_full=skipped_full,
                payload_bytes=payload_bytes, priority_rank=priority_rank,
                is_broadcast=True,
            )

            print(
                f"[agora] {_colored(source)} "
                + ("Announcement" if closing else "Broadcast")
                + f" : {_fmt_payload(payload)}",
                flush=True,
            )

        return {
            "command_id": cmd_id,
            "created_at": now,
            "conversation_id": conv_id,
            "conversation_id_substituted": substituted,
            "dispatched_to": [{"instance_id": t, "as": "primary"} for t in deliverable]
                + [{"instance_id": b, "as": "subscribed"} for b in subscriber_bots]
                + [{"instance_id": b, "as": "cc"} for b in observer_bots
                   if b not in subscriber_bots],
            "target_inbox_depth_after": {t: len(self._queues[t]) for t in deliverable},
            "skipped_full": skipped_full,
            "denied": denied,
        }

    async def bot_emit(
        self,
        source: str,
        payload: Any,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """봇 결과 emit (결정 25). in_reply_to 지정 시 원 메시지의 source로 라우팅,
        미지정 시 payload msgtype 구독 봇에 schema-routed fan-out. 항상 observer cc."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        msgtype = self._validate_payload(payload)
        payload_bytes = validate_payload_size(payload)
        priority_rank = validate_priority("normal")

        reply_target: str | None = None
        if in_reply_to is not None:
            reply_target = self._conv.source_of(in_reply_to)
            if reply_target is None:
                reply_target = self._persistence.lookup_source_for(in_reply_to)
        subscriber_bots: list[str] = []
        if in_reply_to is None:
            subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
        observer_bots = sorted(self._bot_registry.observers())

        cmd_id = str(uuid.uuid4())
        now = _now_iso()
        conv_id, is_new_conv, substituted = self._conv.resolve_conversation_id(None, in_reply_to)

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            if is_new_conv or not self._conv.has(conv_id):
                self._conv.put(conv_id, self._conv.new_state(kind="direct"))
            state = self._conv.get(conv_id)
            self._conv.add_participant(state, source, role="cc", delivered=True)
            state["last_message_at"] = now
            state["message_count"] += 1
            self._conv.record_command(cmd_id, conv_id, source)

            envs: list[Envelope] = []
            delivered: list[dict[str, str]] = []
            skipped_full: list[str] = []

            def _enqueue(tid: str, das: str) -> None:
                if len(self._queues[tid]) >= self._max_inbox_depth:
                    skipped_full.append(tid)
                    return
                e = make_envelope(
                    cmd_id=cmd_id, source=source, target=tid, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=False, reply_to=None, cc=None,
                    delivered_as=das, dispatch_kind="direct",
                    in_reply_to=in_reply_to, closing=False,
                    priority="normal", deadline_ts=None,
                )
                envs.append(e)
                self._queues[tid].append(e)
                self._conv.add_participant(
                    state, tid, role="primary" if das == "primary" else "cc", delivered=True)
                self._last_dispatch_to[tid] = now
                self._wake(tid)
                delivered.append({"instance_id": tid, "as": das})

            if reply_target is not None:
                _enqueue(reply_target, "primary")
            for bot_id in subscriber_bots:
                if bot_id == reply_target:
                    continue
                _enqueue(bot_id, "subscribed")
            for bot_id in observer_bots:
                if bot_id == reply_target or bot_id in subscriber_bots:
                    continue
                _enqueue(bot_id, "cc")

            await self._dispatch_persistence.persist_dispatch_txn(
                state=state, conv_id=conv_id, is_new_conv=is_new_conv,
                env=None, cc_envs=envs, skipped_full=skipped_full,
                payload_bytes=payload_bytes, priority_rank=priority_rank,
            )
            print(
                f"[agora] {_colored(source)} bot_emit"
                + (f" -> {_colored(reply_target)}" if reply_target else " (schema-routed)")
                + f" : {_fmt_payload(payload)}",
                flush=True,
            )

        return {
            "command_id": cmd_id, "created_at": now, "conversation_id": conv_id,
            "conversation_id_substituted": substituted,
            "dispatched_to": delivered, "skipped_full": skipped_full,
        }

    def _touch_last_seen(self, instance_id: str) -> None:
        """instance_id가 봇이면 BotRegistry, 워커면 InstanceRegistry의 last_seen을 갱신한다."""
        if self._bot_registry.is_bot(instance_id):
            self._bot_registry.touch_last_seen(instance_id)
        else:
            self._registry.touch_last_seen(instance_id)

    async def flush(
        self,
        instance_id: str,
        from_sources: list[str] | None = None,
        sort: Literal["fifo", "priority"] = "priority",
        by_conversation: str | None = None,
    ) -> list[dict[str, Any]]:
        """현재 큐에 있는 메시지를 즉시 드레인하고 반환한다 (논블로킹)."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        # 봇 instance_id는 bot_registry에서, 워커는 worker registry에서 검증 (결정 22)
        if not self._bot_registry.is_bot(instance_id):
            self._registry.resolve_instance_id(instance_id)

        def _matches(env: Envelope) -> bool:
            if from_sources is not None and env.source not in set(from_sources):
                return False
            if by_conversation is not None and env.conversation_id != by_conversation:
                return False
            return True

        def _drain_matching() -> list[Envelope]:
            queued = self._queues.get(instance_id, [])
            if not queued:
                return []
            if from_sources is None and by_conversation is None:
                self._queues[instance_id] = []
                return list(queued)
            matched = [c for c in queued if _matches(c)]
            if not matched:
                return []
            self._queues[instance_id] = [c for c in queued if not _matches(c)]
            return matched

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            drained = _drain_matching()

        # sort — priority: 엣지 weight 1차, 메시지 priority 2차, created_at 3차
        if sort == "priority":
            drained.sort(key=lambda e: (
                -self._comm_matrix.weight_of(e.source, instance_id),
                _PRIORITY_RANK[e.priority],
                e.created_at,
                e.id,
            ))
        else:
            drained.sort(key=lambda e: (e.created_at, e.id))

        # last_seen + wait_age_ms
        self._touch_last_seen(instance_id)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        results: list[dict[str, Any]] = []
        for e in drained:
            created = datetime.datetime.fromisoformat(e.created_at)
            age_ms = int((now_dt - created).total_seconds() * 1000)
            d = _envelope_to_dict(e)
            d["wait_age_ms"] = age_ms
            results.append(d)

        # mark drained_at in SQLite (best-effort, single batch)
        if drained:
            now_iso = _now_iso()
            stmts = [
                ("UPDATE messages SET drained_at=? WHERE command_id=? AND target=?",
                 (now_iso, e.id, instance_id))
                for e in drained
            ]
            try:
                await self._write_queue.submit_transaction(stmts)
            except Exception:
                pass

        return results

    async def wait_notify(
        self, instance_id: str, timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Non-destructive long-poll. Block until instance_id's queue is
        non-empty (or timeout), then return {instance_id, pending, sources}
        WITHOUT draining. Used by the channel adapter to detect inbound.
        Advisory like peek — instance_id need not be registered (an empty
        queue just blocks, absorbing the worker/adapter startup race)."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        effective = self._default_timeout_ms if timeout_ms is None else timeout_ms
        loop = asyncio.get_running_loop()

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            fut: asyncio.Future | None = None
            if not self._queues.get(instance_id):
                fut = loop.create_future()
                self._waiters[instance_id].append(fut)

        if fut is not None:
            try:
                if effective <= 0:
                    await fut
                else:
                    await asyncio.wait_for(fut, timeout=effective / 1000.0)
            except asyncio.TimeoutError:
                async with self._lock:
                    if fut in self._waiters.get(instance_id, []):
                        self._waiters[instance_id].remove(fut)

        self._touch_last_seen(instance_id)
        async with self._lock:
            queue = self._queues.get(instance_id, [])
            return {
                "instance_id": instance_id,
                "pending": len(queue),
                "sources": sorted({e.source for e in queue}),
            }

    async def system_notify(self, target: str, payload: dict[str, Any]) -> None:
        """시스템 발신 알림을 target 인박스에 넣고 깨운다. comm-matrix·conversation·
        in_flight 머신을 우회한다 — schema 충돌 통지 등 운영 이벤트용. 영속화 안 함."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        now = _now_iso()
        env = make_envelope(
            cmd_id=str(uuid.uuid4()), source="agora-system", target=target,
            payload=payload, created_at=now, conversation_id=str(uuid.uuid4()),
            expect_result=False, delivered_as="primary", dispatch_kind="direct",
        )
        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            self._queues[target].append(env)
            self._wake(target)

    def in_flight_count(self, instance_id: str) -> int:
        """Number of expect_result=True messages sent TO instance_id that have not been replied."""
        count = 0
        for source, pending_map in self._in_flight.items():
            for cmd_id, replyers in pending_map.items():
                if instance_id in replyers:
                    count += 1
        return count

    def peek(self, targets: list[str] | None) -> dict[str, dict]:
        """Snapshot per target. Unregistered targets get registered=False."""
        if targets is None:
            targets = [i.instance_id for i in self._registry.list_instances()]
        out: dict[str, dict] = {}
        for t in targets:
            try:
                info = self._registry.resolve_instance_id(t)
                out[t] = {
                    "registered": True,
                    "queue_depth": len(self._queues.get(t, [])),
                    "in_flight": self.in_flight_count(t),
                    "last_wait_at": info.last_seen_at,
                    "last_dispatch_to_at": self._last_dispatch_to.get(t),
                    "wait_mode": info.wait_mode,
                    "accepting": info.accepting,
                }
            except NotRegisteredError:
                out[t] = {
                    "registered": False,
                    "queue_depth": None,
                    "in_flight": None,
                    "last_wait_at": None,
                    "last_dispatch_to_at": None,
                    "wait_mode": None,
                    "accepting": None,
                }
        return out

    def conversation_status(self, conv_id: str) -> dict:
        return self._conv.status(conv_id)

    def conversations_list(
        self,
        participant: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self._conv.list_conversations(participant, status, limit)

    async def close_thread(self, caller: str, conv_id: str, reason: str = "") -> dict:
        state = self._conv.get(conv_id)
        if state is None:
            return {"error": "unknown_conversation"}
        if caller not in state["participants"]:
            raise ValueError("not_a_participant")
        if state["status"] == "closed":
            return {"status": "already_closed", "conversation_id": conv_id}
        # dispatch closing to other primary participants
        others = [
            iid for iid, info in state["participants"].items()
            if iid != caller and info["role"] == "primary" and info["delivered"]
        ]
        for o in others:
            try:
                await self.dispatch(
                    source=caller, target=o,
                    payload={
                        "msgtype": "closing", "from": caller,
                        "ts": _now_iso(),
                        **({"reason": reason} if reason else {}),
                    },
                    conversation_id=conv_id, closing=True,
                )
            except (ValueError, NotRegisteredError):
                continue
        # mark caller closed_by even if no others (advisory)
        async with self._lock:
            if caller not in state["closed_by"]:
                state["closed_by"].append(caller)
            if state["status"] == "open":
                state["status"] = "half_closed"
            self._conv.maybe_close(conv_id, state)
        return {"status": state["status"], "conversation_id": conv_id}

    def restore_from_persistence(self) -> None:
        """Inst4 우려3 — 재시작 후 in-memory state 복구."""
        envs = self._persistence.restore_inflight()
        for row in envs:
            payload = json.loads(row["payload"])
            cc_val = json.loads(row["cc"]) if row["cc"] else None
            env = make_envelope(
                cmd_id=row["command_id"], source=row["source"], target=row["target"],
                payload=payload, created_at=row["created_at"],
                conversation_id=row["conversation_id"],
                expect_result=bool(row["expect_result"]),
                reply_to=row["reply_to"], cc=cc_val,
                delivered_as=row["delivered_as"], dispatch_kind=row["dispatch_kind"],
                in_reply_to=row["in_reply_to"], closing=bool(row["closing"]),
                priority=row["priority"], deadline_ts=row["deadline_ts"],
            )
            self._queues[row["target"]].append(env)
            self._conv.set_conv_of(row["command_id"], row["conversation_id"])
        # mark orphan (closed) in-flight messages
        now = _now_iso()
        self._dispatch_persistence.mark_orphan_closed_inflight(now)
        # restore _in_flight
        pending = self._persistence.restore_in_flight_pending()
        for source, m in pending.items():
            self._in_flight.setdefault(source, {}).update(m)

    def drop_inflight_on_restart(self) -> None:
        """클린 스타트 — 이전 실행의 미배달(undrained) 메시지를 전부 drop
        마킹한다. restore_from_persistence와 달리 _queues에 싣지 않는다.
        대화·메시지 행 자체는 audit용으로 남는다."""
        now = _now_iso()
        self._dispatch_persistence.drop_inflight(now)

    # ------------------------------------------------------------------------

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            all_waiters = self._waiters
            self._waiters = defaultdict(list)
        for target, futs in all_waiters.items():
            for f in futs:
                if not f.done():
                    f.set_exception(DispatcherClosed("Dispatcher closed"))
