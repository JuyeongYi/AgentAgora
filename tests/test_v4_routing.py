import pytest
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.bot_registry import BotRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.errors import AgoraError
from _helpers import make_schema_registry, tany, wf


def _register_pytest_schema(dispatcher):
    body = {
        "type": "object",
        "required": ["msgtype", "scenario"],
        "properties": {
            "msgtype": {"type": "string", "const": "pytest_run"},
            "scenario": {"type": "string"},
        },
        "additionalProperties": False,
    }
    dispatcher._schema_registry.register(
        "pytest_run", body, kind="bot-task", purpose="pytest 실행 요청")
    return {"msgtype": "pytest_run", "scenario": "smoke"}


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
async def test_dispatch_fans_out_to_subscribing_bots(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=payload)
    inst2 = await dispatcher.flush("Inst2", )
    bot_a = await dispatcher.flush("bot_a", )
    assert inst2[0]["delivered_as"] == "primary"
    assert bot_a[0]["delivered_as"] == "subscribed"
    delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
    assert delivered == {"Inst2": "primary", "bot_a": "subscribed"}


@pytest.mark.asyncio
async def test_dispatch_target_omitted_routes_to_bots(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    bot_a = await dispatcher.flush("bot_a", )
    assert len(bot_a) == 1 and bot_a[0]["delivered_as"] == "subscribed"
    assert all(d["as"] == "subscribed" for d in res["dispatched_to"])
    assert res["target_inbox_depth_after"] == {}


@pytest.mark.asyncio
async def test_dispatch_target_omitted_no_subscriber_raises_no_route(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    assert ei.value.code == "no_route"


@pytest.mark.asyncio
async def test_dispatch_to_bot_target_not_subscribing_raises_unhandled(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["other_unused"])
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="bot_a", payload=payload)
    assert ei.value.code == "unhandled_schema"


@pytest.mark.asyncio
async def test_dispatch_observer_receives_cc(setup):
    registry, dispatcher = setup
    dispatcher._bot_registry.register(
        session_id="bo1", instance_id="bot_obs", description="d", bot_mode="observer")
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=wf("관찰"))
    obs = await dispatcher.flush("bot_obs", )
    assert len(obs) == 1 and obs[0]["delivered_as"] == "cc"


@pytest.mark.asyncio
async def test_dispatch_to_worker_still_works_unchanged(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m="hi"))
    drained = await dispatcher.flush("Inst2", )
    assert len(drained) == 1 and drained[0]["delivered_as"] == "primary"


@pytest.mark.asyncio
async def test_broadcast_fans_out_to_subscribing_bots(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.broadcast(source="Inst1", payload=payload)
    bot_a = await dispatcher.flush("bot_a", )
    assert len(bot_a) == 1 and bot_a[0]["delivered_as"] == "subscribed"
    inst2 = await dispatcher.flush("Inst2", )
    assert inst2[0]["delivered_as"] == "primary"
    delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
    assert delivered["bot_a"] == "subscribed"


@pytest.mark.asyncio
async def test_broadcast_observer_receives_cc(setup):
    registry, dispatcher = setup
    dispatcher._bot_registry.register(
        session_id="bo1", instance_id="bot_obs", description="d", bot_mode="observer")
    await dispatcher.broadcast(source="Inst1", payload=wf("공지"))
    obs = await dispatcher.flush("bot_obs", )
    assert len(obs) == 1 and obs[0]["delivered_as"] == "cc"


def _bot_reply(result="ok"):
    return {"msgtype": "bot_reply", "from": "bot_a",
            "ts": "2026-01-01T00:00:00Z", "result": result}


@pytest.mark.asyncio
async def test_bot_emit_in_reply_to_routes_to_original_source(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    cmd_id = res["command_id"]
    await dispatcher.bot_emit(source="bot_a", payload=_bot_reply(), in_reply_to=cmd_id)
    inst1 = await dispatcher.flush("Inst1", )
    assert len(inst1) == 1
    assert inst1[0]["payload"]["msgtype"] == "bot_reply"
    assert inst1[0]["in_reply_to"] == cmd_id


@pytest.mark.asyncio
async def test_bot_emit_without_in_reply_to_fans_out_to_subscribers(setup):
    registry, dispatcher = setup
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"type": "string", "const": "metric_log"}},
            "additionalProperties": True}
    dispatcher._schema_registry.register("metric_log", body, kind="bot-task", purpose="metric")
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_metric", description="d",
        bot_mode="handler", subscribe_schemas=["metric_log"])
    await dispatcher.bot_emit(source="bot_src", payload={"msgtype": "metric_log", "v": 1})
    got = await dispatcher.flush("bot_metric", )
    assert len(got) == 1 and got[0]["delivered_as"] == "subscribed"


@pytest.mark.asyncio
async def test_bot_emit_validates_payload(setup):
    registry, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.bot_emit(source="bot_a", payload={"no": "msgtype"})
    assert ei.value.code == "payload_missing_msgtype"


@pytest.mark.asyncio
async def test_bot_emit_in_reply_to_unknown_cmd_no_crash(setup):
    registry, dispatcher = setup
    res = await dispatcher.bot_emit(source="bot_a", payload=_bot_reply(),
                                    in_reply_to="cmd-never-existed")
    assert res["dispatched_to"] == []


@pytest.mark.asyncio
async def test_bot_can_wait_even_though_not_in_instance_registry(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    # bot_a is NOT in InstanceRegistry — wait must still resolve it via BotRegistry
    got = await dispatcher.flush("bot_a")
    assert len(got) == 1


@pytest.mark.asyncio
async def test_wait_unknown_id_still_raises(setup):
    registry, dispatcher = setup
    from agent_agora.registry import NotRegisteredError
    with pytest.raises(NotRegisteredError):
        await dispatcher.flush("ghost_nobody")
