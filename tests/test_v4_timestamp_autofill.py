"""스키마가 선언한 timestamp 필드(ts/timestamp)를 dispatch 시 서버가 자동 채운다."""
import pytest

from agent_agora.registry import BotRegistry, InstanceRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from _helpers import make_schema_registry


def _registry() -> InstanceRegistry:
    reg = InstanceRegistry()
    for i in range(1, 4):
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
            bot_registry=BotRegistry(), comm_matrix=CommMatrix(),
            default_timeout_ms=60000)


@pytest.mark.asyncio
async def test_ts_autofilled_when_schema_declares_and_missing(disp):
    """worker_freeform은 ts가 required — 보내는 쪽이 생략해도 서버가 채워 통과·전달된다."""
    r = await disp.dispatch(
        source="Inst1", target="Inst2",
        payload={"msgtype": "worker_freeform", "type": "task",
                 "from": "Inst1", "message": "hi"})  # ts 생략
    assert "command_id" in r
    inbox = await disp.flush(instance_id="Inst2")
    msg = next(m for m in inbox if m["payload"].get("msgtype") == "worker_freeform")
    assert "ts" in msg["payload"] and msg["payload"]["ts"]


@pytest.mark.asyncio
async def test_sender_provided_ts_preserved(disp):
    explicit = "2020-01-02T03:04:05+00:00"
    await disp.dispatch(
        source="Inst1", target="Inst2",
        payload={"msgtype": "worker_freeform", "type": "task",
                 "from": "Inst1", "message": "hi", "ts": explicit})
    inbox = await disp.flush(instance_id="Inst2")
    msg = next(m for m in inbox if m["payload"].get("msgtype") == "worker_freeform")
    assert msg["payload"]["ts"] == explicit  # 덮어쓰지 않음


@pytest.mark.asyncio
async def test_timestamp_field_autofilled_for_default_schema(disp):
    """default 스키마는 timestamp(ts 아님) required — 그 필드명으로 채운다."""
    await disp.dispatch(
        source="Inst1", target="Inst2",
        payload={"msgtype": "default", "level": "info", "msg": "x", "category": "c"})
    inbox = await disp.flush(instance_id="Inst2")
    msg = next(m for m in inbox if m["payload"].get("msgtype") == "default")
    assert "timestamp" in msg["payload"] and msg["payload"]["timestamp"]


@pytest.mark.asyncio
async def test_from_autofilled_with_source(disp):
    """worker_freeform은 from이 required — 생략하면 서버가 dispatch source로 채운다."""
    await disp.dispatch(
        source="Inst1", target="Inst2",
        payload={"msgtype": "worker_freeform", "type": "task", "message": "hi"})  # from 생략
    inbox = await disp.flush(instance_id="Inst2")
    msg = next(m for m in inbox if m["payload"].get("msgtype") == "worker_freeform")
    assert msg["payload"]["from"] == "Inst1"


@pytest.mark.asyncio
async def test_sender_provided_from_preserved(disp):
    await disp.dispatch(
        source="Inst1", target="Inst2",
        payload={"msgtype": "worker_freeform", "type": "task", "message": "hi", "from": "custom"})
    inbox = await disp.flush(instance_id="Inst2")
    msg = next(m for m in inbox if m["payload"].get("msgtype") == "worker_freeform")
    assert msg["payload"]["from"] == "custom"  # 덮지 않음


@pytest.mark.asyncio
async def test_schema_without_ts_field_untouched(disp):
    """ts/timestamp를 선언 안 한 스키마(test_any)는 주입하지 않는다(검증 안전)."""
    await disp.dispatch(
        source="Inst1", target="Inst2",
        payload={"msgtype": "test_any", "text": "x"})
    inbox = await disp.flush(instance_id="Inst2")
    msg = next(m for m in inbox if m["payload"].get("msgtype") == "test_any")
    assert "ts" not in msg["payload"] and "timestamp" not in msg["payload"]
