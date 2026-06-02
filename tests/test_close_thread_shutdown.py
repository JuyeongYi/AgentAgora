"""Wave 1 — bugfix: agora.close_thread must catch DispatcherClosed like its siblings.

During shutdown, dispatcher.close_thread() dispatches a 'closing' message to the
other primary participants; that inner dispatch raises DispatcherClosed, which the
close_thread tool handler did NOT catch (it only caught ValueError) — so an
unhandled exception escaped. Every sibling tool (dispatch / broadcast / bot_emit /
flush / ...) returns a 'server is shutting down' sentinel instead. This pins the
symmetric behaviour.

The bug only triggers when there IS another delivered primary participant (the
`others` list is non-empty), so the conversation is established first.
"""
import json

import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.server import create_agora_app
from _helpers import make_schema_registry, tany, get_tool as _tool, FakeCtx as _FakeCtx


@pytest.fixture
async def app(tmp_path):
    instance_registry = InstanceRegistry()
    for name in ("Inst1", "Coder1"):
        instance_registry.register(f"sess-{name}", name)
    bot_registry = BotRegistry()
    comm_matrix = CommMatrix()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, default_timeout_ms=200)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, persistence=persistence,
            dispatcher=dispatcher, port=0)
        yield mcp, dispatcher


@pytest.mark.asyncio
async def test_close_thread_returns_shutting_down_when_dispatcher_closed(app):
    mcp, dispatcher = app
    # establish a conversation so close_thread has another delivered primary participant
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Inst1"), payload=tany(m=1), target="Coder1"))
    assert res["status"] == "ok"
    conv_id = res["conversation_id"]

    dispatcher._closed = True  # simulate shutdown in progress

    # Must not raise an unhandled DispatcherClosed; returns the sibling sentinel.
    out = json.loads(await _tool(mcp, "agora.close_thread")(
        _FakeCtx("sess-Inst1"), conversation_id=conv_id))
    assert out == {"error": "server is shutting down"}
