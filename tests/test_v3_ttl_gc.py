"""M2 — Background sweep tests with deterministic fixed-clock injection."""
from __future__ import annotations

import datetime

import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            default_timeout_ms=500,
            close_timeout_ms=300_000,
            dead_session_timeout_ms=1_800_000,
            gc_retention_days=90,
        )
        yield registry, persistence, dispatcher


# ------------------------------ close TTL ------------------------------

@pytest.mark.asyncio
async def test_close_ttl_sweep_transitions_half_closed_to_closed_after_timeout(setup):
    _, _, dispatcher = setup
    conv = "conv-ttl-1"
    # only Inst1 sends closing → half_closed
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1),
                               conversation_id=conv, closing=True)
    assert dispatcher.conversation_status(conv)["status"] == "half_closed"
    # sweep at t = last_message_at + close_timeout + 1s → should close
    last = datetime.datetime.fromisoformat(
        dispatcher.conversation_status(conv)["last_message_at"]
    )
    future = last + datetime.timedelta(milliseconds=300_001)
    closed_ids = dispatcher.close_ttl_sweep(now=future)
    assert conv in closed_ids
    assert dispatcher.conversation_status(conv)["status"] == "closed"


@pytest.mark.asyncio
async def test_close_ttl_sweep_resets_on_new_message_within_window(setup):
    _, _, dispatcher = setup
    conv = "conv-ttl-2"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1),
                               conversation_id=conv, closing=True)
    # new message arrives → resets last_message_at
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(x=2),
                               conversation_id=conv)
    last = datetime.datetime.fromisoformat(
        dispatcher.conversation_status(conv)["last_message_at"]
    )
    # sweep slightly past first close but before reset+timeout
    future = last + datetime.timedelta(milliseconds=100_000)
    closed_ids = dispatcher.close_ttl_sweep(now=future)
    assert conv not in closed_ids
    assert dispatcher.conversation_status(conv)["status"] == "half_closed"


@pytest.mark.asyncio
async def test_close_ttl_sweep_ignores_open_conversations(setup):
    _, _, dispatcher = setup
    conv = "conv-ttl-open"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1),
                               conversation_id=conv)
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    closed_ids = dispatcher.close_ttl_sweep(now=future)
    assert conv not in closed_ids
    assert dispatcher.conversation_status(conv)["status"] == "open"


# ------------------------- dead-session GC ----------------------------

@pytest.mark.asyncio
async def test_dead_session_sweep_unregisters_idle_instance(setup):
    registry, _, dispatcher = setup
    # Force Inst3's last_seen_at into the past
    registry.touch_last_seen("Inst3")
    info = registry.resolve_instance_id("Inst3")
    last_seen = datetime.datetime.fromisoformat(info.last_seen_at)
    future = last_seen + datetime.timedelta(milliseconds=1_800_001)
    removed = dispatcher.dead_session_sweep(now=future)
    assert "Inst3" in removed
    from agent_agora.registry import NotRegisteredError
    with pytest.raises(NotRegisteredError):
        registry.resolve_instance_id("Inst3")


@pytest.mark.asyncio
async def test_dead_session_sweep_skips_recent_instances(setup):
    registry, _, dispatcher = setup
    registry.touch_last_seen("Inst3")
    # sweep right now — well within timeout
    removed = dispatcher.dead_session_sweep(now=datetime.datetime.now(datetime.timezone.utc))
    assert "Inst3" not in removed
    # Inst3 still registered
    info = registry.resolve_instance_id("Inst3")
    assert info.instance_id == "Inst3"


# ------------------------- message GC ----------------------------

@pytest.mark.asyncio
async def test_message_gc_sweep_deletes_old_closed_messages_preserves_meta(setup):
    _, persistence, dispatcher = setup
    conv = "conv-gc-1"
    # create + close + age beyond retention
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(old=1),
                               conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(old=2),
                               conversation_id=conv, closing=True)
    assert dispatcher.conversation_status(conv)["status"] == "closed"
    # mock closed_at to far past via direct SQLite
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=91)).isoformat()
    persistence.conn.execute(
        "UPDATE conversations SET closed_at=? WHERE conversation_id=?",
        (past, conv),
    )
    # also age in-memory state for cache eviction
    dispatcher._conversations[conv]["closed_at"] = past
    deleted = dispatcher.message_gc_sweep(now=datetime.datetime.now(datetime.timezone.utc))
    assert deleted >= 2
    msgs_left = persistence.conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conv,)
    ).fetchone()[0]
    assert msgs_left == 0
    # conversation meta preserved
    conv_left = persistence.conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE conversation_id=?", (conv,)
    ).fetchone()[0]
    assert conv_left == 1


@pytest.mark.asyncio
async def test_message_gc_sweep_evicts_in_memory_cache(setup):
    _, persistence, dispatcher = setup
    conv = "conv-gc-cache"
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1),
                                     conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(m=2),
                               conversation_id=conv, closing=True)
    cmd_id = res["command_id"]
    assert conv in dispatcher._conversations
    assert cmd_id in dispatcher._conversation_of
    # age beyond retention
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=91)).isoformat()
    persistence.conn.execute(
        "UPDATE conversations SET closed_at=? WHERE conversation_id=?",
        (past, conv),
    )
    dispatcher._conversations[conv]["closed_at"] = past
    dispatcher.message_gc_sweep(now=datetime.datetime.now(datetime.timezone.utc))
    # Inst4 우려4 — cache eviction
    assert conv not in dispatcher._conversations
    assert cmd_id not in dispatcher._conversation_of


@pytest.mark.asyncio
async def test_message_gc_sweep_skips_recently_closed(setup):
    _, _, dispatcher = setup
    conv = "conv-gc-recent"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1),
                               conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(m=2),
                               conversation_id=conv, closing=True)
    # closed_at is now — well within 90d
    deleted = dispatcher.message_gc_sweep(now=datetime.datetime.now(datetime.timezone.utc))
    assert deleted == 0
    assert conv in dispatcher._conversations
