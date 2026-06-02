"""Plan B TD3 — bot_emit(target) comm-matrix ACL 재검사 (opt-in)."""
import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.errors import AgoraError
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


def _setup(tmp_path):
    registry = InstanceRegistry()
    registry.register("s-w", "Worker1")
    persistence = Persistence(tmp_path / "a.db")
    persistence.migrate()
    cm = CommMatrix()
    # 활성 매트릭스. router_bot은 매트릭스에 미등재 → weight 0 → 재검사 시 denied.
    cm.load_csv("Worker1\n0")
    return registry, persistence, cm


@pytest.mark.asyncio
async def test_bot_emit_rechecks_acl_when_enabled(tmp_path):
    registry, persistence, cm = _setup(tmp_path)
    queue = AsyncWriteQueue(persistence)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       bot_emit_recheck_acl=True)
        d._bot_registry.register("s-b", "router_bot", description="d", bot_mode="observer")
        with pytest.raises(AgoraError):
            await d.bot_emit(source="router_bot", payload=tany(text="x"), target="Worker1")


@pytest.mark.asyncio
async def test_bot_emit_bypasses_acl_by_default(tmp_path):
    registry, persistence, cm = _setup(tmp_path)
    queue = AsyncWriteQueue(persistence)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm)  # default off
        d._bot_registry.register("s-b", "router_bot", description="d", bot_mode="observer")
        res = await d.bot_emit(source="router_bot", payload=tany(text="x"), target="Worker1")
        assert res["command_id"]
        # Worker1 인박스에 도착했다 (ACL 우회)
        inbox = await d.flush(instance_id="Worker1")
        assert any(m["payload"].get("text") == "x" for m in inbox)
