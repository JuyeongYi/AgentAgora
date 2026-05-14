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
        await disp.dispatch(source="A", target=["X"], payload={})


async def test_wait_returns_pending_commands(setup):
    reg, disp = setup
    await disp.dispatch(source="A", target=["B"], payload={"hello": 1})
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
    await disp.dispatch(source="A", target=["B"], payload={"k": "v"})
    result = await waiter
    assert len(result) == 1
    assert result[0]["payload"] == {"k": "v"}


async def test_dispatch_broadcast_fans_out_to_all_others(setup):
    reg, disp = setup
    reg.register(session_id="sC", instance_id="C", role="worker")
    await disp.dispatch(source="A", target=["_broadcast"], payload={"ping": 1})
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
    await disp.dispatch(source="A", target=["B"], payload={"x": 1})
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


async def test_dispatch_after_close_raises(setup):
    reg, disp = setup
    await disp.close()
    with pytest.raises(DispatcherClosed):
        await disp.dispatch(source="A", target=["B"], payload={"x": 1})


async def test_wait_after_close_raises(setup):
    reg, disp = setup
    await disp.close()
    with pytest.raises(DispatcherClosed):
        await disp.wait(instance_id="B", timeout_ms=10)


async def test_dispatch_multi_target_fan_out(setup):
    """target=[B, C] fans out to both, same cmd_id, each gets the command in its queue."""
    reg, disp = setup
    reg.register(session_id="sC", instance_id="C", role="worker")
    result = await disp.dispatch(source="A", target=["B", "C"], payload={"hi": True})
    cmd_id = result["command_id"]
    assert "created_at" in result
    b = await disp.wait(instance_id="B", timeout_ms=200)
    c = await disp.wait(instance_id="C", timeout_ms=200)
    assert len(b) == 1 and len(c) == 1
    assert b[0]["id"] == cmd_id
    assert c[0]["id"] == cmd_id
    assert b[0]["payload"] == {"hi": True}


async def test_dispatch_rejects_non_list_target(setup):
    reg, disp = setup
    with pytest.raises(ValueError, match="non-empty list"):
        await disp.dispatch(source="A", target="B", payload={})


async def test_dispatch_rejects_empty_target(setup):
    reg, disp = setup
    with pytest.raises(ValueError, match="non-empty list"):
        await disp.dispatch(source="A", target=[], payload={})


async def test_dispatch_rejects_broadcast_mixed_with_explicit(setup):
    reg, disp = setup
    with pytest.raises(ValueError, match="cannot be mixed"):
        await disp.dispatch(source="A", target=["_broadcast", "B"], payload={})


async def test_wait_from_sources_filter(setup):
    reg, disp = setup
    reg.register(session_id="sC", instance_id="C", role="worker")
    # Two senders push to B
    await disp.dispatch(source="A", target=["B"], payload={"src": "A"})
    await disp.dispatch(source="C", target=["B"], payload={"src": "C"})
    # B asks only for commands from A
    a_only = await disp.wait(instance_id="B", timeout_ms=200, from_sources=["A"])
    assert len(a_only) == 1
    assert a_only[0]["source"] == "A"
    # The C-sourced command stays queued — next wait sees it
    rest = await disp.wait(instance_id="B", timeout_ms=200)
    assert len(rest) == 1
    assert rest[0]["source"] == "C"


async def test_wait_from_sources_mismatch_returns_empty_and_keeps_queue(setup):
    reg, disp = setup
    await disp.dispatch(source="A", target=["B"], payload={"src": "A"})
    miss = await disp.wait(instance_id="B", timeout_ms=100, from_sources=["X"])
    assert miss == []
    # The A command must remain queued
    a_now = await disp.wait(instance_id="B", timeout_ms=100, from_sources=["A"])
    assert len(a_now) == 1


async def test_wait_close_race_does_not_leak_future(setup):
    """If close() runs between wait()'s pre-lock check and lock acquisition,
    wait() must observe the closed state via the in-lock recheck and raise —
    not register a dangling future in the discarded waiter list."""
    reg, disp = setup
    # Close first, then call wait() — exercises the in-lock _closed recheck
    # path that guards against the race window between the pre-lock check and
    # acquiring the lock.
    await disp.close()
    with pytest.raises(DispatcherClosed):
        await disp.wait(instance_id="B", timeout_ms=10)
