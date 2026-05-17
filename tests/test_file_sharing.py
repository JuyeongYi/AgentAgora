"""파일 공유 MCP 도구 테스트."""
from __future__ import annotations

import json

import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.file_policy import FilePolicy
from agent_agora.file_store import FileStore
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.server import create_agora_app
from _helpers import make_schema_registry


class _FakeCtx:
    def __init__(self, session_id):
        self.request_context = type("RC", (), {"request": type("R", (), {
            "headers": {"mcp-session-id": session_id}})()})()


def _tool(mcp, name):
    return mcp._tool_manager.get_tool(name).fn


@pytest.fixture
async def file_app(tmp_path):
    instance_registry = InstanceRegistry()
    for name in ("Inst1", "Inst2"):
        instance_registry.register(f"sess-{name}", name)
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
            comm_matrix=comm_matrix, default_timeout_ms=200)
        file_store = FileStore(tmp_path, persistence)
        file_policy = FilePolicy()
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, persistence=persistence,
            dispatcher=dispatcher, port=0, file_store=file_store,
            file_policy=file_policy)
        yield mcp, dispatcher, file_store, file_policy


@pytest.mark.asyncio
async def test_share_then_fetch(file_app, tmp_path):
    mcp, _, file_store, _ = file_app
    src = tmp_path / "doc.md"
    src.write_text("payload", encoding="utf-8")
    r = json.loads(await _tool(mcp, "agora.share_file")(
        _FakeCtx("sess-Inst1"), path=str(src)))
    assert r["status"] == "ok"
    fid = r["handle"]["file_id"]
    dest = tmp_path / "got.md"
    r2 = json.loads(await _tool(mcp, "agora.fetch_file")(
        _FakeCtx("sess-Inst2"), file_id=fid, dest_path=str(dest)))
    assert r2["status"] == "ok"
    assert dest.read_text(encoding="utf-8") == "payload"


@pytest.mark.asyncio
async def test_fetch_unknown_file(file_app, tmp_path):
    mcp, _, _, _ = file_app
    r = json.loads(await _tool(mcp, "agora.fetch_file")(
        _FakeCtx("sess-Inst2"), file_id="nope", dest_path=str(tmp_path / "x")))
    assert "unknown_file" in r["error"]


@pytest.mark.asyncio
async def test_share_file_upload_denied(file_app, tmp_path):
    mcp, _, _, file_policy = file_app
    file_policy.load_json(json.dumps({"workers": {"Inst1": {"r": ["*"], "w": ["*.md"]}}}))
    src = tmp_path / "evil.exe"
    src.write_bytes(b"x")
    r = json.loads(await _tool(mcp, "agora.share_file")(
        _FakeCtx("sess-Inst1"), path=str(src)))
    assert "file_upload_denied" in r["error"]


@pytest.mark.asyncio
async def test_fetch_file_download_denied(file_app, tmp_path):
    mcp, _, file_store, file_policy = file_app
    h = file_store.store_bytes(b"data", "app.py", "Inst1")
    file_policy.load_json(json.dumps({"workers": {"Inst2": {"r": ["*.md"], "w": []}}}))
    r = json.loads(await _tool(mcp, "agora.fetch_file")(
        _FakeCtx("sess-Inst2"), file_id=h["file_id"], dest_path=str(tmp_path / "x")))
    assert "file_download_denied" in r["error"]
