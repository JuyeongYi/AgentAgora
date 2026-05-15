"""v3 SQLite persistence: conversations, messages, participants. WAL mode."""
from __future__ import annotations

import asyncio
import datetime
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('open','half_closed','closed')),
  started_at TEXT NOT NULL,
  last_message_at TEXT NOT NULL,
  closed_at TEXT,
  closed_by TEXT NOT NULL DEFAULT '[]',
  message_count INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'direct' CHECK (kind IN ('direct','broadcast'))
);
CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conv_last_msg ON conversations(last_message_at);

CREATE TABLE IF NOT EXISTS messages (
  command_id TEXT NOT NULL,
  target TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  source TEXT NOT NULL,
  in_reply_to TEXT,
  created_at TEXT NOT NULL,
  expect_result INTEGER NOT NULL DEFAULT 0,
  reply_to TEXT,
  cc TEXT,
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc')),
  dispatch_kind TEXT NOT NULL DEFAULT 'direct' CHECK (dispatch_kind IN ('direct','broadcast')),
  closing INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
  priority_rank INTEGER NOT NULL DEFAULT 1 CHECK (priority_rank IN (0,1,2)),
  deadline_ts TEXT,
  payload TEXT NOT NULL,
  drained_at TEXT,
  drop_reason TEXT CHECK (drop_reason IS NULL OR drop_reason IN ('server_restart','manual')),
  PRIMARY KEY (command_id, target),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_msg_source ON messages(source);
CREATE INDEX IF NOT EXISTS idx_msg_inflight ON messages(target, drained_at) WHERE drained_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_msg_priority_sort ON messages(target, priority_rank, created_at, command_id);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at);

CREATE TABLE IF NOT EXISTS conversation_participants (
  conversation_id TEXT NOT NULL,
  instance_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'primary' CHECK (role IN ('primary','cc')),
  joined_at TEXT NOT NULL,
  delivered INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (conversation_id, instance_id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_cp_inst ON conversation_participants(instance_id);

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schemas (
  name TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('conversation','bot-task')),
  purpose TEXT NOT NULL DEFAULT '',
  registered_at TEXT NOT NULL,
  registered_by TEXT
);
"""


class Persistence:
    """Synchronous SQLite handle. Hot path never calls writes directly — use AsyncWriteQueue."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def migrate(self, target_version: int = 1) -> None:
        cur = self._conn.cursor()
        cur.executescript(_SCHEMA_V1)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute("INSERT OR IGNORE INTO schema_version VALUES (?, ?)", (target_version, now))

    def close(self) -> None:
        self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def restore_inflight(self) -> list[dict[str, Any]]:
        """Inst4 함정5 — JOIN으로 closed 메시지 자동 제외."""
        rows = self._conn.execute(
            """
            SELECT m.command_id, m.target, m.conversation_id, m.source, m.created_at,
                   m.expect_result, m.reply_to, m.cc, m.delivered_as, m.dispatch_kind,
                   m.in_reply_to, m.closing, m.priority, m.priority_rank, m.deadline_ts,
                   m.payload
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.conversation_id
            WHERE m.drained_at IS NULL AND c.status != 'closed'
            ORDER BY m.created_at ASC, m.command_id ASC
            """
        ).fetchall()
        cols = ("command_id","target","conversation_id","source","created_at",
                "expect_result","reply_to","cc","delivered_as","dispatch_kind",
                "in_reply_to","closing","priority","priority_rank","deadline_ts","payload")
        return [dict(zip(cols, r)) for r in rows]

    def restore_in_flight_pending(self) -> dict[str, dict[str, set[str]]]:
        """Inst4 우려3 — _in_flight 재시작 복구."""
        rows = self._conn.execute(
            """
            SELECT m.target, m.command_id, m.source
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.conversation_id
            WHERE m.drained_at IS NULL AND m.expect_result = 1
              AND m.delivered_as = 'primary' AND c.status != 'closed'
            """
        ).fetchall()
        result: dict[str, dict[str, set[str]]] = {}
        for target, cmd_id, source in rows:
            result.setdefault(source, {}).setdefault(cmd_id, set()).add(target)
        return result

    def lookup_conversation_for(self, cmd_id: str) -> str | None:
        """Inst4 함정2 — cache miss 폴백."""
        row = self._conn.execute(
            "SELECT conversation_id FROM messages WHERE command_id=? LIMIT 1",
            (cmd_id,),
        ).fetchone()
        return row[0] if row else None


@dataclass
class _TxnRequest:
    stmts: list[tuple[str, tuple]]
    future: asyncio.Future | None


class AsyncWriteQueue:
    """Asynchronous SQLite writer — all hot-path writes funnel as single-tx batches.
    Best-effort: on failure in-memory state is NOT rolled back (Inst5 V4)."""

    def __init__(self, persistence: Persistence) -> None:
        self._p = persistence
        self._queue: asyncio.Queue[_TxnRequest | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    async def __aenter__(self) -> "AsyncWriteQueue":
        self._worker = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._queue.put(None)
        if self._worker is not None:
            await self._worker

    async def _run(self) -> None:
        while True:
            req = await self._queue.get()
            if req is None:
                break
            try:
                cur = self._p.conn.cursor()
                cur.execute("BEGIN")
                for sql, params in req.stmts:
                    cur.execute(sql, params)
                cur.execute("COMMIT")
                if req.future is not None:
                    req.future.set_result(None)
            except Exception as e:
                try:
                    self._p.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if req.future is not None:
                    req.future.set_exception(e)

    async def submit_transaction(self, stmts: list[tuple[str, tuple]], wait: bool = True) -> None:
        loop = asyncio.get_running_loop()
        future = loop.create_future() if wait else None
        await self._queue.put(_TxnRequest(stmts=stmts, future=future))
        if future is not None:
            await future
