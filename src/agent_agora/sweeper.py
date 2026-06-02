"""Sweeper — periodic background sweeps, extracted from Dispatcher.

핫패스가 아니다 — __main__.py의 주기 루프가 호출한다. 알고리즘은 Dispatcher의
기존 sweep 본문 그대로다."""
from __future__ import annotations

import datetime
import time

from agent_agora.bot_registry import BotRegistry
from agent_agora.conversation_store import ConversationStore
from agent_agora.persistence import Persistence
from agent_agora.registry import InstanceRegistry, is_operator
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
        file_store=None,
        file_retention_days: int = 7,
        dispatcher=None,
    ) -> None:
        self._conv = conversation_store
        self._instance_registry = instance_registry
        self._bot_registry = bot_registry
        self._schema_registry = schema_registry
        self._persistence = persistence
        self._close_timeout_ms = close_timeout_ms
        self._dead_session_timeout_ms = dead_session_timeout_ms
        self._gc_retention_days = gc_retention_days
        self._file_store = file_store
        self._file_retention_days = file_retention_days
        # dispatcher는 dead_session_sweep 후 unregister hook 호출 용도.
        # Optional — 테스트나 hook 비사용 시 None 안전.
        self._dispatcher = dispatcher

        # 실행 통계 — dashboard_health.py (Task 7)에서 읽는다.
        # dead_session_sweep 호출만 카운트한다 (다른 sweep 메서드는 별도 통계 없음).
        self.dead_session_sweep_runs_total: int = 0
        self.dead_session_sweep_last_run_at: float | None = None

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
        In-flight queues are preserved (a re-registered instance will see them).
        operator: 접두사 인스턴스는 TTL에 관계없이 면제된다."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(milliseconds=self._dead_session_timeout_ms)
        removed: list[str] = []
        for info in self._instance_registry.list_instances():
            if is_operator(info.instance_id):
                continue  # 운영자 pseudo-instance는 GC 면제
            if info.last_seen_at is None:
                continue
            seen = datetime.datetime.fromisoformat(info.last_seen_at)
            if seen < cutoff:
                self._instance_registry.unregister_session(info.session_id)
                removed.append(info.instance_id)
        for iid in removed:
            self._schema_registry.release_holder(iid)
            if self._dispatcher is not None:
                self._dispatcher.notify_unregistered(iid)
        self.dead_session_sweep_runs_total += 1
        self.dead_session_sweep_last_run_at = time.time()
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

    def file_gc_sweep(self, now: datetime.datetime | None = None) -> int:
        """보관 기간을 지난 공유 파일을 스토어·메타에서 삭제. 삭제 수 반환."""
        if self._file_store is None:
            return 0
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=self._file_retention_days)
        return self._file_store.gc(cutoff.isoformat())

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

    async def deadline_sweep(self, now: datetime.datetime | None = None) -> list[dict]:
        """expect_result deadline 초과 명령을 만료시킨다. Dispatcher로 위임
        (in_flight/_deadlines 조작은 dispatcher._lock 안에서 일어나야 한다).
        dispatcher 미주입(테스트) 시 빈 리스트."""
        if self._dispatcher is None:
            return []
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        return await self._dispatcher.expire_overdue_deadlines(now_iso=now.isoformat())

    def vacuum(self) -> None:
        """SQLite VACUUM — 일일 GC 루프에서 message_gc_sweep 후 호출해 삭제된
        행이 점유하던 디스크를 회수한다(gc_retention_days 후 수동 VACUUM 필요 제거)."""
        self._persistence.conn.execute("VACUUM")
