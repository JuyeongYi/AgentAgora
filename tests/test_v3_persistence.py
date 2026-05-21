import pytest
import sqlite3
from agent_agora.persistence import Persistence


def test_migrate_creates_three_tables(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    names = {r[0] for r in rows}
    assert {"conversations", "messages", "conversation_participants", "schema_version"} <= names


def test_migrate_idempotent_no_pk_violation(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    versions = conn.execute("SELECT version FROM schema_version").fetchall()
    assert versions == [(1,)]


def test_messages_has_priority_rank_column(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert "priority_rank" in cols
    assert "drop_reason" in cols
    assert "delivered_as" in cols
    assert "dispatch_kind" in cols
    assert "cc" in cols


def test_participants_has_role_column(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(conversation_participants)").fetchall()]
    assert "role" in cols
    assert "delivered" in cols


@pytest.mark.asyncio
async def test_submit_transaction_commits_atomically(tmp_path):
    from agent_agora.persistence import AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)
    async with queue:
        await queue.submit_transaction([
            ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
             ("c1", "open", "2026-05-14T00:00:00+00:00", "2026-05-14T00:00:00+00:00")),
            ("INSERT INTO conversation_participants (conversation_id, instance_id, role, joined_at) VALUES (?,?,?,?)",
             ("c1", "Inst1", "primary", "2026-05-14T00:00:00+00:00")),
        ])
    rows = p.conn.execute("SELECT conversation_id FROM conversations").fetchall()
    assert rows == [("c1",)]


@pytest.mark.asyncio
async def test_submit_transaction_rolls_back_on_constraint_violation(tmp_path):
    from agent_agora.persistence import AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)
    async with queue:
        with pytest.raises(Exception):
            await queue.submit_transaction([
                ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
                 ("c2", "open", "2026-05-14T00:00:00+00:00", "2026-05-14T00:00:00+00:00")),
                ("INSERT INTO conversation_participants (conversation_id, instance_id, role, joined_at) VALUES (?,?,?,?)",
                 ("conv-x-nonexistent", "Inst1", "primary", "2026-05-14T00:00:00+00:00")),
            ])
    rows = p.conn.execute("SELECT conversation_id FROM conversations").fetchall()
    assert rows == []


@pytest.mark.asyncio
async def test_restore_inflight_skips_closed_conversation_messages(tmp_path):
    from agent_agora.persistence import AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)
    async with queue:
        await queue.submit_transaction([
            ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
             ("c-open", "open", "t1", "t1")),
            ("INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
             ("cmd-1", "Inst2", "c-open", "Inst1", "t1", '{"m":1}', 1)),
        ])
        await queue.submit_transaction([
            ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at, closed_at) VALUES (?,?,?,?,?)",
             ("c-closed", "closed", "t1", "t1", "t2")),
            ("INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
             ("cmd-2", "Inst3", "c-closed", "Inst1", "t1", '{"m":2}', 1)),
        ])
    restored = p.restore_inflight()
    assert len(restored) == 1
    assert restored[0]["command_id"] == "cmd-1"


def test_lookup_conversation_for_returns_id_when_command_exists(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    p.conn.execute(
        "INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
        ("c1", "open", "t1", "t1"),
    )
    p.conn.execute(
        "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
        ("cmd-x", "Inst2", "c1", "Inst1", "t1", '{}', 1),
    )
    assert p.lookup_conversation_for("cmd-x") == "c1"
    assert p.lookup_conversation_for("cmd-missing") is None


def test_migrate_creates_schemas_table(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "schemas" in names


def test_schemas_table_has_kind_and_purpose_columns(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    cols = [r[1] for r in p.conn.execute("PRAGMA table_info(schemas)").fetchall()]
    assert {"name", "body", "kind", "purpose", "registered_at", "registered_by"} <= set(cols)


def test_save_and_restore_schemas(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    body = {"type": "object", "properties": {"msgtype": {"type": "string"}}}
    p.save_schema("foo", body, kind="bot-task", purpose="테스트", registered_by="bot_x")
    rows = p.restore_schemas()
    assert len(rows) == 1
    assert rows[0]["name"] == "foo"
    assert rows[0]["kind"] == "bot-task"
    assert rows[0]["body"] == body
    assert rows[0]["purpose"] == "테스트"
    assert rows[0]["registered_by"] == "bot_x"


def test_save_schema_idempotent_on_same_name(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    body = {"properties": {"msgtype": {}}}
    p.save_schema("foo", body, kind="bot-task", purpose="p")
    p.save_schema("foo", body, kind="bot-task", purpose="p")  # no PK violation
    assert len(p.restore_schemas()) == 1


def test_migrate_creates_bot_subscriptions_table(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    names = {r[0] for r in p.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "bot_subscriptions" in names


def test_messages_delivered_as_check_allows_subscribed(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    sql = p.conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='messages'").fetchone()[0]
    assert "subscribed" in sql


def test_save_and_restore_bot_subscriptions(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    p.save_bot_subscriptions("bot_x", subscribe=["s1", "s2"], emit=["s1"])
    subs = p.restore_bot_subscriptions()
    assert sorted(subs["bot_x"]["subscribe"]) == ["s1", "s2"]
    assert subs["bot_x"]["emit"] == ["s1"]


def test_save_bot_subscriptions_replaces_prior_rows(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    p.save_bot_subscriptions("bot_x", subscribe=["old"], emit=[])
    p.save_bot_subscriptions("bot_x", subscribe=["new"], emit=[])
    subs = p.restore_bot_subscriptions()
    assert subs["bot_x"]["subscribe"] == ["new"]


def test_messages_has_reply_only_column(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    cols = [r[1] for r in p.conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert "reply_only" in cols


def test_migrate_idempotent_reply_only_column_add(tmp_path):
    """Older DBs that pre-date reply_only should get the column added without error."""
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    # second migrate must not raise even though ALTER TABLE would error a second time
    p.migrate()
    cols = [r[1] for r in p.conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert "reply_only" in cols


@pytest.mark.asyncio
async def test_reply_only_survives_persistence_roundtrip(tmp_path):
    """Envelope.reply_only=True should round-trip through SQLite via dispatch INSERT + restore_inflight."""
    from agent_agora.persistence import AsyncWriteQueue
    from agent_agora.dispatch_persistence import DispatchPersistence
    from agent_agora.envelope import make_envelope, validate_payload_size, validate_priority

    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)

    env_true = make_envelope(
        cmd_id="cmd-true", source="operator:alice", target="worker1",
        payload={"q": 1}, created_at="2026-05-21T00:00:00Z",
        conversation_id="conv-1",
        reply_only=True,
    )
    env_false = make_envelope(
        cmd_id="cmd-false", source="operator:alice", target="worker2",
        payload={"q": 2}, created_at="2026-05-21T00:00:01Z",
        conversation_id="conv-1",
        # reply_only defaults to False
    )

    async with queue:
        dp = DispatchPersistence(p, queue)
        state = {
            "status": "open",
            "started_at": "2026-05-21T00:00:00Z",
            "last_message_at": "2026-05-21T00:00:00Z",
            "kind": "direct",
            "participants": {
                "operator:alice": {"role": "primary", "delivered": True},
                "worker1": {"role": "primary", "delivered": True},
            },
            "closed_at": None,
            "closed_by": [],
        }
        payload_bytes_true = validate_payload_size(env_true.payload)
        rank = validate_priority(env_true.priority)
        await dp.persist_dispatch_txn(
            state=state, conv_id="conv-1", is_new_conv=True,
            env=env_true, cc_envs=[], skipped_full=[],
            payload_bytes=payload_bytes_true, priority_rank=rank,
        )

        state["participants"]["worker2"] = {"role": "primary", "delivered": True}
        state["last_message_at"] = "2026-05-21T00:00:01Z"
        payload_bytes_false = validate_payload_size(env_false.payload)
        await dp.persist_dispatch_txn(
            state=state, conv_id="conv-1", is_new_conv=False,
            env=env_false, cc_envs=[], skipped_full=[],
            payload_bytes=payload_bytes_false, priority_rank=rank,
        )

    restored = p.restore_inflight()
    by_cmd = {r["command_id"]: r for r in restored}
    assert by_cmd["cmd-true"]["reply_only"] is True
    assert by_cmd["cmd-false"]["reply_only"] is False


def test_lookup_source_for_returns_message_source(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    p.conn.execute(
        "INSERT INTO conversations (conversation_id, status, started_at, last_message_at) "
        "VALUES ('c1', 'open', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")
    p.conn.execute(
        "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload) "
        "VALUES ('cmd1', 'Inst2', 'c1', 'Inst1', '2026-01-01T00:00:00Z', '{}')")
    assert p.lookup_source_for("cmd1") == "Inst1"
    assert p.lookup_source_for("nonexistent") is None


@pytest.mark.asyncio
async def test_write_queue_depth_initially_zero(tmp_path):
    """write_queue_depth() returns 0 when no writes are pending."""
    from agent_agora.persistence import AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    # Do NOT enter context manager — worker task is not started, queue is empty.
    queue = AsyncWriteQueue(p)
    assert queue.write_queue_depth() == 0


@pytest.mark.asyncio
async def test_write_queue_depth_reports_queued_items(tmp_path):
    """write_queue_depth() reflects pending writes when worker is not draining."""
    from agent_agora.persistence import AsyncWriteQueue, _TxnRequest
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    # Do NOT start the worker (no async with) so items accumulate without draining.
    queue = AsyncWriteQueue(p)
    dummy = _TxnRequest(stmts=[], future=None)
    queue._queue.put_nowait(dummy)
    queue._queue.put_nowait(dummy)
    assert queue.write_queue_depth() == 2
