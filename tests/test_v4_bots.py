import json
import pytest
from agent_agora.server import create_agora_app
from agent_agora.registry import InstanceRegistry
from agent_agora.bot_registry import BotRegistry
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import Persistence, AsyncWriteQueue
from _helpers import make_schema_registry


class FakeCtx:
    """_session_id_from_ctx가 읽는 ctx.request_context.request.headers를 흉내낸다."""
    def __init__(self, session_id):
        self.request_context = type("RC", (), {"request": type("R", (), {
            "headers": {"mcp-session-id": session_id}})()})()


def _tool(mcp, name):
    return mcp._tool_manager.get_tool(name).fn


@pytest.fixture
async def app(tmp_path):
    instance_registry = InstanceRegistry()
    bot_registry = BotRegistry()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            persistence=persistence, dispatcher=dispatcher, port=0)
        yield mcp, instance_registry, bot_registry, schema_registry


@pytest.mark.asyncio
async def test_register_bot_handler_succeeds(app):
    mcp, _, bot_registry, schema_reg = app
    schema_reg.register(
        "pytest_run",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "pytest_run"}}},
        kind="bot-task", purpose="pytest")
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a",
        description="run pytest", bot_mode="handler",
        subscribe_schemas=["pytest_run"]))
    assert res["status"] == "ok"
    assert bot_registry.resolve_instance_id("bot_a").description == "run pytest"


@pytest.mark.asyncio
async def test_register_bot_missing_description_rejected(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="",
        bot_mode="handler", subscribe_schemas=["x"]))
    assert "description이 필수" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_handler_empty_subscribe_rejected(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=[]))
    assert "구독 schema가 비어" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_subscribing_conversation_kind_rejected(app):
    mcp, *_ = app
    # worker_freeform is conversation kind
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["worker_freeform"]))
    assert "conversation kind" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_with_inline_schemas(app):
    mcp, _, _, schema_reg = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["build_run"],
        schemas={"build_run": {
            "kind": "bot-task", "purpose": "빌드 실행",
            "body": {"type": "object", "required": ["msgtype"],
                     "properties": {"msgtype": {"const": "build_run"}}}}}))
    assert res["status"] == "ok"
    assert schema_reg.get("build_run").kind == "bot-task"


@pytest.mark.asyncio
async def test_register_bot_schema_diff_preflight_blocks(app):
    mcp, _, _, schema_reg = app
    body_v1 = {"type": "object", "required": ["msgtype"],
               "properties": {"msgtype": {"const": "build_run"}}}
    schema_reg.register("build_run", body_v1, kind="bot-task", purpose="v1")
    body_v2 = dict(body_v1, required=["msgtype", "extra"])
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["build_run"],
        schemas={"build_run": {"kind": "bot-task", "purpose": "v2", "body": body_v2}}))
    assert "이미 등록됨" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_observer_mode(app):
    mcp, _, bot_registry, _ = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-obs"), instance_id="bot_obs", description="archiver",
        bot_mode="observer"))
    assert res["status"] == "ok"
    assert bot_registry.observers() == {"bot_obs"}


@pytest.mark.asyncio
async def test_bots_lists_only_bots_instances_lists_only_workers(app):
    mcp, instance_registry, bot_registry, schema_reg = app
    instance_registry.register("ws1", "worker_x")
    schema_reg.register("x_task",
        {"type": "object", "properties": {"msgtype": {"const": "x_task"}}},
        kind="bot-task", purpose="p")
    bot_registry.register(session_id="bs1", instance_id="bot_x", description="d",
                          bot_mode="handler", subscribe_schemas=["x_task"])
    bots = json.loads(await _tool(mcp, "agora.bots")())["bots"]
    instances = json.loads(await _tool(mcp, "agora.instances")())["instances"]
    assert {b["instance_id"] for b in bots} == {"bot_x"}
    assert {i["instance_id"] for i in instances} == {"worker_x"}


@pytest.mark.asyncio
async def test_find_returns_workers_and_bots_with_kind(app):
    mcp, instance_registry, bot_registry, schema_reg = app
    instance_registry.register("ws1", "worker_build", description="build helper")
    schema_reg.register("build_task",
        {"type": "object", "properties": {"msgtype": {"const": "build_task"}}},
        kind="bot-task", purpose="p")
    bot_registry.register(session_id="bs1", instance_id="bot_build",
                          description="build bot", bot_mode="handler",
                          subscribe_schemas=["build_task"])
    found = json.loads(await _tool(mcp, "agora.find")("build"))["results"]
    kinds = {r["instance_id"]: r["kind"] for r in found}
    assert kinds == {"worker_build": "worker", "bot_build": "bot"}


@pytest.mark.asyncio
async def test_bot_emit_requires_bot_caller(app):
    mcp, instance_registry, *_ = app
    instance_registry.register("ws1", "worker_x")
    res = json.loads(await _tool(mcp, "agora.bot_emit")(
        FakeCtx("ws1"),
        payload={"msgtype": "bot_reply", "from": "worker_x",
                 "ts": "2026-01-01T00:00:00Z", "result": "x"}))
    assert "봇만 호출" in res["error"]


@pytest.mark.asyncio
async def test_worker_dispatch_to_bot_then_bot_emit_chain(app):
    mcp, instance_registry, bot_registry, schema_reg = app
    schema_reg.register("ping_task",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "ping_task"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    instance_registry.register("ws1", "worker_x")
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("bs1"), instance_id="bot_p", description="d",
        bot_mode="handler", subscribe_schemas=["ping_task"])
    # worker dispatches with target omitted -> schema-routed to bot
    disp = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "ping_task", "v": 1}))
    assert disp["status"] == "ok"
    got = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("bs1"), timeout_ms=200))
    assert len(got["commands"]) == 1
    cmd_id = got["commands"][0]["id"]
    # bot emits a result back to the original caller
    await _tool(mcp, "agora.bot_emit")(
        FakeCtx("bs1"),
        payload={"msgtype": "bot_reply", "from": "bot_p",
                 "ts": "2026-01-01T00:00:00Z", "result": {"pong": 1}},
        in_reply_to=cmd_id)
    reply = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("ws1"), timeout_ms=200))
    assert reply["commands"][0]["payload"]["result"] == {"pong": 1}


@pytest.mark.asyncio
async def test_bot_cannot_call_dispatch(app):
    mcp, _, bot_registry, schema_reg = app
    schema_reg.register("t1",
        {"type": "object", "properties": {"msgtype": {"const": "t1"}}},
        kind="bot-task", purpose="p")
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("bs1"), instance_id="bot_d", description="d",
        bot_mode="handler", subscribe_schemas=["t1"])
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("bs1"), payload={"msgtype": "t1"}, target="bot_d"))
    assert "봇은" in res["error"] and "bot_emit" in res["error"]
