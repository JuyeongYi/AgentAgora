import pytest
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.errors import AgoraError
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
