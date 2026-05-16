"""agora.wait_notify — 비파괴 long-poll 테스트."""
from __future__ import annotations

import asyncio

import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=500)
        yield registry, dispatcher


@pytest.mark.asyncio
async def test_returns_immediately_when_queue_nonempty(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=200)
    assert snap["instance_id"] == "Inst2"
    assert snap["pending"] == 1
    assert snap["sources"] == ["Inst1"]


@pytest.mark.asyncio
async def test_blocks_until_message_then_returns(setup):
    registry, dispatcher = setup
    task = asyncio.create_task(dispatcher.wait_notify("Inst2", timeout_ms=2000))
    await asyncio.sleep(0.05)            # let it block on the empty queue
    assert not task.done()
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await task
    assert snap["pending"] == 1
    assert snap["sources"] == ["Inst1"]


@pytest.mark.asyncio
async def test_timeout_returns_empty_snapshot(setup):
    registry, dispatcher = setup
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=50)
    assert snap == {"instance_id": "Inst2", "pending": 0, "sources": []}


@pytest.mark.asyncio
async def test_is_non_destructive(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=200)
    assert snap["pending"] == 1
    # 큐가 그대로 — 이어서 wait가 같은 메시지를 드레인한다
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    assert len(drained) == 1
    assert drained[0]["payload"]["x"] == 1


@pytest.mark.asyncio
async def test_touches_last_seen(setup):
    registry, dispatcher = setup
    assert registry.resolve_instance_id("Inst2").last_seen_at is None
    await dispatcher.wait_notify("Inst2", timeout_ms=50)
    assert registry.resolve_instance_id("Inst2").last_seen_at is not None


@pytest.mark.asyncio
async def test_distinct_sources_sorted(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst3", target="Inst2", payload=tany(x=1))
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=2))
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=3))
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=200)
    assert snap["pending"] == 3
    assert snap["sources"] == ["Inst1", "Inst3"]   # distinct, sorted


@pytest.mark.asyncio
async def test_coexists_with_wait(setup):
    registry, dispatcher = setup
    wn = asyncio.create_task(dispatcher.wait_notify("Inst2", timeout_ms=2000))
    w = asyncio.create_task(dispatcher.wait("Inst2", timeout_ms=2000))
    await asyncio.sleep(0.05)
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await wn
    drained = await w
    # 둘 다 깨어났다(데드락 없음). wait가 메시지를 드레인한다.
    assert snap["instance_id"] == "Inst2"
    assert len(drained) == 1
