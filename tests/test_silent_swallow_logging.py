"""Wave 1 — observability: previously-silent except-swallow paths must log.

RED-first per TDD. Covers:
  - persistence.py decode fallbacks (fetch_messages_for / fetch_transcript)
  - AsyncWriteQueue transaction failure (incl. fire-and-forget, otherwise fully silent)
  - dispatcher flush / cancel drained_at UPDATE swallows
Behaviour is unchanged (raw fallback / best-effort swallow preserved); only a log
record is added so the failure is observable.
"""
from __future__ import annotations

import logging

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry


def _seed_corrupt_message(p, *, command_id, target, conversation_id, payload_raw):
    """Insert a message row whose payload column is NOT valid JSON."""
    p.conn.execute(
        "INSERT INTO conversations (conversation_id, status, started_at, last_message_at) "
        "VALUES (?, 'open', ?, ?)",
        (conversation_id, "2026-06-03T00:00:00+00:00", "2026-06-03T00:00:00+00:00"),
    )
    p.conn.execute(
        "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload) "
        "VALUES (?,?,?,?,?,?)",
        (command_id, target, conversation_id, "Inst1", "2026-06-03T00:00:00+00:00", payload_raw),
    )


def test_fetch_messages_for_logs_warning_on_corrupt_payload(tmp_path, caplog):
    p = Persistence(tmp_path / "a.db")
    p.migrate()
    _seed_corrupt_message(p, command_id="c1", target="Inst2",
                          conversation_id="conv1", payload_raw="NOT_JSON{")
    with caplog.at_level(logging.WARNING, logger="agent_agora.persistence"):
        out = p.fetch_messages_for(recipient="Inst2")
    assert out[0]["payload"] == "NOT_JSON{"  # raw fallback preserved
    assert any("c1" in r.getMessage() for r in caplog.records), \
        "corrupt payload decode should log a warning naming the message_id"


def test_fetch_transcript_logs_warning_on_corrupt_payload(tmp_path, caplog):
    p = Persistence(tmp_path / "a.db")
    p.migrate()
    _seed_corrupt_message(p, command_id="c2", target="Inst2",
                          conversation_id="conv2", payload_raw="ALSO}{BAD")
    with caplog.at_level(logging.WARNING, logger="agent_agora.persistence"):
        out = p.fetch_transcript("conv2")
    assert out[0]["payload"] == "ALSO}{BAD"  # raw fallback preserved
    assert any("c2" in r.getMessage() for r in caplog.records), \
        "corrupt payload decode in transcript should log a warning naming the command_id"


@pytest.mark.asyncio
async def test_write_queue_logs_failed_transaction(tmp_path, caplog):
    p = Persistence(tmp_path / "a.db")
    p.migrate()
    queue = AsyncWriteQueue(p)
    with caplog.at_level(logging.WARNING, logger="agent_agora.persistence"):
        async with queue:
            # fire-and-forget bad txn: failure is otherwise fully silent (future is None)
            await queue.submit_transaction(
                [("INSERT INTO nonexistent_table VALUES (1)", ())], wait=False)
        # __aexit__ drains the worker, so the bad txn has been processed by now
    assert any(r.levelno >= logging.WARNING for r in caplog.records), \
        "a failed async write transaction must not be swallowed silently"


def _register_pytest_schema(dispatcher):
    body = {
        "type": "object",
        "required": ["msgtype", "scenario"],
        "properties": {
            "msgtype": {"type": "string", "const": "pytest_run"},
            "scenario": {"type": "string"},
        },
        "additionalProperties": False,
    }
    dispatcher._schema_registry.register(
        "pytest_run", body, kind="bot-task", purpose="pytest 실행 요청")
    return {"msgtype": "pytest_run", "scenario": "smoke"}


@pytest.fixture
async def dispatcher_env(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 3):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=500)
        yield dispatcher


@pytest.mark.asyncio
async def test_flush_logs_warning_when_drained_update_fails(dispatcher_env, caplog, monkeypatch):
    dispatcher = dispatcher_env
    payload = _register_pytest_schema(dispatcher)
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=payload)

    async def boom(*a, **k):
        raise RuntimeError("write queue down")
    monkeypatch.setattr(dispatcher._write_queue, "submit_transaction", boom)

    with caplog.at_level(logging.WARNING, logger="agent_agora.dispatcher"):
        drained = await dispatcher.flush("Inst2")
    assert len(drained) == 1  # swallow preserved: flush still returns the drained message
    assert any(r.levelno >= logging.WARNING for r in caplog.records), \
        "a failed drained_at UPDATE on flush must not be swallowed silently"


@pytest.mark.asyncio
async def test_cancel_logs_warning_when_drained_update_fails(dispatcher_env, caplog, monkeypatch):
    dispatcher = dispatcher_env
    payload = _register_pytest_schema(dispatcher)
    res = await dispatcher.dispatch(source="Inst1", target="Inst2",
                                    payload=payload, expect_result=True)
    cmd_id = res["command_id"]

    async def boom(*a, **k):
        raise RuntimeError("write queue down")
    monkeypatch.setattr(dispatcher._write_queue, "submit_transaction", boom)

    with caplog.at_level(logging.WARNING, logger="agent_agora.dispatcher"):
        out = await dispatcher.cancel(caller="Inst1", command_id=cmd_id)
    assert out["cancelled"] == ["Inst2"]  # swallow preserved
    assert any(r.levelno >= logging.WARNING for r in caplog.records), \
        "a failed drained_at UPDATE on cancel must not be swallowed silently"
