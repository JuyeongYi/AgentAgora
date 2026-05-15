import pytest
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
    inst2 = await dispatcher.wait("Inst2", timeout_ms=200)
    bot_a = await dispatcher.wait("bot_a", timeout_ms=200)
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
    bot_a = await dispatcher.wait("bot_a", timeout_ms=200)
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
    obs = await dispatcher.wait("bot_obs", timeout_ms=200)
    assert len(obs) == 1 and obs[0]["delivered_as"] == "cc"


@pytest.mark.asyncio
async def test_dispatch_to_worker_still_works_unchanged(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m="hi"))
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    assert len(drained) == 1 and drained[0]["delivered_as"] == "primary"
