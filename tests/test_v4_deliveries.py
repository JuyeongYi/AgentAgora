"""Plan A2 Task 2 — dispatch deliveries[] per-target 전달 상태 (TD2)."""
import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


@pytest.fixture
async def disp(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        yield Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=500, max_inbox_depth=1)


@pytest.mark.asyncio
async def test_deliveries_marks_skipped_full(disp):
    # Inst3 인박스를 채워 cc 전달 실패 유도 (max_inbox_depth=1)
    await disp.dispatch(source="Inst1", target="Inst3", payload=tany(text="fill"))
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), cc=["Inst3"])
    by = {e["target"]: e for e in r["deliveries"]}
    assert by["Inst2"]["status"] == "delivered" and by["Inst2"]["role"] == "primary"
    assert by["Inst3"]["status"] == "skipped_full" and by["Inst3"]["role"] == "cc"
    # 하위호환 필드 병존
    assert "dispatched_to" in r and "skipped_full" in r
