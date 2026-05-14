from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.schema import SchemaRegistry
from agent_agora.server import create_agora_app
from agent_agora.store import AgoraStore


@pytest.fixture
def runtime(tmp_path, sample_schemas):
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    (agora_dir / "schemas.json").write_text(json.dumps(sample_schemas))
    schema_reg = SchemaRegistry.load(agora_dir)
    store = AgoraStore(agora_dir, schema_reg)
    inst_reg = InstanceRegistry()
    disp = Dispatcher(inst_reg, default_timeout_ms=2000)
    mcp, queue = create_agora_app(agora_dir, store, schema_reg, inst_reg, disp, port=0)
    return mcp, queue, inst_reg, disp


async def test_a_dispatches_b_receives(runtime):
    """A registers, B registers, A dispatches, B's wait future wakes and returns the command."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")

        wait_task = asyncio.create_task(disp.wait(instance_id="B", timeout_ms=1000))
        await asyncio.sleep(0.05)
        await disp.dispatch(source="A", target="B", payload={"task": "run-tests"})

        commands = await wait_task
        assert len(commands) == 1
        assert commands[0]["payload"] == {"task": "run-tests"}
        assert commands[0]["source"] == "A"
        assert commands[0]["target"] == "B"


async def test_broadcast_fans_out(runtime):
    """A broadcasts; all OTHER registered instances receive; A itself does not."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")
        inst_reg.register(session_id="sC", instance_id="C", role="worker")

        await disp.dispatch(source="A", target="_broadcast", payload={"ping": 1})
        b = await disp.wait(instance_id="B", timeout_ms=200)
        c = await disp.wait(instance_id="C", timeout_ms=200)
        assert len(b) == 1 and b[0]["payload"] == {"ping": 1}
        assert len(c) == 1 and c[0]["payload"] == {"ping": 1}

        a = await disp.wait(instance_id="A", timeout_ms=100)
        assert a == []


async def test_result_writeback_via_second_dispatch(runtime):
    """B processes a command, then dispatches a result back to A as a separate command."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")

        cmd_id = await disp.dispatch(
            source="A", target="B", payload={"task": "echo", "value": 42}, expect_result=True,
        )
        cmds = await disp.wait(instance_id="B", timeout_ms=500)
        assert len(cmds) == 1
        assert cmds[0]["expect_result"] is True
        original_id = cmds[0]["id"]
        assert original_id == cmd_id

        await disp.dispatch(source="B", target="A", payload={
            "result_for": original_id,
            "value": 42,
        })
        a_cmds = await disp.wait(instance_id="A", timeout_ms=500)
        assert len(a_cmds) == 1
        assert a_cmds[0]["payload"]["result_for"] == cmd_id
        assert a_cmds[0]["payload"]["value"] == 42


async def test_unknown_target_dispatch_raises(runtime):
    """Dispatch to an unregistered instance raises NotRegisteredError."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        with pytest.raises(NotRegisteredError):
            await disp.dispatch(source="A", target="ghost", payload={})


async def test_unregister_session_removes_instance(runtime):
    """Unregistering a session removes both forward and reverse mappings; subsequent
    dispatch to that instance raises."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")
        inst_reg.unregister_session("sB")
        with pytest.raises(NotRegisteredError):
            inst_reg.resolve_instance_id("B")
        with pytest.raises(NotRegisteredError):
            await disp.dispatch(source="A", target="B", payload={})


async def test_dispatch_queues_when_no_waiter_then_drains_on_first_wait(runtime):
    """If A dispatches before B calls wait, the command queues and B receives it
    on the next wait call (no timeout suffered)."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")
        await disp.dispatch(source="A", target="B", payload={"x": 1})
        await disp.dispatch(source="A", target="B", payload={"x": 2})
        cmds = await disp.wait(instance_id="B", timeout_ms=100)
        assert len(cmds) == 2
        assert [c["payload"]["x"] for c in cmds] == [1, 2]
