"""Sweeper — operator 면제 + 실행 통계 테스트."""
from __future__ import annotations

import dataclasses
import datetime

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry

TIMEOUT_MS = 1_800_000  # 30분 — Dispatcher 기본 dead_session_timeout_ms


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        bot_registry = BotRegistry()
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=bot_registry,
            comm_matrix=CommMatrix(),
            default_timeout_ms=500,
            dead_session_timeout_ms=TIMEOUT_MS,
        )
        yield registry, dispatcher


def _backdate_instance(reg: InstanceRegistry, instance_id: str, ts: str) -> None:
    """Test-only: directly mutate registry to backdate last_seen_at.

    Not thread-safe — bypasses InstanceRegistry._lock. OK for single-threaded
    test fixtures. Do NOT use in production code.
    """
    info = reg._by_instance[instance_id]
    updated = dataclasses.replace(info, last_seen_at=ts)
    reg._by_instance[instance_id] = updated
    reg._by_session[updated.session_id] = updated


@pytest.mark.asyncio
async def test_sweeper_skips_operator_instances(setup):
    """operator: 접두사 인스턴스는 last_seen이 아무리 오래 전이어도 GC 면제."""
    reg, dispatcher = setup

    # 운영자 pseudo-instance 등록 후 last_seen을 99999초 전으로 강제 설정
    reg.register(session_id="dashboard:alice", instance_id="operator:alice",
                 role="operator", description="op")
    reg.touch_last_seen("operator:alice")
    very_old = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(seconds=99999)).isoformat()
    _backdate_instance(reg, "operator:alice", very_old)

    # 일반 워커도 동일하게 만료 설정
    reg.register(session_id="s1", instance_id="Worker1",
                 role="coder", description="w")
    reg.touch_last_seen("Worker1")
    _backdate_instance(reg, "Worker1", very_old)

    # now=현재 시각으로 sweep — Worker1은 TTL 초과, operator:alice는 면제
    removed = dispatcher.sweeper.dead_session_sweep()
    assert "operator:alice" not in removed
    assert "Worker1" in removed

    # operator 인스턴스가 레지스트리에 여전히 존재해야 함
    assert reg.resolve_instance_id("operator:alice").instance_id == "operator:alice"


@pytest.mark.asyncio
async def test_sweeper_does_not_skip_normal_instances(setup):
    """operator: 접두사 없는 일반 인스턴스는 TTL 초과 시 정상 제거."""
    reg, dispatcher = setup

    reg.register(session_id="s2", instance_id="Planner1", role="planner")
    reg.touch_last_seen("Planner1")
    very_old = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(seconds=99999)).isoformat()
    _backdate_instance(reg, "Planner1", very_old)

    removed = dispatcher.sweeper.dead_session_sweep()
    assert "Planner1" in removed


@pytest.mark.asyncio
async def test_sweeper_exposes_run_stats_initial(setup):
    """Sweeper 생성 직후 dead_session_sweep_runs_total==0, dead_session_sweep_last_run_at==None."""
    _, dispatcher = setup
    assert dispatcher.sweeper.dead_session_sweep_runs_total == 0
    assert dispatcher.sweeper.dead_session_sweep_last_run_at is None


@pytest.mark.asyncio
async def test_sweeper_exposes_run_stats_after_sweep(setup):
    """dead_session_sweep() 한 번 호출 후 runs_total==1, last_run_at 설정됨."""
    _, dispatcher = setup
    dispatcher.sweeper.dead_session_sweep()
    assert dispatcher.sweeper.dead_session_sweep_runs_total == 1
    assert dispatcher.sweeper.dead_session_sweep_last_run_at is not None


@pytest.mark.asyncio
async def test_sweeper_run_stats_accumulate(setup):
    """여러 번 sweep 시 dead_session_sweep_runs_total이 누적된다."""
    _, dispatcher = setup
    dispatcher.sweeper.dead_session_sweep()
    dispatcher.sweeper.dead_session_sweep()
    dispatcher.sweeper.dead_session_sweep()
    assert dispatcher.sweeper.dead_session_sweep_runs_total == 3


@pytest.mark.asyncio
async def test_sweeper_last_run_at_is_float(setup):
    """dead_session_sweep_last_run_at은 time.time() 기반의 float 값이다."""
    _, dispatcher = setup
    dispatcher.sweeper.dead_session_sweep()
    assert isinstance(dispatcher.sweeper.dead_session_sweep_last_run_at, float)
    # 합리적인 범위: 2026-01-01 Unix timestamp보다 커야 함
    assert dispatcher.sweeper.dead_session_sweep_last_run_at > 1_735_689_600.0
