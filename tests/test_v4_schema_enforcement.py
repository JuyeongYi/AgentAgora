import json
import pytest
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.errors import AgoraError
from agent_agora.server import create_agora_app
from _helpers import make_schema_registry, tany, wf


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                default_timeout_ms=500)
        yield registry, dispatcher


@pytest.mark.asyncio
async def test_dispatch_rejects_payload_without_msgtype(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": "hi"})
    assert ei.value.code == "payload_missing_msgtype"


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_msgtype(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="Inst2",
                                  payload={"msgtype": "nonexistent"})
    assert ei.value.code == "unknown_msgtype"


@pytest.mark.asyncio
async def test_dispatch_rejects_schema_violation(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="Inst2",
                                  payload={"msgtype": "worker_freeform"})
    assert ei.value.code == "schema_violation"


@pytest.mark.asyncio
async def test_dispatch_accepts_valid_worker_freeform(setup):
    _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=wf("안녕"))
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    assert drained[0]["payload"]["message"] == "안녕"


@pytest.mark.asyncio
async def test_broadcast_rejects_payload_without_msgtype(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.broadcast(source="Inst1", payload={"m": "hi"})
    assert ei.value.code == "payload_missing_msgtype"


@pytest.mark.asyncio
async def test_close_thread_uses_closing_schema(setup):
    _, dispatcher = setup
    conv = "conv-close-x"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1),
                              conversation_id=conv)
    res = await dispatcher.close_thread("Inst1", conv, reason="끝")
    assert res["conversation_id"] == conv
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    closing_msgs = [d for d in drained if d["payload"].get("msgtype") == "closing"]
    assert len(closing_msgs) == 1
    assert closing_msgs[0]["payload"]["reason"] == "끝"


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
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(instance_registry, persistence, queue,
                                schema_registry=schema_registry, default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, persistence=persistence,
            dispatcher=dispatcher, port=0)
        yield mcp, instance_registry, schema_registry


@pytest.mark.asyncio
async def test_register_schema_and_schemas_list(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        name="deploy_run", kind="bot-task", purpose="배포 실행",
        body={"type": "object", "required": ["msgtype"],
              "properties": {"msgtype": {"const": "deploy_run"}}}))
    assert res["status"] == "ok"
    meta = json.loads(await _tool(mcp, "agora.schemas_list")())["schemas"]
    names = {m["name"]: m for m in meta}
    assert names["deploy_run"]["kind"] == "bot-task"
    assert names["deploy_run"]["purpose"] == "배포 실행"


@pytest.mark.asyncio
async def test_register_schema_missing_msgtype_rejected(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        name="bad", kind="bot-task", purpose="p",
        body={"type": "object", "properties": {"x": {"type": "string"}}}))
    assert "msgtype property가 없습니다" in res["error"]


@pytest.mark.asyncio
async def test_register_schema_immutable(app):
    mcp, *_ = app
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"const": "t"}}}
    await _tool(mcp, "agora.register_schema")(name="t", kind="bot-task", purpose="v1", body=body)
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        name="t", kind="bot-task", purpose="v2",
        body=dict(body, required=["msgtype", "x"])))
    assert "이미 등록됨" in res["error"]


@pytest.mark.asyncio
async def test_schemas_returns_full_body(app):
    mcp, *_ = app
    full = json.loads(await _tool(mcp, "agora.schemas")())["schemas"]
    wf = next(s for s in full if s["name"] == "worker_freeform")
    assert "body" in wf and "properties" in wf["body"]
