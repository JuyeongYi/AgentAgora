# src/agent_agora/server.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from mcp.types import ToolExecution

from agent_agora.dispatcher import Dispatcher, DispatcherClosed
from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.schema import SchemaRegistry
from agent_agora.store import AgoraStore, AsyncWriteQueue

MCP_SESSION_ID_HEADER = "mcp-session-id"

# Name kept as a module-level constant so the list_tools wrapper below
# stays in sync if the @mcp.tool name is ever changed.
_WAIT_TOOL_NAME = "agora.wait"

# Schemas whose data is owned exclusively by the dispatcher/registry subsystem.
# Writing through CRUD tools (set/append/delete) would corrupt the user-visible
# view without touching the in-memory registry, so we block writes at the boundary.
# NOTE: "schemas" is intentionally excluded — it is a meta-schema, not a data schema.
_RESERVED_SCHEMA_NAMES = frozenset({"instances", "commands", "results"})


def _session_id_from_ctx(ctx: Context) -> str:
    """Extract MCP session id from FastMCP Context.

    Currently relies on the Streamable HTTP transport injecting the Starlette
    Request into request_context; the session id rides on the `Mcp-Session-Id` header.
    If the SDK structure changes, this helper needs to be re-verified.
    """
    try:
        request = ctx.request_context.request
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            return session_id
    except (AttributeError, ValueError, LookupError):
        pass
    raise RuntimeError("Cannot determine MCP session id from Context (no active streamable-HTTP request?)")


def create_agora_app(
    agora_dir: Path,
    store: AgoraStore,
    registry: SchemaRegistry,
    instance_registry: InstanceRegistry,
    dispatcher: Dispatcher,
    port: int,
) -> tuple[FastMCP, AsyncWriteQueue]:
    """FastMCP 앱과 AsyncWriteQueue를 생성한다."""

    mcp = FastMCP(
        name="AgentAgora",
        host="127.0.0.1",
        port=port,
    )

    queue = AsyncWriteQueue(store)
    start_time = time.time()

    @mcp.tool(name="agora.info")
    async def agora_info() -> str:
        """Return AgentAgora server metadata: data directory path, port, registered schemas, uptime."""
        return json.dumps({
            "path": str(agora_dir),
            "port": port,
            "schemas": sorted(registry.names()),
            "uptime": int(time.time() - start_time),
        }, ensure_ascii=False)

    @mcp.tool(name="agora.set")
    async def agora_set(schema: str, key: str, value: Any, wait: bool = True) -> str:
        """Store a value under a schema key. Value is validated against the registered JSON Schema. Overwrites if key exists."""
        if schema in _RESERVED_SCHEMA_NAMES:
            return json.dumps({"error": f"Schema '{schema}' is reserved for internal use. Use the agora.register / agora.dispatch tools instead."})
        try:
            await queue.submit_set(schema, key, value, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except (KeyError, ValueError, TypeError) as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.get")
    async def agora_get(schema: str, key: str) -> str:
        """Retrieve a value by schema and key."""
        try:
            result = store.get(schema, key)
            return json.dumps({"schema": schema, "key": key, "value": result}, ensure_ascii=False)
        except KeyError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.append")
    async def agora_append(schema: str, key: str, value: Any, wait: bool = False) -> str:
        """Append an item to a list value. The existing value must be an array."""
        if schema in _RESERVED_SCHEMA_NAMES:
            return json.dumps({"error": f"Schema '{schema}' is reserved for internal use. Use the agora.register / agora.dispatch tools instead."})
        try:
            await queue.submit_append(schema, key, value, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except (KeyError, ValueError, TypeError) as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.delete")
    async def agora_delete(schema: str, key: str, wait: bool = True) -> str:
        """Remove a key from a schema. The schema definition is preserved."""
        if schema in _RESERVED_SCHEMA_NAMES:
            return json.dumps({"error": f"Schema '{schema}' is reserved for internal use. It is auto-managed; use agora.unregister to remove an instance."})
        try:
            await queue.submit_delete(schema, key, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except KeyError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.list")
    async def agora_list(schema: str | None = None) -> str:
        """List registered schemas, or list keys within a specific schema."""
        if schema is None:
            return json.dumps({"schemas": sorted(registry.names())})
        try:
            keys = store.list_keys(schema)
            return json.dumps({"schema": schema, "keys": keys})
        except KeyError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.register")
    async def agora_register(ctx: Context, instance_id: str, role: str = "worker") -> str:
        """Register this session as an addressable instance. Required before dispatch/wait."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        info = instance_registry.register(session_id=session_id, instance_id=instance_id, role=role)
        return json.dumps({
            "status": "ok",
            "instance_id": info.instance_id,
            "role": info.role,
            "registered_at": info.registered_at,
        })

    @mcp.tool(name="agora.unregister")
    async def agora_unregister(ctx: Context) -> str:
        """Unregister this session. Idempotent."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        instance_registry.unregister_session(session_id)
        return json.dumps({"status": "ok"})

    @mcp.tool(name="agora.instances")
    async def agora_instances() -> str:
        """List all registered instances visible to the server."""
        items = [
            {"instance_id": i.instance_id, "role": i.role, "registered_at": i.registered_at}
            for i in instance_registry.list_instances()
        ]
        return json.dumps({"instances": items})

    @mcp.tool(name="agora.dispatch")
    async def agora_dispatch(
        ctx: Context,
        target: str,
        payload: Any,
        expect_result: bool = False,
    ) -> str:
        """Dispatch a command to another registered instance. Use target='_broadcast' to fan out to all others.
        The caller MUST be registered (via agora.register) before dispatching."""
        try:
            source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            cmd_id = await dispatcher.dispatch(
                source=source, target=target, payload=payload, expect_result=expect_result,
            )
            return json.dumps({"status": "ok", "command_id": cmd_id, "target": target})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    @mcp.tool(name=_WAIT_TOOL_NAME)
    async def agora_wait(ctx: Context, timeout_ms: int | None = None) -> str:
        """Wait for commands targeted at this instance.

        timeout_ms: positive = wait at most N ms then return empty;
                    0 = unbounded blocking (no timeout);
                    None = use server default (--default-wait-timeout-ms).
        Returns {commands: [...]}. Empty list means timeout with no commands.
        The caller MUST be registered (via agora.register) before waiting."""
        try:
            info = instance_registry.resolve_session(_session_id_from_ctx(ctx))
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            commands = await dispatcher.wait(instance_id=info.instance_id, timeout_ms=timeout_ms)
            return json.dumps({"commands": commands}, ensure_ascii=False)
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    # --- MCP 2025-11-25: declare execution.taskSupport="optional" on agora.wait ---
    # The FastMCP internal Tool class and its @mcp.tool decorator do not yet expose an
    # `execution` field (Case B: mcp.types.Tool has it; fastmcp.tools.base.Tool does not).
    # We wrap mcp.list_tools() on this instance to inject the field into the wire
    # representation for agora.wait. All other tools are passed through unchanged.
    #
    # REMOVAL: When fastmcp.tools.base.Tool gains an `execution` field
    # (check with `'execution' in fastmcp.tools.base.Tool.model_fields`),
    # replace this block with `@mcp.tool(name=_WAIT_TOOL_NAME, execution=...)`
    # and delete _original_list_tools / _list_tools_with_wait_execution.
    _original_list_tools = mcp.list_tools

    async def _list_tools_with_wait_execution():
        tools = await _original_list_tools()
        return [
            tool.model_copy(update={"execution": ToolExecution(taskSupport="optional")})
            if tool.name == _WAIT_TOOL_NAME
            else tool
            for tool in tools
        ]

    mcp.list_tools = _list_tools_with_wait_execution  # type: ignore[method-assign]  # swap bound method to inject execution metadata
    # CRITICAL: re-register the wire handler so the new wrapper is captured in
    # request_handlers[ListToolsRequest].  FastMCP's _setup_handlers() already
    # registered the original mcp.list_tools as a closure; calling the decorator
    # factory again overwrites that entry with a new closure around our wrapper.
    # mcp._mcp_server: private FastMCP attribute (verified against mcp SDK 1.26.0).
    mcp._mcp_server.list_tools()(_list_tools_with_wait_execution)
    # -------------------------------------------------------------------------

    # Sanity: the wrapper hardcodes _WAIT_TOOL_NAME; ensure the corresponding tool exists.
    assert any(t.name == _WAIT_TOOL_NAME for t in mcp._tool_manager.list_tools()), (
        f"Internal error: list_tools wrapper expects '{_WAIT_TOOL_NAME}' but no such tool registered"
    )

    return mcp, queue
