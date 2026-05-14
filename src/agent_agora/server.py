# src/agent_agora/server.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mcp.server import FastMCP
from mcp.server.fastmcp.server import Context

from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.schema import SchemaRegistry
from agent_agora.store import AgoraStore, AsyncWriteQueue

MCP_SESSION_ID_HEADER = "mcp-session-id"


def _session_id_from_ctx(ctx: Context) -> str:
    """Extract MCP session id from a FastMCP Context.

    In this SDK version the session ID is the HTTP Mcp-Session-Id header,
    which the StreamableHTTP transport stores as a Starlette Request object
    at ctx.request_context.request.  We try that path first, then fall back
    through alternative shapes for forward-compatibility.
    """
    # Primary path: streamable-HTTP transport sets request_context.request to
    # the Starlette Request object, which carries the mcp-session-id header.
    try:
        request = ctx.request_context.request
        if request is not None:
            session_id = request.headers.get(MCP_SESSION_ID_HEADER)
            if session_id:
                return session_id
    except (AttributeError, LookupError):
        pass

    # Fallback: future SDK versions may expose session_id directly on the session
    for attr_chain in (
        ("request_context", "session", "session_id"),
        ("request_context", "session_id"),
        ("session_id",),
    ):
        obj = ctx
        try:
            for attr in attr_chain:
                obj = getattr(obj, attr)
            if isinstance(obj, str):
                return obj
        except AttributeError:
            continue

    raise RuntimeError(
        "Cannot determine session id from MCP Context. "
        "The Mcp-Session-Id header was absent or the Context structure is unrecognised. "
        "agora.register requires a stateful streamable-HTTP session."
    )


def create_agora_app(
    agora_dir: Path,
    store: AgoraStore,
    registry: SchemaRegistry,
    instance_registry: InstanceRegistry,
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
        try:
            await queue.submit_append(schema, key, value, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except (KeyError, ValueError, TypeError) as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.delete")
    async def agora_delete(schema: str, key: str, wait: bool = True) -> str:
        """Remove a key from a schema. The schema definition is preserved."""
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
        session_id = _session_id_from_ctx(ctx)
        info = instance_registry.register(session_id=session_id, instance_id=instance_id, role=role)
        return json.dumps({
            "status": "ok",
            "instance_id": info.instance_id,
            "registered_at": info.registered_at,
        })

    @mcp.tool(name="agora.unregister")
    async def agora_unregister(ctx: Context) -> str:
        """Unregister this session. Idempotent."""
        session_id = _session_id_from_ctx(ctx)
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

    return mcp, queue
