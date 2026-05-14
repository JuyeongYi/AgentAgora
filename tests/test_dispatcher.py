from __future__ import annotations

import asyncio

import pytest

from agent_agora.dispatcher import Dispatcher, DispatcherClosed
from agent_agora.registry import InstanceRegistry, NotRegisteredError


@pytest.fixture
def setup():
    reg = InstanceRegistry()
    reg.register(session_id="sA", instance_id="A", role="orch")
    reg.register(session_id="sB", instance_id="B", role="worker")
    disp = Dispatcher(reg, default_timeout_ms=1000)
    return reg, disp


async def test_dispatch_to_unknown_target_raises(setup):
    reg, disp = setup
    with pytest.raises(NotRegisteredError):
        await disp.dispatch(source="A", target="X", payload={})


async def test_wait_returns_pending_commands(setup):
    reg, disp = setup
    await disp.dispatch(source="A", target="B", payload={"hello": 1})
    commands = await disp.wait(instance_id="B", timeout_ms=500)
    assert len(commands) == 1
    assert commands[0]["source"] == "A"
    assert commands[0]["payload"] == {"hello": 1}


async def test_wait_empty_after_timeout(setup):
    reg, disp = setup
    commands = await disp.wait(instance_id="B", timeout_ms=50)
    assert commands == []


async def test_wait_wakes_when_command_arrives(setup):
    reg, disp = setup

    async def wait_task():
        return await disp.wait(instance_id="B", timeout_ms=2000)

    waiter = asyncio.create_task(wait_task())
    await asyncio.sleep(0.05)
    await disp.dispatch(source="A", target="B", payload={"k": "v"})
    result = await waiter
    assert len(result) == 1
    assert result[0]["payload"] == {"k": "v"}


async def test_dispatch_broadcast_fans_out_to_all_others(setup):
    reg, disp = setup
    reg.register(session_id="sC", instance_id="C", role="worker")
    await disp.dispatch(source="A", target="_broadcast", payload={"ping": 1})
    b_cmds = await disp.wait(instance_id="B", timeout_ms=200)
    c_cmds = await disp.wait(instance_id="C", timeout_ms=200)
    assert len(b_cmds) == 1
    assert len(c_cmds) == 1
    # broadcast excludes the sender
    a_cmds = await disp.wait(instance_id="A", timeout_ms=50)
    assert a_cmds == []


async def test_wait_no_timeout_blocks_until_command(setup):
    reg, disp = setup

    async def waiter_no_timeout():
        return await disp.wait(instance_id="B", timeout_ms=0)

    task = asyncio.create_task(waiter_no_timeout())
    await asyncio.sleep(0.1)
    assert not task.done()
    await disp.dispatch(source="A", target="B", payload={"x": 1})
    result = await asyncio.wait_for(task, timeout=1.0)
    assert len(result) == 1


async def test_close_releases_all_waiters(setup):
    reg, disp = setup

    async def w():
        return await disp.wait(instance_id="B", timeout_ms=0)

    task = asyncio.create_task(w())
    await asyncio.sleep(0.05)
    await disp.close()
    with pytest.raises(DispatcherClosed):
        await task


async def test_wait_for_unregistered_instance_raises(setup):
    reg, disp = setup
    with pytest.raises(NotRegisteredError):
        await disp.wait(instance_id="ghost", timeout_ms=10)
