"""Plan B TD4 — sweeper.vacuum() 일일 GC 통합."""
import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
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
            default_timeout_ms=500)


@pytest.mark.asyncio
async def test_vacuum_runs_after_gc_without_error(disp):
    await disp.dispatch(source="Inst1", target="Inst2", payload=tany(text="x"))
    # 일일 GC 루프 순서 재현: message_gc_sweep → vacuum
    disp.sweeper.message_gc_sweep()
    disp.sweeper.vacuum()  # 예외 없이 완료
    # DB가 이후에도 정상 동작
    inbox = await disp.flush(instance_id="Inst2")
    assert any(m["payload"].get("text") == "x" for m in inbox)
