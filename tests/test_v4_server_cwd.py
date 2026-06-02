"""agora.instances / agora.find / agora.cwd — cwd 필드 노출 테스트."""
from __future__ import annotations

import json

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.server import create_agora_app
from _helpers import make_schema_registry, get_tool as _tool, FakeCtx as _FakeCtx


@pytest.fixture
async def app(tmp_path):
    instance_registry = InstanceRegistry()
    bot_registry = BotRegistry()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        comm_matrix = CommMatrix()
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix,
            default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix,
            persistence=persistence, dispatcher=dispatcher, port=0)
        yield mcp, instance_registry


# ---------------------------------------------------------------------------
# 1. agora.instances includes cwd field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_instances_includes_cwd(app):
    mcp, instance_registry = app
    instance_registry.register("sess-a", "WorkerA", cwd="/home/user/project")

    res = json.loads(await _tool(mcp, "agora.instances")())
    worker = next(
        (item for item in res["instances"] if item["instance_id"] == "WorkerA"),
        None,
    )
    assert worker is not None, "WorkerA not found in instances"
    assert worker["cwd"] == "/home/user/project"


# ---------------------------------------------------------------------------
# 2. agora.find worker result includes cwd field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_worker_includes_cwd(app):
    mcp, instance_registry = app
    instance_registry.register("sess-b", "SearchMe", cwd="C:/repos/my-app")

    res = json.loads(await _tool(mcp, "agora.find")("SearchMe"))
    worker = next(
        (r for r in res["results"] if r["instance_id"] == "SearchMe"),
        None,
    )
    assert worker is not None, "SearchMe not found in find results"
    assert worker["kind"] == "worker"
    assert worker["cwd"] == "C:/repos/my-app"


# ---------------------------------------------------------------------------
# 3. agora.cwd returns instance_id and cwd
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cwd_tool_returns_cwd(app):
    mcp, instance_registry = app
    instance_registry.register("sess-c", "CwdWorker", cwd="/workspace/foo")

    res = json.loads(await _tool(mcp, "agora.cwd")("CwdWorker"))
    assert res == {"instance_id": "CwdWorker", "cwd": "/workspace/foo"}


# ---------------------------------------------------------------------------
# 4. agora.cwd unregistered id → standard error shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cwd_tool_unregistered_returns_error(app):
    mcp, instance_registry = app

    res = json.loads(await _tool(mcp, "agora.cwd")("no-such-instance"))
    assert "error" in res


# ---------------------------------------------------------------------------
# 5. agora.cwd with no cwd registered → returns cwd: ""
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cwd_tool_no_cwd_returns_empty_string(app):
    mcp, instance_registry = app
    instance_registry.register("sess-d", "NoCwdWorker")  # no cwd kwarg

    res = json.loads(await _tool(mcp, "agora.cwd")("NoCwdWorker"))
    assert res == {"instance_id": "NoCwdWorker", "cwd": ""}


# ---------------------------------------------------------------------------
# 6. agora.register tool accepts a cwd argument (durability — set via tool)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_tool_accepts_and_returns_cwd(app):
    mcp, instance_registry = app

    res = json.loads(await _tool(mcp, "agora.register")(
        _FakeCtx("sess-reg-cwd"), instance_id="ToolCwd", cwd="/tool/set/path"))

    assert res["status"] == "ok"
    assert res["cwd"] == "/tool/set/path"
    assert instance_registry.resolve_session("sess-reg-cwd").cwd == "/tool/set/path"


# ---------------------------------------------------------------------------
# 7. session-unavailable path (single source: _session_or_error)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_without_session_returns_session_unavailable(app):
    """A ctx carrying no mcp-session-id resolves to the shared 'session
    unavailable' error via _session_or_error (consolidated across all tools)."""
    mcp, _ = app
    res = json.loads(await _tool(mcp, "agora.register")(_FakeCtx(None), instance_id="X"))
    assert "Session context unavailable" in res["error"]
