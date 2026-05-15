import json
import pytest
from agent_agora.bot_registry import BotRegistry
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
                                bot_registry=BotRegistry(),
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
    bot_registry = BotRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(instance_registry, persistence, queue,
                                schema_registry=schema_registry,
                                bot_registry=bot_registry,
                                default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            persistence=persistence, dispatcher=dispatcher, port=0)
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


@pytest.mark.asyncio
async def test_all_six_default_schemas_have_msgtype_property(app):
    """default 포함 기본 제공 schema 6종 모두 msgtype property를 가진다 (결정 20)."""
    _, _, schema_reg = app
    for name in ("default", "worker_freeform", "bot_reply", "bot_error", "closing", "ack"):
        entry = schema_reg.get(name)
        assert entry is not None, name
        assert "msgtype" in entry.body["properties"], name


@pytest.mark.asyncio
async def test_worker_freeform_regression(app):
    """v3 워커 payload(worker_freeform + 보조필드)가 schema를 통과한다 (§9.1)."""
    mcp, instance_registry, _ = app
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y",
        payload={"msgtype": "worker_freeform", "type": "reply", "from": "worker_x",
                 "ts": "2026-01-01T00:00:00Z", "message": "자유 텍스트",
                 "in_reply_to": "abc", "subject": "보조필드"}))
    assert res["status"] == "ok"


@pytest.mark.asyncio
async def test_dispatch_msgtype_required_and_unknown_rejected(app):
    mcp, instance_registry, _ = app
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    r1 = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y", payload={"no": "msgtype"}))
    assert "msgtype이 없습니다" in r1["error"]
    r2 = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y", payload={"msgtype": "ghost"}))
    assert "registry에 없습니다" in r2["error"]


@pytest.mark.asyncio
async def test_schema_persists_across_restart(tmp_path):
    """register된 도메인 schema가 서버 재시작(_build_app 재호출) 후에도 살아있다."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp1 = _build_app(agora_dir=agora_dir, port=0)
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"const": "domain_x"}}}
    # save_schema는 동기 쓰기(autocommit)라 flush 불필요
    mcp1._agora_persistence.save_schema("domain_x", body, kind="bot-task", purpose="p")
    # 재시작 — _build_app 재호출이 SQLite에서 schema를 복원해야 한다
    mcp2 = _build_app(agora_dir=agora_dir, port=0)
    assert mcp2._agora_schema_registry.get("domain_x") is not None
