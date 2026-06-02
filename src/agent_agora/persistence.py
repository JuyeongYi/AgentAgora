"""v3 SQLite persistence: conversations, messages, participants. WAL mode."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc','subscribed')),
  dispatch_kind TEXT NOT NULL DEFAULT 'direct' CHECK (dispatch_kind IN ('direct','broadcast')),
  closing INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
  priority_rank INTEGER NOT NULL DEFAULT 1 CHECK (priority_rank IN (0,1,2)),
  deadline_ts TEXT,
  payload TEXT NOT NULL,
  drained_at TEXT,
  drop_reason TEXT CHECK (drop_reason IS NULL OR drop_reason IN ('server_restart','manual')),
  reply_only INTEGER NOT NULL DEFAULT 0,
  acked_at REAL,
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
CREATE TABLE IF NOT EXISTS bot_subscriptions (
  instance_id TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('subscribe','emit')),
  PRIMARY KEY (instance_id, schema_name, kind)
);
CREATE INDEX IF NOT EXISTS idx_bot_sub_schema ON bot_subscriptions(schema_name);

CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  content_type TEXT,
  registered_by TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at);
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
        # Idempotent column adds for older DBs that pre-date these fields.
        # Use PRAGMA pre-check rather than catching OperationalError — narrow
        # the failure surface so disk/lock/syntax errors still surface.
        existing_cols = {row[1] for row in cur.execute("PRAGMA table_info(messages)").fetchall()}
        if "reply_only" not in existing_cols:
            cur.execute("ALTER TABLE messages ADD COLUMN reply_only INTEGER NOT NULL DEFAULT 0")
        if "acked_at" not in existing_cols:
            cur.execute("ALTER TABLE messages ADD COLUMN acked_at REAL")
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
                   m.payload, m.reply_only
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.conversation_id
            WHERE m.drained_at IS NULL AND c.status != 'closed'
            ORDER BY m.created_at ASC, m.command_id ASC
            """
        ).fetchall()
        cols = ("command_id","target","conversation_id","source","created_at",
                "expect_result","reply_to","cc","delivered_as","dispatch_kind",
                "in_reply_to","closing","priority","priority_rank","deadline_ts","payload",
                "reply_only")
        out = [dict(zip(cols, r)) for r in rows]
        for row in out:
            row["reply_only"] = bool(row["reply_only"])
        return out

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

    def save_schema(
        self, name: str, body: dict, kind: str, purpose: str,
        registered_by: str | None = None,
    ) -> None:
        """schema를 동기 영속화한다. 동일 이름 재저장은 무시 (registry가 불변성 강제)."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO schemas (name, body, kind, purpose, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, json.dumps(body, ensure_ascii=False), kind, purpose, now, registered_by),
        )

    def restore_schemas(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT name, body, kind, purpose, registered_at, registered_by FROM schemas"
        ).fetchall()
        return [
            {"name": r[0], "body": json.loads(r[1]), "kind": r[2],
             "purpose": r[3], "registered_at": r[4], "registered_by": r[5]}
            for r in rows
        ]

    def save_bot_subscriptions(
        self, instance_id: str, subscribe: list[str], emit: list[str],
    ) -> None:
        """봇 구독을 audit용으로 영속화한다. 같은 instance_id의 기존 행은 교체한다.
        (BotRegistry는 재시작 시 이 테이블에서 복원하지 않는다 — 봇이 재접속하며 재등록한다.)"""
        self._conn.execute("DELETE FROM bot_subscriptions WHERE instance_id=?", (instance_id,))
        for s in subscribe:
            self._conn.execute(
                "INSERT OR IGNORE INTO bot_subscriptions (instance_id, schema_name, kind) "
                "VALUES (?, ?, 'subscribe')", (instance_id, s))
        for s in emit:
            self._conn.execute(
                "INSERT OR IGNORE INTO bot_subscriptions (instance_id, schema_name, kind) "
                "VALUES (?, ?, 'emit')", (instance_id, s))

    def restore_bot_subscriptions(self) -> dict[str, dict[str, list[str]]]:
        rows = self._conn.execute(
            "SELECT instance_id, schema_name, kind FROM bot_subscriptions").fetchall()
        out: dict[str, dict[str, list[str]]] = {}
        for instance_id, schema_name, kind in rows:
            entry = out.setdefault(instance_id, {"subscribe": [], "emit": []})
            entry["subscribe" if kind == "subscribe" else "emit"].append(schema_name)
        return out

    def lookup_source_for(self, cmd_id: str) -> str | None:
        """cmd_id의 원 source를 SQLite에서 조회 (bot_emit in_reply_to cache miss 폴백)."""
        row = self._conn.execute(
            "SELECT source FROM messages WHERE command_id=? LIMIT 1", (cmd_id,)
        ).fetchone()
        return row[0] if row else None

    _FILE_COLS = ("file_id", "name", "size", "sha256", "content_type",
                  "registered_by", "created_at")

    def save_file(self, file_id, name, size, sha256, content_type,
                  registered_by, created_at) -> None:
        self._conn.execute(
            "INSERT INTO files (file_id,name,size,sha256,content_type,"
            "registered_by,created_at) VALUES (?,?,?,?,?,?,?)",
            (file_id, name, size, sha256, content_type, registered_by, created_at))

    def get_file(self, file_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT file_id,name,size,sha256,content_type,registered_by,created_at "
            "FROM files WHERE file_id=?", (file_id,)).fetchone()
        return dict(zip(self._FILE_COLS, row)) if row is not None else None

    def files_before(self, cutoff_iso: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT file_id FROM files WHERE created_at < ?", (cutoff_iso,)).fetchall()
        return [r[0] for r in rows]

    def delete_file(self, file_id: str) -> None:
        self._conn.execute("DELETE FROM files WHERE file_id=?", (file_id,))

    def fetch_messages_for(
        self,
        *,
        recipient: str | None = None,
        conversation_id: str | None = None,
        include_acked: bool = False,
    ) -> list[dict]:
        """Fetch messages from the messages table filtered by recipient or conversation_id.

        By default, only messages with acked_at IS NULL are returned (unless include_acked=True).
        Returns list of dicts with keys: message_id, sender, source, target, payload,
        conversation_id, created_at, delivered_as, in_reply_to, reply_only, acked_at.
        (`sender` and `source` are aliases — `sender` is the canonical UI-facing name,
        `source` matches the DB column name for code that introspects by SQL identifier.)
        """
        conditions: list[str] = []
        params: list = []

        if recipient is not None:
            conditions.append("target = ?")
            params.append(recipient)
        if conversation_id is not None:
            conditions.append("conversation_id = ?")
            params.append(conversation_id)
        if not include_acked:
            conditions.append("acked_at IS NULL")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            f"SELECT command_id, source, target, payload, conversation_id, "
            f"created_at, delivered_as, in_reply_to, acked_at, reply_only "
            f"FROM messages {where} "
            f"ORDER BY created_at ASC, command_id ASC"
        )
        rows = self._conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            payload_raw = row[3]
            try:
                payload_val = json.loads(payload_raw)
            except (TypeError, ValueError):
                logger.warning("message %s has non-JSON payload; returning raw text", row[0])
                payload_val = payload_raw
            out.append({
                "message_id": row[0],
                "sender": row[1],
                "source": row[1],
                "target": row[2],
                "payload": payload_val,
                "conversation_id": row[4],
                "created_at": row[5],
                "delivered_as": row[6],
                "in_reply_to": row[7],
                "acked_at": row[8],
                "reply_only": bool(row[9]),
            })
        return out

    def fetch_transcript(self, conversation_id: str, since_ts: str | None = None) -> list[dict]:
        """conversation의 논리 메시지를 시간순으로. cmd_id별 1행(primary 우선)으로 dedup."""
        params: list = [conversation_id]
        sql = ("SELECT command_id, source, target, payload, conversation_id, created_at, "
               "delivered_as, in_reply_to FROM messages WHERE conversation_id = ?")
        if since_ts is not None:
            sql += " AND created_at > ?"
            params.append(since_ts)
        sql += " ORDER BY created_at ASC, command_id ASC"
        rows = self._conn.execute(sql, params).fetchall()
        seen: dict[str, dict] = {}
        for r in rows:
            cmd = r[0]
            if cmd in seen and r[6] != "primary":
                continue  # primary 행을 우선 보존
            try:
                payload_val = json.loads(r[3])
            except (TypeError, ValueError):
                logger.warning("message %s has non-JSON payload; returning raw text", cmd)
                payload_val = r[3]
            seen[cmd] = {
                "command_id": cmd, "source": r[1], "target": r[2], "payload": payload_val,
                "conversation_id": r[4], "created_at": r[5],
                "delivered_as": r[6], "in_reply_to": r[7],
            }
        return sorted(seen.values(), key=lambda m: (m["created_at"], m["command_id"]))

    async def mark_messages_acked(
        self, message_ids: list[str], *, write_queue: "AsyncWriteQueue",
    ) -> int:
        """Set acked_at = current unix timestamp for the given message_ids.

        Routes the UPDATE through the AsyncWriteQueue to preserve the codebase
        invariant "hot path never calls writes directly" (Persistence docstring).
        Returns the number of message_ids submitted (not the SQLite rowcount —
        the queue worker does not surface rowcount through submit_transaction).
        """
        if not message_ids:
            return 0
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        placeholders = ",".join("?" * len(message_ids))
        sql = f"UPDATE messages SET acked_at = ? WHERE command_id IN ({placeholders})"
        await write_queue.submit_transaction([(sql, (now_ts, *message_ids))])
        return len(message_ids)


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
                logger.warning("async write transaction failed, rolling back: %s", e)
                try:
                    self._p.conn.execute("ROLLBACK")
                except Exception:
                    logger.exception("ROLLBACK failed after write error; connection may be corrupt")
                if req.future is not None:
                    req.future.set_exception(e)

    async def submit_transaction(self, stmts: list[tuple[str, tuple]], wait: bool = True) -> None:
        loop = asyncio.get_running_loop()
        future = loop.create_future() if wait else None
        await self._queue.put(_TxnRequest(stmts=stmts, future=future))
        if future is not None:
            await future

    def write_queue_depth(self) -> int:
        """Current async write queue depth — operator dashboard health metric."""
        return self._queue.qsize()
