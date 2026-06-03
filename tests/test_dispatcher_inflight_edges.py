"""기능4 — dispatcher.in_flight_edges() 집계(플로우 뷰 백엔드)."""
import pytest

from agent_agora.registry import BotRegistry, InstanceRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from _helpers import make_schema_registry, tany


def _registry() -> InstanceRegistry:
    reg = InstanceRegistry()
    for i in range(1, 5):
        reg.register(f"sess-{i}", f"Inst{i}")
    return reg


@pytest.fixture
async def disp(tmp_path):
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        yield Dispatcher(
            _registry(), persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=60000)


@pytest.mark.asyncio
async def test_in_flight_edges_aggregates_and_clears_on_reply(disp):
    # expect_result dispatch → source→target 엣지 1건
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True)
    cmd = r["command_id"]
    edges = disp.in_flight_edges()
    assert {"source": "Inst1", "target": "Inst2", "count": 1} in edges

    # 같은 source→target 두 번째 dispatch → count 2
    await disp.dispatch(source="Inst1", target="Inst2",
                        payload=tany(text="y"), expect_result=True)
    edge = next(e for e in disp.in_flight_edges()
                if e["source"] == "Inst1" and e["target"] == "Inst2")
    assert edge["count"] == 2

    # Inst2가 첫 cmd에 회신 → 해당 엣지 count 감소
    await disp.dispatch(source="Inst2", target="Inst1",
                        payload=tany(text="done"), in_reply_to=cmd)
    edge2 = next((e for e in disp.in_flight_edges()
                  if e["source"] == "Inst1" and e["target"] == "Inst2"), None)
    assert edge2 is not None and edge2["count"] == 1


@pytest.mark.asyncio
async def test_no_expect_result_no_edge(disp):
    await disp.dispatch(source="Inst1", target="Inst2", payload=tany(text="x"))
    assert disp.in_flight_edges() == []


@pytest.mark.asyncio
async def test_broadcast_expect_result_creates_per_target_edges(disp):
    await disp.broadcast(source="Inst1", payload=tany(text="x"), expect_result=True)
    edges = disp.in_flight_edges()
    targets = {e["target"] for e in edges if e["source"] == "Inst1"}
    assert {"Inst2", "Inst3", "Inst4"} <= targets
    assert all(e["count"] >= 1 for e in edges)
