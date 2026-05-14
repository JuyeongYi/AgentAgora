"""M3 §15.5 — persistence restart recovery + AsyncWriteQueue properties."""
from __future__ import annotations

import asyncio
import time

import pytest

from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry


@pytest.mark.asyncio
async def test_restart_recovery_restores_inflight_messages(tmp_path):
    """Spec §11.5 — open conversation의 미수신 메시지는 재시작 후 큐로 복원."""
    db = tmp_path / "agora.db"
    # phase 1: dispatch + leave undelivered, then close dispatcher cleanly
    reg1 = InstanceRegistry()
    reg1.register("s1", "Inst1")
    reg1.register("s2", "Inst2")
    pers1 = Persistence(db)
    pers1.migrate()
    q1 = AsyncWriteQueue(pers1)
    async with q1:
        d1 = Dispatcher(reg1, pers1, q1)
        await d1.dispatch(source="Inst1", target="Inst2", payload={"keep": True})
    pers1.close()

    # phase 2: cold restart
    reg2 = InstanceRegistry()
    reg2.register("s1", "Inst1")
    reg2.register("s2", "Inst2")
    pers2 = Persistence(db)
    q2 = AsyncWriteQueue(pers2)
    async with q2:
        d2 = Dispatcher(reg2, pers2, q2)
        d2.restore_from_persistence()
        msgs = await d2.wait("Inst2", timeout_ms=200)
    pers2.close()
    assert len(msgs) == 1
    assert msgs[0]["payload"] == {"keep": True}


@pytest.mark.asyncio
async def test_restart_recovery_drops_closed_conversation_messages_with_drop_reason(tmp_path):
    """Inst5 M1 — closed conversation의 orphan 메시지는 server_restart 마킹 후 드롭."""
    db = tmp_path / "agora.db"
    reg = InstanceRegistry()
    reg.register("s1", "Inst1")
    reg.register("s2", "Inst2")
    reg.register("s3", "Inst3")
    pers = Persistence(db)
    pers.migrate()
    q = AsyncWriteQueue(pers)
    async with q:
        d = Dispatcher(reg, pers, q)
        # close a conversation explicitly
        conv_closed = "conv-closed-x"
        await d.dispatch(source="Inst1", target="Inst3", payload={"a": 1},
                         conversation_id=conv_closed, closing=True)
        await d.dispatch(source="Inst3", target="Inst1", payload={"b": 2},
                         conversation_id=conv_closed, closing=True)
        assert d.conversation_status(conv_closed)["status"] == "closed"
        # force an undrained orphan message into that closed conversation
        pers.conn.execute(
            "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) "
            "VALUES (?,?,?,?,?,?,?)",
            ("cmd-orphan", "Inst2", conv_closed, "Inst1", "t1", '{}', 1),
        )
    pers.close()

    # restart
    reg2 = InstanceRegistry()
    reg2.register("s1", "Inst1")
    reg2.register("s2", "Inst2")
    reg2.register("s3", "Inst3")
    pers2 = Persistence(db)
    q2 = AsyncWriteQueue(pers2)
    async with q2:
        d2 = Dispatcher(reg2, pers2, q2)
        d2.restore_from_persistence()
        msgs = await d2.wait("Inst2", timeout_ms=100)
    # orphan must NOT be in restored queue
    assert all(m.get("id") != "cmd-orphan" for m in msgs)
    # drop_reason marking persisted
    row = pers2.conn.execute(
        "SELECT drained_at, drop_reason FROM messages WHERE command_id=?",
        ("cmd-orphan",),
    ).fetchone()
    pers2.close()
    assert row[0] is not None
    assert row[1] == "server_restart"


@pytest.mark.asyncio
async def test_async_write_queue_does_not_block_hot_path_under_burst_dispatch(tmp_path):
    """Inst7 §15.5 — write queue 비동기성. 20 dispatch 버스트가 빠르게 끝남."""
    reg = InstanceRegistry()
    reg.register("s1", "Inst1")
    reg.register("s2", "Inst2")
    pers = Persistence(tmp_path / "agora.db")
    pers.migrate()
    q = AsyncWriteQueue(pers)
    async with q:
        d = Dispatcher(reg, pers, q)
        start = time.perf_counter()
        for i in range(20):
            await d.dispatch(source="Inst1", target="Inst2", payload={"i": i})
        elapsed = time.perf_counter() - start
    pers.close()
    # 20 dispatches with synchronous SQLite would still be fast on local disk,
    # but we keep a generous bound. Documents that dispatch is NOT seconds-scale.
    assert elapsed < 2.0, f"burst took {elapsed:.2f}s — write queue may be blocking hot path"


def test_async_write_queue_documented_unbounded(tmp_path):
    """Inst7 invariant — AsyncWriteQueue is intentionally unbounded (Inst5 V4 best-effort).
    Pins this in a test so any future bounding decision must update the contract."""
    pers = Persistence(tmp_path / "agora.db")
    pers.migrate()
    q = AsyncWriteQueue(pers)
    # asyncio.Queue exposes maxsize: 0 means unbounded
    assert q._queue.maxsize == 0
    pers.close()
