"""Plan A1 — deadline 안전망 테스트."""
import datetime

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


def _registry() -> InstanceRegistry:
    reg = InstanceRegistry()
    for i in range(1, 5):
        reg.register(f"sess-{i}", f"Inst{i}")
    return reg


@pytest.fixture
async def disp(tmp_path):
    registry = _registry()
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


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_expect_result_gets_default_deadline(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True)
    cmd = r["command_id"]
    assert cmd in disp._deadlines
    dl = datetime.datetime.fromisoformat(disp._deadlines[cmd])
    created = datetime.datetime.fromisoformat(r["created_at"])
    assert 55 <= (dl - created).total_seconds() <= 65


@pytest.mark.asyncio
async def test_explicit_deadline_is_respected(disp):
    explicit = "2030-01-01T00:00:00+00:00"
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True,
                            deadline_ts=explicit)
    assert disp._deadlines[r["command_id"]] == explicit


@pytest.mark.asyncio
async def test_deadline_hook_fires_on_expiry(disp):
    """register_deadline_hook 콜백이 만료 항목 {command_id,source,target}으로 호출된다
    (대시보드 SSE deadline_expired의 소스)."""
    captured: list = []
    disp.register_deadline_hook(lambda entry: captured.append(entry))
    r = await disp.dispatch(source="Inst1", target="Inst2", payload=tany(text="x"),
                            expect_result=True, deadline_ts="2000-01-01T00:00:00+00:00")
    cmd = r["command_id"]
    expired = await disp.expire_overdue_deadlines(now_iso=_now_iso())
    assert {"command_id": cmd, "source": "Inst1", "target": "Inst2"} in expired
    assert any(e["command_id"] == cmd and e["target"] == "Inst2" for e in captured)


@pytest.mark.asyncio
async def test_no_deadline_without_expect_result(disp):
    r = await disp.dispatch(source="Inst1", target="Inst2", payload=tany(text="x"))
    assert r["command_id"] not in disp._deadlines


@pytest.mark.asyncio
async def test_expire_injects_timeout_and_clears_inflight(disp):
    past = "2000-01-01T00:00:00+00:00"
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True,
                            deadline_ts=past)
    cmd = r["command_id"]
    expired = await disp.expire_overdue_deadlines(now_iso=_now_iso())
    assert cmd in [e["command_id"] for e in expired]
    inbox = await disp.flush(instance_id="Inst1")
    errs = [m for m in inbox if m["payload"].get("msgtype") == "agora.error"]
    assert errs and errs[0]["payload"]["error"] == "timeout"
    assert errs[0]["payload"]["command_id"] == cmd
    assert errs[0]["in_reply_to"] == cmd
    assert cmd not in disp._deadlines
    assert disp.in_flight_count("Inst2") == 0


@pytest.mark.asyncio
async def test_expire_noop_when_reply_already_cleared_inflight(disp):
    past = "2000-01-01T00:00:00+00:00"
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True,
                            deadline_ts=past)
    cmd = r["command_id"]
    # Inst2가 먼저 회신 → in_flight 해제
    await disp.dispatch(source="Inst2", target="Inst1",
                        payload=tany(text="done"), in_reply_to=cmd)
    expired = await disp.expire_overdue_deadlines(now_iso=_now_iso())
    assert cmd not in [e["command_id"] for e in expired]


@pytest.mark.asyncio
async def test_sweeper_deadline_sweep_delegates(disp):
    past = "2000-01-01T00:00:00+00:00"
    r = await disp.dispatch(source="Inst1", target="Inst2",
                            payload=tany(text="x"), expect_result=True,
                            deadline_ts=past)
    expired = await disp.sweeper.deadline_sweep()
    assert r["command_id"] in [e["command_id"] for e in expired]
    assert disp.in_flight_count("Inst2") == 0


@pytest.mark.asyncio
async def test_broadcast_deadline_per_target_independent(disp):
    past = "2000-01-01T00:00:00+00:00"
    r = await disp.broadcast(source="Inst1", payload=tany(text="x"),
                             expect_result=True, deadline_ts=past)
    cmd = r["command_id"]
    assert cmd in disp._deadlines
    expired = await disp.expire_overdue_deadlines(now_iso=_now_iso())
    # 모든 broadcast target이 만료된다
    targets = {e["target"] for e in expired if e["command_id"] == cmd}
    assert {"Inst2", "Inst3", "Inst4"} <= targets


@pytest.mark.asyncio
async def test_deadlines_restored_after_restart(tmp_path):
    registry = _registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    past = "2000-01-01T00:00:00+00:00"
    queue = AsyncWriteQueue(persistence)
    async with queue:
        d = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(), comm_matrix=CommMatrix(),
            default_timeout_ms=60000)
        r = await d.dispatch(source="Inst1", target="Inst2",
                             payload=tany(text="x"), expect_result=True,
                             deadline_ts=past)
        cmd = r["command_id"]
    # 재시작 — 새 dispatcher, 같은 persistence
    queue2 = AsyncWriteQueue(persistence)
    async with queue2:
        d2 = Dispatcher(
            registry, persistence, queue2,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(), comm_matrix=CommMatrix(),
            default_timeout_ms=60000)
        d2.restore_from_persistence()
        assert d2._deadlines.get(cmd) == past
