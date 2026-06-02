import json
import pytest
from agent_agora.comm_matrix import CommMatrix
from agent_agora.server import create_agora_app
from agent_agora.registry import InstanceRegistry
from agent_agora.registry import BotRegistry
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import Persistence, AsyncWriteQueue
from _helpers import make_schema_registry, get_tool as _tool, FakeCtx


@pytest.fixture
async def bot_app(tmp_path):
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




@pytest.fixture
async def app(tmp_path):
    instance_registry = InstanceRegistry()
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
            comm_matrix=comm_matrix,
            default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix,
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
    assert res["code"] == "schema_immutable"


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
    got = json.loads(await _tool(mcp, "agora.flush")(FakeCtx("bs1")))
    assert len(got["commands"]) == 1
    cmd_id = got["commands"][0]["id"]
    # bot emits a result back to the original caller
    await _tool(mcp, "agora.bot_emit")(
        FakeCtx("bs1"),
        payload={"msgtype": "bot_reply", "from": "bot_p",
                 "ts": "2026-01-01T00:00:00Z", "result": {"pong": 1}},
        in_reply_to=cmd_id)
    reply = json.loads(await _tool(mcp, "agora.flush")(FakeCtx("ws1")))
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


async def _register_bot(mcp, sess, iid, subscribe, mode="handler"):
    return json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx(sess), instance_id=iid, description="d",
        bot_mode=mode, subscribe_schemas=subscribe))


@pytest.mark.asyncio
async def test_multi_bot_subscription_fan_out(app):
    """같은 schema를 N봇이 구독하면 한 메시지가 N봇 모두에 fan-out (결정 25)."""
    mcp, instance_registry, _, schema_reg = app
    schema_reg.register("pytest_run",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "pytest_run"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    await _register_bot(mcp, "bs1", "bot_a", ["pytest_run"])
    await _register_bot(mcp, "bs2", "bot_b", ["pytest_run"])
    instance_registry.register("ws1", "worker_x")
    await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "pytest_run", "scenario": "s"})
    a = json.loads(await _tool(mcp, "agora.flush")(FakeCtx("bs1")))
    b = json.loads(await _tool(mcp, "agora.flush")(FakeCtx("bs2")))
    assert len(a["commands"]) == 1 and len(b["commands"]) == 1


@pytest.mark.asyncio
async def test_observer_receives_all_messages(app):
    """observer는 schema 무관 모든 메시지를 cc로 받는다."""
    mcp, instance_registry, _, _ = app
    await _register_bot(mcp, "bo1", "bot_obs", [], mode="observer")
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    await _tool(mcp, "agora.dispatch")(FakeCtx("ws1"), target="worker_y",
        payload={"msgtype": "worker_freeform", "type": "task",
                 "from": "worker_x", "ts": "2026-01-01T00:00:00Z", "message": "hi"})
    obs = json.loads(await _tool(mcp, "agora.flush")(FakeCtx("bo1")))
    assert len(obs["commands"]) == 1
    assert obs["commands"][0]["delivered_as"] == "cc"


@pytest.mark.asyncio
async def test_no_route_when_no_subscriber_and_no_target(app):
    """target 생략 + 구독 봇 없음 → no_route 에러."""
    mcp, instance_registry, _, schema_reg = app
    schema_reg.register("orphan_task",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "orphan_task"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    instance_registry.register("ws1", "worker_x")
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "orphan_task"}))
    assert "구독하는 봇이 없고" in res["error"]


@pytest.mark.asyncio
async def test_worker_freeform_regression_through_broker(app):
    """v3 워커 payload(worker_freeform + 보조필드)가 broker를 통과한다 (§9.1)."""
    mcp, instance_registry, _, _ = app
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y",
        payload={"msgtype": "worker_freeform", "type": "reply", "from": "worker_x",
                 "ts": "2026-01-01T00:00:00Z", "message": "자유 텍스트",
                 "in_reply_to": "abc", "subject": "보조필드"}))
    assert res["status"] == "ok"


@pytest.mark.asyncio
async def test_bot_error_emit_reaches_caller(app):
    """봇이 bot_error를 in_reply_to로 emit하면 원 caller가 받는다 (§3.7)."""
    mcp, instance_registry, _, schema_reg = app
    schema_reg.register("job",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "job"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    instance_registry.register("ws1", "worker_x")
    await _register_bot(mcp, "bs1", "bot_j", ["job"])
    disp = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "job"}))
    cmd_id = disp["command_id"]
    await _tool(mcp, "agora.bot_emit")(
        FakeCtx("bs1"),
        payload={"msgtype": "bot_error", "from": "bot_j",
                 "ts": "2026-01-01T00:00:00Z",
                 "error_code": "boom", "error_message": "handler failed"},
        in_reply_to=cmd_id)
    reply = json.loads(await _tool(mcp, "agora.flush")(FakeCtx("ws1")))
    assert reply["commands"][0]["payload"]["error_code"] == "boom"


@pytest.mark.asyncio
async def test_unregister_removes_bot_from_registry(app):
    """봇이 agora.unregister를 호출하면 BotRegistry에서 제거되고 fan-out 대상에서 빠진다."""
    mcp, _, bot_registry, schema_reg = app
    schema_reg.register("u_task",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "u_task"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("bs1"), instance_id="bot_u", description="d",
        bot_mode="handler", subscribe_schemas=["u_task"])
    assert bot_registry.is_bot("bot_u") is True
    assert bot_registry.subscribers_of("u_task") == {"bot_u"}
    res = json.loads(await _tool(mcp, "agora.unregister")(FakeCtx("bs1")))
    assert res["status"] == "ok"
    assert bot_registry.is_bot("bot_u") is False
    assert bot_registry.subscribers_of("u_task") == set()


@pytest.mark.asyncio
async def test_bot_emit_rejects_unknown_msgtype(app):
    """bot_emit payload의 msgtype이 registry에 없으면 unknown_msgtype 에러."""
    mcp, _, bot_registry, _ = app
    bot_registry.register(session_id="bs1", instance_id="bot_e", description="d",
                          bot_mode="observer")
    res = json.loads(await _tool(mcp, "agora.bot_emit")(
        FakeCtx("bs1"), payload={"msgtype": "ghost_unregistered_xyz"}))
    assert "registry에 없습니다" in res["error"]


@pytest.mark.asyncio
async def test_bot_inline_schema_holds_ref(bot_app):
    """register_bot 인라인 schemas= → 봇이 holder ref 보유."""
    mcp, dispatcher, schema_registry = bot_app
    body = {"type": "object", "properties": {"msgtype": {"const": "echo_task"}}}
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("sess-bot1"), instance_id="bot1", description="d",
        bot_mode="handler", subscribe_schemas=["echo_task"],
        schemas={"echo_task": {"kind": "bot-task", "purpose": "p", "body": body}})
    assert "bot1" in schema_registry.refs_of("echo_task")


@pytest.mark.asyncio
async def test_unregister_releases_schema_ref(bot_app):
    """봇 unregister → 그 봇이 마지막 holder면 스키마 해제."""
    mcp, dispatcher, schema_registry = bot_app
    body = {"type": "object", "properties": {"msgtype": {"const": "echo2"}}}
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("sess-bot1"), instance_id="bot1", description="d",
        bot_mode="handler", subscribe_schemas=["echo2"],
        schemas={"echo2": {"kind": "bot-task", "purpose": "p", "body": body}})
    assert schema_registry.get("echo2") is not None
    await _tool(mcp, "agora.unregister")(FakeCtx("sess-bot1"))
    assert schema_registry.get("echo2") is None


@pytest.mark.asyncio
async def test_register_bot_revalidation_failure_preserves_old_schema_ref(bot_app):
    """BUG1 — 재등록이 검증 실패하면 옛 봇의 스키마 ref가 보존되어야 한다.
    옛 코드는 검증 전에 옛 ref를 해제해, 검증 실패 시 스키마가 잘못 해제됐다."""
    mcp, dispatcher, schema_registry = bot_app
    body = {"type": "object", "properties": {"msgtype": {"const": "job"}}}
    res1 = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("sess-botj"), instance_id="bot_j", description="d",
        bot_mode="handler", subscribe_schemas=["job"],
        schemas={"job": {"kind": "bot-task", "purpose": "p", "body": body}}))
    assert res1["status"] == "ok"
    assert schema_registry.get("job") is not None
    # 같은 봇이 검증 실패하는 재등록을 시도 (존재하지 않는 schema 구독)
    res2 = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("sess-botj"), instance_id="bot_j", description="d",
        bot_mode="handler", subscribe_schemas=["nonexistent_schema"]))
    assert "error" in res2
    # BUG1 수정: 옛 'job' 스키마 ref가 보존돼 schema가 살아있어야 한다
    assert schema_registry.get("job") is not None
    assert "bot_j" in schema_registry.refs_of("job")
