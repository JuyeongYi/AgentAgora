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
