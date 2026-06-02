import json
import pytest
from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.storage.persistence import Persistence, AsyncWriteQueue
from agent_agora.errors import AgoraError
from agent_agora.server import create_agora_app
from _helpers import make_schema_registry, tany, wf, get_tool as _tool, FakeCtx


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
                                comm_matrix=CommMatrix(),
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
    drained = await dispatcher.flush("Inst2")
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
    drained = await dispatcher.flush("Inst2")
    closing_msgs = [d for d in drained if d["payload"].get("msgtype") == "closing"]
    assert len(closing_msgs) == 1
    assert closing_msgs[0]["payload"]["reason"] == "끝"




@pytest.fixture
async def app(tmp_path):
    instance_registry = InstanceRegistry()
    schema_registry = make_schema_registry()
    bot_registry = BotRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        comm_matrix = CommMatrix()
        dispatcher = Dispatcher(instance_registry, persistence, queue,
                                schema_registry=schema_registry,
                                bot_registry=bot_registry,
                                comm_matrix=comm_matrix,
                                default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix,
            persistence=persistence, dispatcher=dispatcher, port=0)
        yield mcp, instance_registry, schema_registry


@pytest.mark.asyncio
async def test_register_schema_and_schemas_list(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        FakeCtx("sess-anon"), name="deploy_run", kind="bot-task", purpose="배포 실행",
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
        FakeCtx("sess-anon"), name="bad", kind="bot-task", purpose="p",
        body={"type": "object", "properties": {"x": {"type": "string"}}}))
    assert "msgtype property가 없습니다" in res["error"]


@pytest.mark.asyncio
async def test_register_schema_immutable(app):
    mcp, *_ = app
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"const": "t"}}}
    await _tool(mcp, "agora.register_schema")(
        FakeCtx("sess-anon"), name="t", kind="bot-task", purpose="v1", body=body)
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        FakeCtx("sess-anon"), name="t", kind="bot-task", purpose="v2",
        body=dict(body, required=["msgtype", "x"])))
    assert "이미 등록됨" in res["error"]
    assert res["code"] == "schema_immutable"


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
    """재시작 후 런타임 등록 schema는 복원되지 않는다 (spec §3 재시작 동작).
    빌트인(jsonl) schema와 schema_conflict 시스템 스키마만 매 시작 시 로드된다.
    봇·워커는 재접속 시 스스로 재등록한다."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp1 = _build_app(agora_dir=agora_dir, port=0)
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"const": "domain_x"}}}
    # save_schema는 동기 쓰기(autocommit)라 flush 불필요
    mcp1._agora_persistence.save_schema("domain_x", body, kind="bot-task", purpose="p")
    # 재시작 — 런타임 schema는 복원 안 됨 (ref-counting 하에서 holder가 죽어 고아 ref)
    mcp2 = _build_app(agora_dir=agora_dir, port=0)
    assert mcp2._agora_schema_registry.get("domain_x") is None  # 복원 안 됨
    # 빌트인 schema와 schema_conflict는 여전히 로드됨
    from agent_agora.storage.schemas import SCHEMA_CONFLICT_NAME
    assert mcp2._agora_schema_registry.get(SCHEMA_CONFLICT_NAME) is not None


@pytest.fixture
async def schema_app(tmp_path):
    instance_registry = InstanceRegistry()
    for name in ("Inst1", "Inst2"):
        instance_registry.register(f"sess-{name}", name)
    bot_registry = BotRegistry()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        comm_matrix = CommMatrix()
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, persistence=persistence,
            dispatcher=dispatcher, port=0)
        yield mcp, dispatcher, schema_registry


@pytest.mark.asyncio
async def test_register_schema_holds_ref_for_caller(schema_app):
    """register_schema는 호출자 instance_id를 holder로 ref를 잡는다."""
    mcp, dispatcher, schema_registry = schema_app
    body = {"type": "object", "properties": {"msgtype": {"const": "custom_a"}}}
    r = json.loads(await _tool(mcp, "agora.register_schema")(
        FakeCtx("sess-Inst1"), name="custom_a", body=body,
        kind="bot-task", purpose="p"))
    assert r["status"] == "ok"
    assert schema_registry.refs_of("custom_a") == {"Inst1"}


@pytest.mark.asyncio
async def test_register_schema_conflict_dispatches_notice(schema_app):
    """같은 이름 다른 body → schema_immutable 동기 에러 + schema_conflict 통지."""
    mcp, dispatcher, schema_registry = schema_app
    b1 = {"type": "object", "properties": {"msgtype": {"const": "custom_b"}}}
    b2 = {"type": "object", "properties": {"msgtype": {"const": "custom_b"},
                                           "x": {"type": "string"}}}
    await _tool(mcp, "agora.register_schema")(
        FakeCtx("sess-Inst1"), name="custom_b", body=b1, kind="bot-task", purpose="p")
    r = json.loads(await _tool(mcp, "agora.register_schema")(
        FakeCtx("sess-Inst2"), name="custom_b", body=b2, kind="bot-task", purpose="p"))
    assert "error" in r and "이미 등록됨" in r["error"]
    assert r["code"] == "schema_immutable"
    drained = await dispatcher.flush("Inst2")
    assert any(d["payload"]["msgtype"] == "schema_conflict" for d in drained)
