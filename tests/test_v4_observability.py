"""Plan A2 — observability 도구 테스트 (transcript/coverage/reply/cancel)."""
import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.errors import AgoraError
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
            default_timeout_ms=60000)


# --- transcript ---

@pytest.mark.asyncio
async def test_transcript_time_ordered_and_since_filter(disp):
    r1 = await disp.dispatch(source="Inst1", target="Inst2", payload=tany(text="1"))
    conv = r1["conversation_id"]
    await disp.dispatch(source="Inst1", target="Inst2", payload=tany(text="2"),
                        conversation_id=conv)
    t = disp.transcript(conversation_id=conv)
    texts = [m["payload"]["text"] for m in t["messages"]]
    assert texts == ["1", "2"]
    t2 = disp.transcript(conversation_id=conv, since_ts=r1["created_at"])
    assert all(m["created_at"] > r1["created_at"] for m in t2["messages"])
    assert "as_of_ts" in t


# --- coverage ---

@pytest.mark.asyncio
async def test_coverage_responded_pending_expired(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True,
                            deadline_ts="2000-01-01T00:00:00+00:00")
    cmd = r["command_id"]
    cov = disp.coverage(cmd)
    assert cov["pending"] == ["Inst2"] and cov["responded"] == []
    assert cov["expired"] is True
    assert cov["deadline_ts"] == "2000-01-01T00:00:00+00:00"
    await disp.dispatch(source="Inst2", target="Inst1",
                        payload=tany(text="ok"), in_reply_to=cmd)
    cov2 = disp.coverage(cmd)
    assert "Inst2" in cov2["responded"] and cov2["pending"] == []


# --- reply ---

@pytest.mark.asyncio
async def test_reply_autofills_from_last_inbound(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="q"), expect_result=True)
    cmd = r["command_id"]
    conv = r["conversation_id"]
    await disp.flush(instance_id="Inst2")  # Inst2 수신 → _last_inbound 갱신
    rep = await disp.reply(caller="Inst2", payload=tany(text="a"))
    assert rep["conversation_id"] == conv
    inbox = await disp.flush(instance_id="Inst1")
    got = [m for m in inbox if m["payload"].get("text") == "a"]
    assert got and got[0]["in_reply_to"] == cmd
    assert disp.in_flight_count("Inst2") == 0


@pytest.mark.asyncio
async def test_reply_without_inbound_errors(disp):
    with pytest.raises(AgoraError):
        await disp.reply(caller="Inst1", payload=tany(text="x"))


# --- cancel ---

@pytest.mark.asyncio
async def test_cancel_recalls_unconsumed(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True)
    cmd = r["command_id"]
    res = await disp.cancel(caller="Inst1", command_id=cmd)
    assert res["cancelled"] == ["Inst2"]
    inbox = await disp.flush(instance_id="Inst2")
    assert all(m["id"] != cmd for m in inbox)
    assert disp.in_flight_count("Inst2") == 0


@pytest.mark.asyncio
async def test_cancel_already_consumed_is_noop(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True)
    cmd = r["command_id"]
    await disp.flush(instance_id="Inst2")  # 이미 소비
    res = await disp.cancel(caller="Inst1", command_id=cmd)
    assert res["already_consumed"] == ["Inst2"] and res["cancelled"] == []


@pytest.mark.asyncio
async def test_cancel_non_source_denied(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True)
    with pytest.raises(AgoraError):
        await disp.cancel(caller="Inst2", command_id=r["command_id"])
