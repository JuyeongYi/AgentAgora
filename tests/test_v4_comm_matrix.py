import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES


def test_comm_matrix_error_codes_present():
    assert {"comm_denied", "comm_matrix_shape_mismatch",
            "comm_matrix_invalid_cell", "comm_matrix_invalid_pattern"} <= set(ERROR_MESSAGES)


def test_comm_denied_message_formats_from_and_to():
    e = AgoraError("comm_denied", from_="Coder1", to="Tester1")
    assert e.code == "comm_denied"
    assert "Coder1" in str(e) and "Tester1" in str(e)


from agent_agora.comm_matrix import CommMatrix, load_comm_matrix

_HUB = "\n".join([
    "Inst1,Coder1,Reviewer1,Tester1",
    "0,1,1,1",
    "1,0,0,0",
    "1,0,0,0",
    "1,0,0,0",
])


_WEIGHTED = "\n".join([
    "Inst1,Coder1,Reviewer1,Tester1",
    "0,3,3,3",
    "10,0,0,0",
    "10,0,0,0",
    "10,0,0,0",
])


def test_load_csv_parses_integer_weights():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    assert cm.weight_of("Coder1", "Inst1") == 3
    assert cm.weight_of("Inst1", "Coder1") == 10
    assert cm.weight_of("Coder1", "Coder1") == 0


def test_weight_of_inactive_matrix_is_zero():
    cm = CommMatrix()
    assert cm.weight_of("anyone", "anyone_else") == 0


def test_weight_of_unlisted_pair_is_zero():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    assert cm.weight_of("Ghost", "Inst1") == 0
    assert cm.weight_of("Inst1", "Ghost") == 0


def test_is_allowed_equals_weight_positive():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    assert cm.is_allowed("Coder1", "Inst1") is True   # weight 3
    assert cm.is_allowed("Coder1", "Coder1") is False  # weight 0


def test_zero_one_csv_still_works():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.weight_of("Coder1", "Inst1") == 1
    assert cm.is_allowed("Coder1", "Inst1") is True
    assert cm.is_allowed("Inst1", "Inst1") is False


def test_load_csv_rejects_negative_cell():
    cm = CommMatrix()
    with pytest.raises(AgoraError) as ei:
        cm.load_csv("A,B\n0,-1\n1,0")
    assert ei.value.code == "comm_matrix_invalid_cell"


def test_load_csv_rejects_noninteger_cell():
    cm = CommMatrix()
    with pytest.raises(AgoraError) as ei:
        cm.load_csv("A,B\n0,x\n1,0")
    assert ei.value.code == "comm_matrix_invalid_cell"


def test_snapshot_returns_weight_map():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    snap = cm.snapshot()
    assert snap["Inst1"] == {"Inst1": 0, "Coder1": 3, "Reviewer1": 3, "Tester1": 3}
    assert snap["Coder1"] == {"Inst1": 10, "Coder1": 0, "Reviewer1": 0, "Tester1": 0}


def test_fresh_matrix_is_inactive_and_allows_all():
    cm = CommMatrix()
    assert cm.active is False
    assert cm.is_allowed("anyone", "anyone_else") is True


def test_load_csv_activates_and_enforces_hub_and_spoke():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.active is True
    assert cm.is_allowed("Coder1", "Inst1") is True
    assert cm.is_allowed("Inst1", "Inst1") is False
    assert cm.is_allowed("Inst1", "Coder1") is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False
    assert cm.is_allowed("Tester1", "Coder1") is False


def test_unregistered_worker_is_denied():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.is_allowed("Ghost", "Inst1") is False
    assert cm.is_allowed("Inst1", "Ghost") is False


def test_load_csv_rejects_row_count_mismatch():
    cm = CommMatrix()
    bad = "A,B,C\n0,1,1\n1,0,0"
    with pytest.raises(AgoraError) as ei:
        cm.load_csv(bad)
    assert ei.value.code == "comm_matrix_shape_mismatch"


def test_load_csv_rejects_column_count_mismatch():
    cm = CommMatrix()
    bad = "A,B,C\n0,1,1\n1,0\n1,0,0"
    with pytest.raises(AgoraError) as ei:
        cm.load_csv(bad)
    assert ei.value.code == "comm_matrix_shape_mismatch"


def test_load_csv_replaces_prior_matrix_in_place():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    cm.load_csv("A,B\n1,1\n1,1")
    assert cm.is_allowed("A", "B") is True
    assert cm.is_allowed("Coder1", "Inst1") is False


def test_snapshot_inactive_is_empty():
    assert CommMatrix().snapshot() == {}


def test_load_comm_matrix_absent_file_returns_inactive(tmp_path):
    cm = load_comm_matrix(tmp_path / "comm-matrix.csv")
    assert cm.active is False
    assert cm.is_allowed("x", "y") is True


def test_load_comm_matrix_present_file_loads(tmp_path):
    p = tmp_path / "comm-matrix.csv"
    p.write_text(_HUB, encoding="utf-8")
    cm = load_comm_matrix(p)
    assert cm.active is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False


from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.bot_registry import BotRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from _helpers import make_schema_registry, tany, get_tool as _tool, FakeCtx as _FakeCtx


async def _make_dispatcher(tmp_path, comm_matrix):
    registry = InstanceRegistry()
    for name in ("Inst1", "Coder1", "Reviewer1", "Tester1"):
        registry.register(f"sess-{name}", name)
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    return registry, persistence, queue


@pytest.mark.asyncio
async def test_dispatch_denied_pair_raises_comm_denied(tmp_path):
    cm = CommMatrix()
    cm.load_csv(_HUB)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        with pytest.raises(AgoraError) as ei:
            await d.dispatch(source="Coder1", target="Reviewer1", payload=tany(m=1))
        assert ei.value.code == "comm_denied"


@pytest.mark.asyncio
async def test_dispatch_allowed_pair_passes(tmp_path):
    cm = CommMatrix()
    cm.load_csv(_HUB)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        res = await d.dispatch(source="Coder1", target="Inst1", payload=tany(m=1))
        assert res["command_id"]
        drained = await d.flush("Inst1")
        assert len(drained) == 1


@pytest.mark.asyncio
async def test_dispatch_inactive_matrix_allows_all(tmp_path):
    cm = CommMatrix()  # inactive
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        res = await d.dispatch(source="Coder1", target="Reviewer1", payload=tany(m=1))
        assert res["command_id"]


@pytest.mark.asyncio
async def test_broadcast_filters_denied_targets_and_reports(tmp_path):
    cm = CommMatrix()
    cm.load_csv(_HUB)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        # Inst1 broadcasts — hub -> all spokes is allowed
        res1 = await d.broadcast(source="Inst1", payload=tany(m=1))
        assert res1["denied"] == []
        delivered = {x["instance_id"] for x in res1["dispatched_to"]}
        assert delivered == {"Coder1", "Reviewer1", "Tester1"}
        # Coder1 broadcasts — only Coder1 -> Inst1 allowed; spokes denied
        res2 = await d.broadcast(source="Coder1", payload=tany(m=2))
        assert {x["instance_id"] for x in res2["dispatched_to"]} == {"Inst1"}
        assert sorted(res2["denied"]) == ["Reviewer1", "Tester1"]


@pytest.mark.asyncio
async def test_broadcast_inactive_matrix_denied_empty(tmp_path):
    cm = CommMatrix()  # inactive
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        res = await d.broadcast(source="Coder1", payload=tany(m=1))
        assert res["denied"] == []
        assert {x["instance_id"] for x in res["dispatched_to"]} == {"Inst1", "Reviewer1", "Tester1"}


import json
from agent_agora.server import create_agora_app




@pytest.fixture
async def cm_app(tmp_path):
    instance_registry = InstanceRegistry()
    for name in ("Inst1", "Coder1", "Reviewer1", "Tester1"):
        instance_registry.register(f"sess-{name}", name)
    bot_registry = BotRegistry()
    comm_matrix = CommMatrix()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, default_timeout_ms=200)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, persistence=persistence,
            dispatcher=dispatcher, port=0)
        yield mcp, dispatcher, comm_matrix


@pytest.mark.asyncio
async def test_no_file_means_all_allow(tmp_path):
    """comm-matrix.csv가 없으면 ACL 비활성 — 모든 worker↔worker dispatch 허용."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp = _build_app(agora_dir=agora_dir, port=0)
    assert mcp._agora_comm_matrix.active is False


@pytest.mark.asyncio
async def test_startup_loads_comm_matrix_file(tmp_path):
    """서버 시작 시 .agentagora/comm-matrix.csv가 있으면 ACL 활성."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    (agora_dir / "comm-matrix.csv").write_text(_HUB, encoding="utf-8")
    mcp = _build_app(agora_dir=agora_dir, port=0)
    cm = mcp._agora_comm_matrix
    assert cm.active is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False


@pytest.mark.asyncio
async def test_hub_and_spoke_enforced_end_to_end(cm_app):
    """hub-and-spoke: 워커는 hub에만 회신, 워커끼리 직접 dispatch 차단."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv(_HUB)
    r1 = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(m=1), target="Tester1"))
    assert "comm_denied" in r1["error"]
    r2 = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(m=1), target="Inst1"))
    assert r2["status"] == "ok"


@pytest.mark.asyncio
async def test_unregistered_worker_denied(cm_app):
    """CSV 미등재 워커는 from/to 모두 거부 (strict whitelist)."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv("Inst1,Coder1\n0,1\n1,0")
    r = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Inst1"), payload=tany(m=1), target="Reviewer1"))
    assert "comm_denied" in r["error"]


@pytest.mark.asyncio
async def test_broadcast_partial_filter_through_tool(cm_app):
    """agora.broadcast도 매트릭스 필터 — denied 목록 보고."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv(_HUB)
    res = json.loads(await _tool(mcp, "agora.broadcast")(
        _FakeCtx("sess-Coder1"), payload=tany(m=1)))
    assert res["status"] == "ok"
    assert sorted(res["denied"]) == ["Reviewer1", "Tester1"]


_W_INST1 = "Inst1,Coder1,Reviewer1,Tester1\n0,1,5,1\n1,0,0,0\n1,0,0,0\n1,0,0,0"


@pytest.mark.asyncio
async def test_flush_priority_orders_by_edge_weight(tmp_path):
    """flush sort=priority — 큰 weight 엣지의 메시지가 먼저."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)  # Coder1->Inst1 weight 1, Reviewer1->Inst1 weight 5
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1", payload=tany(s="w1"))
        await d.dispatch(source="Reviewer1", target="Inst1", payload=tany(s="w5"))
        drained = await d.flush("Inst1", sort="priority")
        assert [c["payload"]["s"] for c in drained] == ["w5", "w1"]


@pytest.mark.asyncio
async def test_flush_edge_weight_beats_message_priority(tmp_path):
    """weight가 1차 키 — 큰 weight low가 작은 weight high보다 먼저."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1",
                         payload=tany(s="w1-high"), priority="high")
        await d.dispatch(source="Reviewer1", target="Inst1",
                         payload=tany(s="w5-low"), priority="low")
        drained = await d.flush("Inst1", sort="priority")
        assert [c["payload"]["s"] for c in drained] == ["w5-low", "w1-high"]


@pytest.mark.asyncio
async def test_flush_same_weight_orders_by_message_priority(tmp_path):
    """같은 weight 엣지 내에서는 메시지 priority가 2차 키."""
    cm = CommMatrix()
    # Coder1->Inst1, Reviewer1->Inst1 둘 다 weight 5
    cm.load_csv("Inst1,Coder1,Reviewer1,Tester1\n0,5,5,1\n1,0,0,0\n1,0,0,0\n1,0,0,0")
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1",
                         payload=tany(s="low"), priority="low")
        await d.dispatch(source="Reviewer1", target="Inst1",
                         payload=tany(s="high"), priority="high")
        drained = await d.flush("Inst1", sort="priority")
        assert [c["payload"]["s"] for c in drained] == ["high", "low"]


@pytest.mark.asyncio
async def test_flush_default_sort_is_priority(tmp_path):
    """flush() sort 미지정 기본값이 priority — weight 큰 메시지 먼저."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1", payload=tany(s="w1"))
        await d.dispatch(source="Reviewer1", target="Inst1", payload=tany(s="w5"))
        drained = await d.flush("Inst1")  # sort 미지정 → 기본 priority
        assert [c["payload"]["s"] for c in drained] == ["w5", "w1"]


@pytest.mark.asyncio
async def test_flush_fifo_ignores_weight(tmp_path):
    """sort=fifo escape hatch — weight 무시, created_at 순."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1", payload=tany(s="first"))
        await d.dispatch(source="Reviewer1", target="Inst1", payload=tany(s="second"))
        drained = await d.flush("Inst1", sort="fifo")
        assert [c["payload"]["s"] for c in drained] == ["first", "second"]


_REGEX_GROUP = "hub,coder-.*\n0,3\n7,0"


def test_regex_header_matches_group():
    cm = CommMatrix()
    cm.load_csv(_REGEX_GROUP)
    # coder-.* 행/열은 coder-N 전체에 fullmatch
    assert cm.weight_of("coder-1", "hub") == 3
    assert cm.weight_of("coder-2", "hub") == 3
    assert cm.weight_of("hub", "coder-9") == 7


def test_regex_fullmatch_not_partial():
    cm = CommMatrix()
    cm.load_csv(_REGEX_GROUP)
    # 'decoder'는 coder-.* 그룹이 아님 (fullmatch — 부분 매칭 안 함)
    assert cm.weight_of("decoder", "hub") == 0


def test_dotstar_catch_all_column():
    cm = CommMatrix()
    # 행 .*(catch-all), hub / 데이터: to=.* 행 전부 0, to=hub 행 from=.* 열 5
    cm.load_csv(".*,hub\n0,0\n5,0")
    # 미등재 from은 '.*' from-열을 통해 hub에 도달
    assert cm.weight_of("ghost", "hub") == 5
    assert cm.weight_of("anyone", "hub") == 5


def test_multi_match_takes_max_weight():
    cm = CommMatrix()
    # 명시적 coder-1 to-행은 전부 0, 넓은 coder-.* to-행은 8
    cm.load_csv("coder-1,coder-.*\n0,0\n8,8")
    # coder-1은 두 행 모두에 매칭 — 높은 weight(8)가 이긴다
    assert cm.weight_of("coder-1", "coder-1") == 8


def test_load_csv_rejects_invalid_regex_header():
    cm = CommMatrix()
    with pytest.raises(AgoraError) as ei:
        cm.load_csv("A,*\n0,0\n0,0")
    assert ei.value.code == "comm_matrix_invalid_pattern"


def test_no_star_csv_stays_strict_whitelist():
    cm = CommMatrix()
    cm.load_csv("Inst1,Coder1\n0,1\n1,0")  # '*' 없음
    assert cm.weight_of("Ghost", "Inst1") == 0
    assert cm.is_allowed("Ghost", "Inst1") is False
    assert cm.is_allowed("Inst1", "Ghost") is False


@pytest.mark.asyncio
async def test_flush_tool_default_sort_is_priority(cm_app):
    """agora.flush 도구의 sort 기본값이 priority — weight 큰 메시지 먼저."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv(
        "Inst1,Coder1,Reviewer1,Tester1\n0,1,5,1\n1,0,0,0\n1,0,0,0\n1,0,0,0")
    await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Coder1"), payload=tany(s="w1"), target="Inst1")
    await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(s="w5"), target="Inst1")
    res = json.loads(await _tool(mcp, "agora.flush")(_FakeCtx("sess-Inst1")))
    assert [c["payload"]["s"] for c in res["commands"]] == ["w5", "w1"]
