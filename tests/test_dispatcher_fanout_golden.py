"""Golden characterization of dispatch fan-out routing.

Isolated safety net for the dispatcher routing decomposition (Wave 5): pins the
delivered_as roles, the deliveries[] / dispatched_to structure, and skipped_full
behaviour BEFORE the routing core is refactored. Lives in its own file so it does
not collide with the harness-consolidated dispatcher test modules.
"""
import logging

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry


def _register_task_schema(dispatcher):
    dispatcher._schema_registry.register(
        "fanout_task",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"type": "string", "const": "fanout_task"}},
         "additionalProperties": True},
        kind="bot-task", purpose="golden fan-out")
    return {"msgtype": "fanout_task"}


async def _make_dispatcher(tmp_path, *, max_inbox_depth=100):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    dispatcher = Dispatcher(
        registry, persistence, queue,
        schema_registry=make_schema_registry(),
        bot_registry=BotRegistry(),
        comm_matrix=CommMatrix(),
        default_timeout_ms=300,
        max_inbox_depth=max_inbox_depth)
    return registry, dispatcher, queue


@pytest.mark.asyncio
async def test_fanout_primary_cc_and_subscriber_bot(tmp_path):
    registry, dispatcher, queue = await _make_dispatcher(tmp_path)
    async with queue:
        payload = _register_task_schema(dispatcher)
        dispatcher._bot_registry.register(
            session_id="bs1", instance_id="bot_a", description="d",
            bot_mode="handler", subscribe_schemas=["fanout_task"])

        res = await dispatcher.dispatch(
            source="Inst1", target="Inst2", payload=payload, cc=["Inst3"])

        # dispatched_to: primary target + cc + subscriber bot, each with its role.
        delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
        assert delivered == {"Inst2": "primary", "Inst3": "cc", "bot_a": "subscribed"}

        # deliveries[]: per-target {target, role, status}, all delivered.
        by_target = {d["target"]: d for d in res["deliveries"]}
        assert by_target["Inst2"]["status"] == "delivered"
        assert by_target["Inst2"]["role"] == "primary"
        assert by_target["Inst3"]["role"] == "cc"
        assert by_target["bot_a"]["role"] == "subscribed"
        assert res["skipped_full"] == []

        # each recipient's inbox actually received it with the right delivered_as.
        assert (await dispatcher.flush("Inst2"))[0]["delivered_as"] == "primary"
        assert (await dispatcher.flush("Inst3"))[0]["delivered_as"] == "cc"
        assert (await dispatcher.flush("bot_a"))[0]["delivered_as"] == "subscribed"


@pytest.mark.asyncio
async def test_fanout_skips_full_cc_inbox(tmp_path):
    registry, dispatcher, queue = await _make_dispatcher(tmp_path, max_inbox_depth=1)
    async with queue:
        payload = _register_task_schema(dispatcher)
        # Fill Inst3's inbox to the depth cap (1) via a prior primary dispatch.
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload=payload)
        # Now cc Inst3 on another dispatch — its inbox is full → skipped_full.
        res = await dispatcher.dispatch(
            source="Inst1", target="Inst2", payload=payload, cc=["Inst3"])
        assert "Inst3" in res["skipped_full"]
        by_target = {d["target"]: d for d in res["deliveries"]}
        assert by_target["Inst3"]["status"] == "skipped_full"
        assert by_target["Inst2"]["status"] == "delivered"


@pytest.mark.asyncio
async def test_broadcast_fanout_primary_and_bots(tmp_path):
    """broadcast: 모든 워커(source 제외)에 primary + subscriber(subscribed)/observer(cc) 봇 fan-out."""
    registry, dispatcher, queue = await _make_dispatcher(tmp_path)
    async with queue:
        payload = _register_task_schema(dispatcher)
        dispatcher._bot_registry.register(session_id="bs", instance_id="bot_s", description="d",
                                          bot_mode="handler", subscribe_schemas=["fanout_task"])
        dispatcher._bot_registry.register(session_id="bo", instance_id="bot_o", description="d",
                                          bot_mode="observer")
        res = await dispatcher.broadcast(source="Inst1", payload=payload)
        delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
        # 워커 Inst2/3/4 = primary, subscriber 봇 = subscribed, observer 봇 = cc
        assert delivered["Inst2"] == "primary"
        assert delivered["Inst3"] == "primary"
        assert delivered["Inst4"] == "primary"
        assert delivered["bot_s"] == "subscribed"
        assert delivered["bot_o"] == "cc"
        assert (await dispatcher.flush("Inst2"))[0]["delivered_as"] == "primary"
        assert (await dispatcher.flush("bot_s"))[0]["delivered_as"] == "subscribed"
        assert (await dispatcher.flush("bot_o"))[0]["delivered_as"] == "cc"


@pytest.mark.asyncio
async def test_bot_emit_fanout_subscribers_and_observers(tmp_path):
    """bot_emit (target/in_reply_to 없음): msgtype 구독 봇=subscribed, observer=cc fan-out."""
    registry, dispatcher, queue = await _make_dispatcher(tmp_path)
    async with queue:
        payload = _register_task_schema(dispatcher)
        dispatcher._bot_registry.register(session_id="bs", instance_id="bot_s", description="d",
                                          bot_mode="handler", subscribe_schemas=["fanout_task"])
        dispatcher._bot_registry.register(session_id="bo", instance_id="bot_o", description="d",
                                          bot_mode="observer")
        res = await dispatcher.bot_emit(source="Inst1", payload=payload)
        delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
        assert delivered["bot_s"] == "subscribed"
        assert delivered["bot_o"] == "cc"
        assert (await dispatcher.flush("bot_s"))[0]["delivered_as"] == "subscribed"


@pytest.mark.asyncio
async def test_bot_emit_to_target_is_primary(tmp_path):
    """bot_emit (target 지정): 해당 워커에 primary 직접 전달."""
    registry, dispatcher, queue = await _make_dispatcher(tmp_path)
    async with queue:
        payload = _register_task_schema(dispatcher)
        res = await dispatcher.bot_emit(source="Inst1", payload=payload, target="Inst2")
        delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
        assert delivered["Inst2"] == "primary"
        assert (await dispatcher.flush("Inst2"))[0]["delivered_as"] == "primary"


@pytest.mark.asyncio
async def test_dispatch_emits_routing_log_not_stdout(tmp_path, caplog):
    """The routing banner is now a logger.info record (was print) — observable
    via caplog and decoupled from stdout."""
    registry, dispatcher, queue = await _make_dispatcher(tmp_path)
    async with queue:
        payload = _register_task_schema(dispatcher)
        with caplog.at_level(logging.INFO, logger="agent_agora.dispatcher"):
            await dispatcher.dispatch(source="Inst1", target="Inst2", payload=payload)
        msgs = [r.getMessage() for r in caplog.records]
        assert any("Inst1" in m and "Inst2" in m for m in msgs)
