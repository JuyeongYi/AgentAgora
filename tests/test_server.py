# tests/test_server.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_agora.schema import SchemaRegistry
from agent_agora.server import create_agora_app
from agent_agora.store import AgoraStore, AsyncWriteQueue


@pytest.fixture
def registry(agora_dir_with_schemas: Path) -> SchemaRegistry:
    return SchemaRegistry.load(agora_dir_with_schemas)


@pytest.fixture
def store(agora_dir_with_schemas: Path, registry: SchemaRegistry) -> AgoraStore:
    return AgoraStore(agora_dir_with_schemas, registry)


@pytest.fixture
def app_parts(
    agora_dir_with_schemas: Path,
    store: AgoraStore,
    registry: SchemaRegistry,
):
    return create_agora_app(
        agora_dir=agora_dir_with_schemas,
        store=store,
        registry=registry,
        port=0,
    )


async def _call(mcp, name: str, arguments: dict | None = None) -> dict:
    """Call a tool through the FastMCP tool manager and parse the JSON result."""
    raw = await mcp._tool_manager.call_tool(name, arguments or {}, context=None)
    return json.loads(raw)


# ---------- create_agora_app 기본 검증 ----------


class TestCreateApp:
    def test_returns_fastmcp_and_queue(self, app_parts) -> None:
        from mcp.server import FastMCP

        mcp, queue = app_parts
        assert isinstance(mcp, FastMCP)
        assert isinstance(queue, AsyncWriteQueue)

    def test_has_six_tools(self, app_parts) -> None:
        mcp, _ = app_parts
        tools = mcp._tool_manager.list_tools()
        assert len(tools) == 6

    def test_tool_names(self, app_parts) -> None:
        mcp, _ = app_parts
        names = {t.name for t in mcp._tool_manager.list_tools()}
        assert names == {
            "agora/info",
            "agora/set",
            "agora/get",
            "agora/append",
            "agora/delete",
            "agora/list",
        }


# ---------- agora/info ----------


class TestAgoraInfo:
    async def test_returns_metadata(self, app_parts, agora_dir_with_schemas: Path) -> None:
        mcp, _ = app_parts
        result = await _call(mcp, "agora/info")
        assert result["path"] == str(agora_dir_with_schemas)
        assert result["port"] == 0
        assert isinstance(result["uptime"], int)
        assert sorted(result["schemas"]) == ["finding", "status"]


# ---------- agora/set + agora/get ----------


class TestAgoraSetGet:
    async def test_set_then_get(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora/set", {
                "schema": "status",
                "key": "review",
                "value": "pending",
            })
            assert r["status"] == "ok"

            r = await _call(mcp, "agora/get", {"schema": "status", "key": "review"})
            assert r["value"] == "pending"

    async def test_set_overwrite(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            await _call(mcp, "agora/set", {
                "schema": "status", "key": "r", "value": "pending",
            })
            await _call(mcp, "agora/set", {
                "schema": "status", "key": "r", "value": "complete",
            })
            r = await _call(mcp, "agora/get", {"schema": "status", "key": "r"})
            assert r["value"] == "complete"

    async def test_set_validation_error(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora/set", {
                "schema": "status",
                "key": "bad",
                "value": "INVALID_ENUM",
            })
            assert "error" in r

    async def test_get_missing_key_returns_null(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora/get", {"schema": "status", "key": "nope"})
        assert r["value"] is None

    async def test_get_unknown_schema(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora/get", {"schema": "nope", "key": "x"})
        assert "error" in r

    async def test_set_object_value(self, app_parts) -> None:
        mcp, queue = app_parts
        finding = {"file": "a.py", "line": 1, "severity": "low"}
        async with queue:
            r = await _call(mcp, "agora/set", {
                "schema": "finding", "key": "f1", "value": finding,
            })
            assert r["status"] == "ok"
            r = await _call(mcp, "agora/get", {"schema": "finding", "key": "f1"})
            assert r["value"] == finding


# ---------- agora/append ----------


class TestAgoraAppend:
    async def test_append_creates_and_extends_list(self, agora_dir: Path) -> None:
        schemas = {"items": {"type": "array", "items": {"type": "integer"}}}
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        mcp, queue = create_agora_app(agora_dir, s, reg, port=0)
        async with queue:
            await _call(mcp, "agora/append", {"schema": "items", "key": "nums", "value": 1, "wait": True})
            await _call(mcp, "agora/append", {"schema": "items", "key": "nums", "value": 2, "wait": True})
            r = await _call(mcp, "agora/get", {"schema": "items", "key": "nums"})
            assert r["value"] == [1, 2]

    async def test_append_validation_error(self, agora_dir: Path) -> None:
        schemas = {"items": {"type": "array", "items": {"type": "integer"}}}
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        mcp, queue = create_agora_app(agora_dir, s, reg, port=0)
        async with queue:
            r = await _call(mcp, "agora/append", {
                "schema": "items", "key": "nums", "value": "not_int", "wait": True,
            })
            assert "error" in r


# ---------- agora/delete ----------


class TestAgoraDelete:
    async def test_delete_existing_key(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            await _call(mcp, "agora/set", {
                "schema": "status", "key": "r", "value": "pending",
            })
            r = await _call(mcp, "agora/delete", {"schema": "status", "key": "r"})
            assert r["status"] == "ok"
            r = await _call(mcp, "agora/get", {"schema": "status", "key": "r"})
            assert r["value"] is None

    async def test_delete_nonexistent_key_is_noop(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora/delete", {"schema": "status", "key": "nope"})
            assert r["status"] == "ok"

    async def test_delete_unknown_schema(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora/delete", {"schema": "nope", "key": "x"})
            assert "error" in r


# ---------- agora/list ----------


class TestAgoraList:
    async def test_list_schemas(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora/list")
        assert sorted(r["schemas"]) == ["finding", "status"]

    async def test_list_keys_empty(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora/list", {"schema": "status"})
        assert r["keys"] == []

    async def test_list_keys_after_set(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            await _call(mcp, "agora/set", {
                "schema": "status", "key": "a", "value": "pending",
            })
            await _call(mcp, "agora/set", {
                "schema": "status", "key": "b", "value": "complete",
            })
        r = await _call(mcp, "agora/list", {"schema": "status"})
        assert sorted(r["keys"]) == ["a", "b"]

    async def test_list_unknown_schema(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora/list", {"schema": "nope"})
        assert "error" in r
