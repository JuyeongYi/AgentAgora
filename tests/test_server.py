# tests/test_server.py
from __future__ import annotations

import json
from pathlib import Path

import mcp.types as types
import pytest

from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
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
    instance_registry = InstanceRegistry()
    dispatcher = Dispatcher(instance_registry, default_timeout_ms=1000)
    return create_agora_app(
        agora_dir=agora_dir_with_schemas,
        store=store,
        registry=registry,
        instance_registry=instance_registry,
        dispatcher=dispatcher,
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

    def test_has_eleven_tools(self, app_parts) -> None:
        mcp, _ = app_parts
        tools = mcp._tool_manager.list_tools()
        assert len(tools) == 11

    def test_tool_names(self, app_parts) -> None:
        mcp, _ = app_parts
        names = {t.name for t in mcp._tool_manager.list_tools()}
        assert names == {
            "agora.info",
            "agora.set",
            "agora.get",
            "agora.append",
            "agora.delete",
            "agora.list",
            "agora.register",
            "agora.unregister",
            "agora.instances",
            "agora.dispatch",
            "agora.wait",
        }

    async def test_agora_wait_declares_optional_task_support(self, app_parts) -> None:
        """agora.wait must advertise execution.taskSupport='optional' in tools/list.

        MCP 2025-11-25 spec: Tool.execution.taskSupport values are
        'forbidden' (default) | 'optional' | 'required'. 'optional' allows
        task-capable clients to invoke the tool as a long-running task.

        Implementation note (Case B): mcp.types.Tool carries the execution field
        but fastmcp.tools.base.Tool and the @mcp.tool decorator do not. We inject
        the field by wrapping mcp.list_tools() in create_agora_app and
        re-registering via mcp._mcp_server.list_tools()(...) so that the wire-level
        handler in request_handlers[ListToolsRequest] captures the wrapper.

        This test invokes the *actual wire-level handler* stored in
        mcp._mcp_server.request_handlers[ListToolsRequest], which is what a real
        MCP client over tools/list would hit.  The handler returns
        ServerResult(ListToolsResult(tools=[...])); we unwrap accordingly.
        """
        mcp_app, _ = app_parts
        handler = mcp_app._mcp_server.request_handlers[types.ListToolsRequest]
        request = types.ListToolsRequest(method="tools/list", params=None)
        server_result = await handler(request)
        # server_result is ServerResult; its .root is a ListToolsResult
        tools = server_result.root.tools
        wait_tool = next(t for t in tools if t.name == "agora.wait")
        assert wait_tool.execution is not None, "agora.wait must have an execution field set"
        assert wait_tool.execution.taskSupport == "optional"


# ---------- agora.info ----------


class TestAgoraInfo:
    async def test_returns_metadata(self, app_parts, agora_dir_with_schemas: Path) -> None:
        mcp, _ = app_parts
        result = await _call(mcp, "agora.info")
        assert result["path"] == str(agora_dir_with_schemas)
        assert result["port"] == 0
        assert isinstance(result["uptime"], int)
        assert {"finding", "status"}.issubset(result["schemas"])


# ---------- agora.set + agora.get ----------


class TestAgoraSetGet:
    async def test_set_then_get(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora.set", {
                "schema": "status",
                "key": "review",
                "value": "pending",
            })
            assert r["status"] == "ok"

            r = await _call(mcp, "agora.get", {"schema": "status", "key": "review"})
            assert r["value"] == "pending"

    async def test_set_overwrite(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            await _call(mcp, "agora.set", {
                "schema": "status", "key": "r", "value": "pending",
            })
            await _call(mcp, "agora.set", {
                "schema": "status", "key": "r", "value": "complete",
            })
            r = await _call(mcp, "agora.get", {"schema": "status", "key": "r"})
            assert r["value"] == "complete"

    async def test_set_validation_error(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora.set", {
                "schema": "status",
                "key": "bad",
                "value": "INVALID_ENUM",
            })
            assert "error" in r

    async def test_get_missing_key_returns_null(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora.get", {"schema": "status", "key": "nope"})
        assert r["value"] is None

    async def test_get_unknown_schema(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora.get", {"schema": "nope", "key": "x"})
        assert "error" in r

    async def test_set_object_value(self, app_parts) -> None:
        mcp, queue = app_parts
        finding = {"file": "a.py", "line": 1, "severity": "low"}
        async with queue:
            r = await _call(mcp, "agora.set", {
                "schema": "finding", "key": "f1", "value": finding,
            })
            assert r["status"] == "ok"
            r = await _call(mcp, "agora.get", {"schema": "finding", "key": "f1"})
            assert r["value"] == finding


# ---------- agora.append ----------


class TestAgoraAppend:
    async def test_append_creates_and_extends_list(self, agora_dir: Path) -> None:
        schemas = {"items": {"type": "array", "items": {"type": "integer"}}}
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        ir = InstanceRegistry()
        mcp, queue = create_agora_app(agora_dir, s, reg, instance_registry=ir, dispatcher=Dispatcher(ir, default_timeout_ms=1000), port=0)
        async with queue:
            await _call(mcp, "agora.append", {"schema": "items", "key": "nums", "value": 1, "wait": True})
            await _call(mcp, "agora.append", {"schema": "items", "key": "nums", "value": 2, "wait": True})
            r = await _call(mcp, "agora.get", {"schema": "items", "key": "nums"})
            assert r["value"] == [1, 2]

    async def test_append_validation_error(self, agora_dir: Path) -> None:
        schemas = {"items": {"type": "array", "items": {"type": "integer"}}}
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        ir = InstanceRegistry()
        mcp, queue = create_agora_app(agora_dir, s, reg, instance_registry=ir, dispatcher=Dispatcher(ir, default_timeout_ms=1000), port=0)
        async with queue:
            r = await _call(mcp, "agora.append", {
                "schema": "items", "key": "nums", "value": "not_int", "wait": True,
            })
            assert "error" in r


# ---------- agora.delete ----------


class TestAgoraDelete:
    async def test_delete_existing_key(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            await _call(mcp, "agora.set", {
                "schema": "status", "key": "r", "value": "pending",
            })
            r = await _call(mcp, "agora.delete", {"schema": "status", "key": "r"})
            assert r["status"] == "ok"
            r = await _call(mcp, "agora.get", {"schema": "status", "key": "r"})
            assert r["value"] is None

    async def test_delete_nonexistent_key_is_noop(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora.delete", {"schema": "status", "key": "nope"})
            assert r["status"] == "ok"

    async def test_delete_unknown_schema(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            r = await _call(mcp, "agora.delete", {"schema": "nope", "key": "x"})
            assert "error" in r


# ---------- agora.list ----------


class TestAgoraList:
    async def test_list_schemas(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora.list")
        assert {"finding", "status"}.issubset(r["schemas"])

    async def test_list_keys_empty(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora.list", {"schema": "status"})
        assert r["keys"] == []

    async def test_list_keys_after_set(self, app_parts) -> None:
        mcp, queue = app_parts
        async with queue:
            await _call(mcp, "agora.set", {
                "schema": "status", "key": "a", "value": "pending",
            })
            await _call(mcp, "agora.set", {
                "schema": "status", "key": "b", "value": "complete",
            })
        r = await _call(mcp, "agora.list", {"schema": "status"})
        assert sorted(r["keys"]) == ["a", "b"]

    async def test_list_unknown_schema(self, app_parts) -> None:
        mcp, _ = app_parts
        r = await _call(mcp, "agora.list", {"schema": "nope"})
        assert "error" in r


# ---------- reserved-schema guards (Fix 1) ----------


class TestReservedSchemaGuards:
    async def test_agora_set_rejects_instances(self, app_parts) -> None:
        mcp_app, _ = app_parts
        result = await _call(mcp_app, "agora.set", {
            "schema": "instances",
            "key": "fake",
            "value": {"instance_id": "X", "registered_at": "2026-01-01T00:00:00Z"},
        })
        assert "error" in result
        assert "reserved" in result["error"].lower()

    async def test_agora_append_rejects_commands(self, app_parts) -> None:
        mcp_app, _ = app_parts
        result = await _call(mcp_app, "agora.append", {
            "schema": "commands",
            "key": "fake",
            "value": {"id": "x"},
        })
        assert "error" in result
        assert "reserved" in result["error"].lower()

    async def test_agora_delete_rejects_results(self, app_parts) -> None:
        mcp_app, _ = app_parts
        result = await _call(mcp_app, "agora.delete", {
            "schema": "results",
            "key": "fake",
        })
        assert "error" in result
        assert "reserved" in result["error"].lower()

    async def test_agora_set_rejects_commands(self, app_parts) -> None:
        mcp_app, _ = app_parts
        result = await _call(mcp_app, "agora.set", {
            "schema": "commands",
            "key": "fake",
            "value": {},
        })
        assert "error" in result
        assert "reserved" in result["error"].lower()

    async def test_agora_set_rejects_results(self, app_parts) -> None:
        mcp_app, _ = app_parts
        result = await _call(mcp_app, "agora.set", {
            "schema": "results",
            "key": "fake",
            "value": {},
        })
        assert "error" in result
        assert "reserved" in result["error"].lower()

    async def test_agora_get_allows_reserved_schema(self, app_parts) -> None:
        """agora.get must remain read-accessible for reserved schemas (non-destructive)."""
        mcp_app, _ = app_parts
        # These schemas are empty in the store; expect None value, not an error.
        result = await _call(mcp_app, "agora.get", {"schema": "instances", "key": "any"})
        assert "error" not in result or "reserved" not in result.get("error", "").lower()

    async def test_agora_list_allows_reserved_schema(self, app_parts) -> None:
        """agora.list must remain read-accessible for reserved schemas (non-destructive)."""
        mcp_app, _ = app_parts
        result = await _call(mcp_app, "agora.list", {"schema": "instances"})
        # May return error for unknown schema (not registered in store) or an empty list —
        # either is acceptable, but must NOT be a "reserved" error.
        assert "reserved" not in result.get("error", "").lower()
