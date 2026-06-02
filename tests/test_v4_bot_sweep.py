"""dead_bot_sweep — BotRegistry TTL 정리 테스트."""
from __future__ import annotations

import dataclasses
import datetime

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
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
        yield bot_registry, dispatcher


@pytest.mark.asyncio
async def test_stale_bot_is_swept_and_subscriptions_detached(setup):
    bot_registry, dispatcher = setup
    bot_registry.register(session_id="bs1", instance_id="bot_a", description="d",
                          bot_mode="handler", subscribe_schemas=["pytest_run"])
    reg_at = datetime.datetime.fromisoformat(
        bot_registry.resolve_instance_id("bot_a").registered_at)
    future = reg_at + datetime.timedelta(milliseconds=TIMEOUT_MS + 1000)
    swept = dispatcher.sweeper.dead_bot_sweep(now=future)
    assert swept == ["bot_a"]
    assert bot_registry.is_bot("bot_a") is False
    assert bot_registry.subscribers_of("pytest_run") == set()


@pytest.mark.asyncio
async def test_healthy_bot_is_preserved(setup):
    bot_registry, dispatcher = setup
    bot_registry.register(session_id="bs1", instance_id="bot_a", description="d",
                          bot_mode="handler", subscribe_schemas=["pytest_run"])
    reg_at = datetime.datetime.fromisoformat(
        bot_registry.resolve_instance_id("bot_a").registered_at)
    swept = dispatcher.sweeper.dead_bot_sweep(now=reg_at + datetime.timedelta(seconds=1))
    assert swept == []
    assert bot_registry.is_bot("bot_a") is True


@pytest.mark.asyncio
async def test_never_waited_bot_uses_registered_at_fallback(setup):
    bot_registry, dispatcher = setup
    info = bot_registry.register(session_id="bs1", instance_id="bot_a",
                                 description="d", bot_mode="handler",
                                 subscribe_schemas=["pytest_run"])
    assert info.last_seen_at is None  # wait 한 번도 안 함
    reg_at = datetime.datetime.fromisoformat(info.registered_at)
    future = reg_at + datetime.timedelta(milliseconds=TIMEOUT_MS + 1000)
    # last_seen_at=None이어도 crash 없이 registered_at으로 판정
    swept = dispatcher.sweeper.dead_bot_sweep(now=future)
    assert swept == ["bot_a"]


@pytest.mark.asyncio
async def test_recent_last_seen_overrides_old_registered_at(setup):
    bot_registry, dispatcher = setup
    bot_registry.register(session_id="bs1", instance_id="bot_a", description="d",
                          bot_mode="handler", subscribe_schemas=["pytest_run"])
    base = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
    old = (base - datetime.timedelta(hours=2)).isoformat()       # registered_at
    fresh = (base - datetime.timedelta(minutes=1)).isoformat()   # last_seen_at
    info = bot_registry._by_instance["bot_a"]
    updated = dataclasses.replace(info, registered_at=old, last_seen_at=fresh)
    bot_registry._by_instance["bot_a"] = updated
    bot_registry._by_session[updated.session_id] = updated
    # registered_at(2시간 전)만 보면 스윕될 시점 — last_seen(1분 전)이 우선
    swept = dispatcher.sweeper.dead_bot_sweep(now=base)
    assert swept == []
    assert bot_registry.is_bot("bot_a") is True
