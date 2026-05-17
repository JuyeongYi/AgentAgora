"""Sweeper — periodic background sweeps, extracted from Dispatcher.

핫패스가 아니다 — __main__.py의 주기 루프가 호출한다. 알고리즘은 Dispatcher의
기존 sweep 본문 그대로다."""
from __future__ import annotations

import datetime

from agent_agora.bot_registry import BotRegistry
from agent_agora.conversation_store import ConversationStore
from agent_agora.persistence import Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.schemas import SchemaRegistry


class Sweeper:
    def __init__(
        self,
        conversation_store: ConversationStore,
        instance_registry: InstanceRegistry,
        bot_registry: BotRegistry,
        schema_registry: SchemaRegistry,
        persistence: Persistence,
        *,
        close_timeout_ms: int,
        dead_session_timeout_ms: int,
        gc_retention_days: int,
    ) -> None:
        self._conv = conversation_store
        self._instance_registry = instance_registry
        self._bot_registry = bot_registry
        self._schema_registry = schema_registry
        self._persistence = persistence
        self._close_timeout_ms = close_timeout_ms
        self._dead_session_timeout_ms = dead_session_timeout_ms
        self._gc_retention_days = gc_retention_days

    def close_ttl_sweep(self, now: datetime.datetime | None = None) -> list[str]:
        """Auto-transition half_closed conversations to closed after timeout.
        Returns list of conv_ids newly closed. SQLite + in-memory both updated."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(milliseconds=self._close_timeout_ms)
        cutoff_iso = cutoff.isoformat()
        closed_ids: list[str] = []
        for conv_id, state in self._conv.items():
            if state["status"] != "half_closed":
                continue
            if state["last_message_at"] < cutoff_iso:
                state["status"] = "closed"
                state["closed_at"] = now.isoformat()
                closed_ids.append(conv_id)
        if closed_ids:
            # SQLite update (synchronous — sweep runs in background task, not hot path)
            self._persistence.conn.execute(
                "UPDATE conversations SET status='closed', closed_at=? "
                "WHERE status='half_closed' AND last_message_at < ?",
                (now.isoformat(), cutoff_iso),
            )
        return closed_ids

    def dead_session_sweep(self, now: datetime.datetime | None = None) -> list[str]:
        """Unregister instances whose last_seen_at exceeded dead_session_timeout.
        In-flight queues are preserved (a re-registered instance will see them)."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(milliseconds=self._dead_session_timeout_ms)
        removed: list[str] = []
        for info in self._instance_registry.list_instances():
            if info.last_seen_at is None:
                continue
            seen = datetime.datetime.fromisoformat(info.last_seen_at)
            if seen < cutoff:
                self._instance_registry.unregister_session(info.session_id)
                removed.append(info.instance_id)
        for iid in removed:
            self._schema_registry.release_holder(iid)
        return removed

    def dead_bot_sweep(self, now: datetime.datetime | None = None) -> list[str]:
        """Unregister bots whose last_seen_at (or registered_at, if the bot has
        never returned from a wait) exceeded dead_session_timeout. Detaches the
        bot's schema subscriptions so routing immediately stops targeting it.
        Returns swept bot instance_ids. Queued messages are left untouched —
        identical to dead_session_sweep for workers."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(milliseconds=self._dead_session_timeout_ms)
        removed: list[str] = []
        for bot in self._bot_registry.list_bots():
            marker = bot.last_seen_at or bot.registered_at
            if datetime.datetime.fromisoformat(marker) < cutoff:
                self._bot_registry.unregister_session(bot.session_id)
                removed.append(bot.instance_id)
        for iid in removed:
            self._schema_registry.release_holder(iid)
        return removed

    def message_gc_sweep(self, now: datetime.datetime | None = None) -> int:
        """Delete messages of closed conversations older than gc_retention_days.
        Conversations meta is preserved; in-memory caches (Inst4 우려4) are evicted.
        Returns deleted message row count."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=self._gc_retention_days)
        cutoff_iso = cutoff.isoformat()
        # candidates for eviction
        rows = self._persistence.conn.execute(
            "SELECT conversation_id FROM conversations "
            "WHERE status='closed' AND closed_at < ?",
            (cutoff_iso,),
        ).fetchall()
        victim_ids = [r[0] for r in rows]
        if not victim_ids:
            return 0
        # delete messages
        qmarks = ",".join("?" * len(victim_ids))
        cur = self._persistence.conn.execute(
            f"DELETE FROM messages WHERE conversation_id IN ({qmarks})",
            tuple(victim_ids),
        )
        deleted = cur.rowcount
        # in-memory cache eviction
        self._conv.evict(victim_ids)
        return deleted
