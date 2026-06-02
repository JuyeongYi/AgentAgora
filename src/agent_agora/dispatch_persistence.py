"""DispatchPersistence — dispatch persistence transactions + restart SQL,
extracted from Dispatcher. SQL/영속 I/O만 담당하고 in-memory 상태는 만지지 않는다."""
from __future__ import annotations

import json

from agent_agora.envelope import Envelope
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence


class DispatchPersistence:
    def __init__(self, persistence: Persistence, write_queue: AsyncWriteQueue) -> None:
        self._persistence = persistence
        self._write_queue = write_queue

    async def persist_dispatch_txn(
        self,
        state: dict,
        conv_id: str,
        is_new_conv: bool,
        env: Envelope | None,
        cc_envs: list[Envelope],
        skipped_full: list[str],
        payload_bytes: bytes,
        priority_rank: int,
        is_broadcast: bool = False,
    ) -> None:
        stmts: list[tuple[str, tuple]] = []
        if is_new_conv:
            stmts.append((
                "INSERT OR IGNORE INTO conversations "
                "(conversation_id, status, started_at, last_message_at, kind) "
                "VALUES (?, ?, ?, ?, ?)",
                (conv_id, state["status"], state["started_at"], state["last_message_at"], state["kind"]),
            ))
        # participants — INSERT OR IGNORE all currently known
        for iid, info in state["participants"].items():
            stmts.append((
                "INSERT OR IGNORE INTO conversation_participants "
                "(conversation_id, instance_id, role, joined_at, delivered) "
                "VALUES (?, ?, ?, ?, ?)",
                (conv_id, iid, info["role"], state["last_message_at"], 1 if info["delivered"] else 0),
            ))
        # messages
        all_envs: list[Envelope] = []
        if env is not None:
            all_envs.append(env)
        all_envs.extend(cc_envs)
        payload_json = payload_bytes.decode("utf-8")
        for e in all_envs:
            stmts.append((
                "INSERT INTO messages "
                "(command_id, target, conversation_id, source, in_reply_to, created_at, "
                "expect_result, reply_to, cc, delivered_as, dispatch_kind, closing, "
                "priority, priority_rank, deadline_ts, payload, reply_only) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    e.id, e.target, e.conversation_id, e.source, e.in_reply_to, e.created_at,
                    1 if e.expect_result else 0, e.reply_to,
                    json.dumps(e.cc) if e.cc else None,
                    e.delivered_as, e.dispatch_kind, 1 if e.closing else 0,
                    e.priority, priority_rank, e.deadline_ts, payload_json,
                    1 if e.reply_only else 0,
                ),
            ))
        # update conversation last_message_at + count + status
        stmts.append((
            "UPDATE conversations SET last_message_at=?, message_count=message_count+1, "
            "status=?, closed_at=?, closed_by=?, kind=? WHERE conversation_id=?",
            (
                state["last_message_at"], state["status"],
                state.get("closed_at"),
                json.dumps(state["closed_by"]),
                state["kind"], conv_id,
            ),
        ))
        await self._write_queue.submit_transaction(stmts)

    def mark_orphan_closed_inflight(self, now: str) -> None:
        """닫힌 conversation의 undrained 메시지를 drop_reason='server_restart'로 마킹한다."""
        self._persistence.conn.execute(
            """
            UPDATE messages
            SET drained_at = ?, drop_reason = 'server_restart'
            WHERE drained_at IS NULL
              AND conversation_id IN (
                SELECT conversation_id FROM conversations WHERE status = 'closed'
              )
            """,
            (now,),
        )

    def drop_inflight(self, now: str) -> None:
        """모든 undrained 메시지를 drop_reason='server_restart'로 마킹한다 (클린 스타트)."""
        self._persistence.conn.execute(
            """
            UPDATE messages
            SET drained_at = ?, drop_reason = 'server_restart'
            WHERE drained_at IS NULL
            """,
            (now,),
        )
