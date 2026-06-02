from __future__ import annotations

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry, NotRegisteredError
from _helpers import make_schema_registry, tany


@pytest.fixture
async def runtime(tmp_path):
    inst_reg = InstanceRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        disp = Dispatcher(inst_reg, persistence, queue,
                          schema_registry=make_schema_registry(),
                          bot_registry=BotRegistry(),
                          comm_matrix=CommMatrix(),
                          default_timeout_ms=2000)
        yield inst_reg, disp


@pytest.mark.asyncio
async def test_a_dispatches_b_receives(runtime):
    inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    inst_reg.register(session_id="sB", instance_id="B", role="worker")

    await disp.dispatch(source="A", target="B", payload=tany(task="run-tests"))
    commands = await disp.flush(instance_id="B")
    assert len(commands) == 1
    assert commands[0]["payload"] == tany(task="run-tests")
    assert commands[0]["source"] == "A"
    assert commands[0]["target"] == "B"


@pytest.mark.asyncio
async def test_broadcast_fans_out(runtime):
    inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    inst_reg.register(session_id="sB", instance_id="B", role="worker")
    inst_reg.register(session_id="sC", instance_id="C", role="worker")

    await disp.broadcast(source="A", payload=tany(ping=1))
    b = await disp.flush(instance_id="B")
    c = await disp.flush(instance_id="C")
    assert len(b) == 1 and b[0]["payload"] == tany(ping=1)
    assert len(c) == 1 and c[0]["payload"] == tany(ping=1)

    a = await disp.flush(instance_id="A")
    assert a == []


@pytest.mark.asyncio
async def test_result_writeback_via_second_dispatch(runtime):
    inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    inst_reg.register(session_id="sB", instance_id="B", role="worker")

    result = await disp.dispatch(
        source="A", target="B", payload=tany(task="echo", value=42), expect_result=True,
    )
    cmd_id = result["command_id"]
    cmds = await disp.flush(instance_id="B")
    assert len(cmds) == 1
    assert cmds[0]["expect_result"] is True
    assert cmds[0]["id"] == cmd_id

    await disp.dispatch(source="B", target="A", payload=tany(result_for=cmd_id, value=42))
    a_cmds = await disp.flush(instance_id="A")
    assert len(a_cmds) == 1
    assert a_cmds[0]["payload"]["result_for"] == cmd_id


@pytest.mark.asyncio
async def test_unknown_target_dispatch_raises(runtime):
    inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    with pytest.raises(NotRegisteredError):
        await disp.dispatch(source="A", target="ghost", payload=tany())


@pytest.mark.asyncio
async def test_unregister_session_removes_instance(runtime):
    inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    inst_reg.register(session_id="sB", instance_id="B", role="worker")
    inst_reg.unregister_session("sB")
    with pytest.raises(NotRegisteredError):
        inst_reg.resolve_instance_id("B")
    with pytest.raises(NotRegisteredError):
        await disp.dispatch(source="A", target="B", payload=tany())


@pytest.mark.asyncio
async def test_dispatch_queues_when_no_waiter_then_drains_on_first_wait(runtime):
    inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    inst_reg.register(session_id="sB", instance_id="B", role="worker")
    await disp.dispatch(source="A", target="B", payload=tany(x=1))
    await disp.dispatch(source="A", target="B", payload=tany(x=2))
    cmds = await disp.flush(instance_id="B")
    assert len(cmds) == 2
    assert [c["payload"]["x"] for c in cmds] == [1, 2]
