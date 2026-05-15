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
