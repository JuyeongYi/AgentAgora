import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES


def test_comm_matrix_error_codes_present():
    assert {"comm_denied", "comm_matrix_shape_mismatch"} <= set(ERROR_MESSAGES)


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
from _helpers import make_schema_registry, tany


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
        drained = await d.wait("Inst1", timeout_ms=200)
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
