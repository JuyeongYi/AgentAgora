# src/agent_agora/server.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mcp.server import FastMCP

from agent_agora.schema import SchemaRegistry
from agent_agora.store import AgoraStore, AsyncWriteQueue


def create_agora_app(
    agora_dir: Path,
    store: AgoraStore,
    registry: SchemaRegistry,
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

    @mcp.tool(name="agora/info")
    async def agora_info() -> str:
        """Return AgentAgora server metadata: data directory path, port, registered schemas, uptime."""
        return json.dumps({
            "path": str(agora_dir),
            "port": port,
            "schemas": sorted(registry.names()),
            "uptime": int(time.time() - start_time),
        }, ensure_ascii=False)

    @mcp.tool(name="agora/set")
    async def agora_set(schema: str, key: str, value: Any, wait: bool = True) -> str:
        """Store a value under a schema key. Value is validated against the registered JSON Schema. Overwrites if key exists."""
        try:
            await queue.submit_set(schema, key, value, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except (KeyError, ValueError, TypeError) as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora/get")
    async def agora_get(schema: str, key: str) -> str:
        """Retrieve a value by schema and key."""
        try:
            result = store.get(schema, key)
            return json.dumps({"schema": schema, "key": key, "value": result}, ensure_ascii=False)
        except KeyError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora/append")
    async def agora_append(schema: str, key: str, value: Any, wait: bool = False) -> str:
        """Append an item to a list value. The existing value must be an array."""
        try:
            await queue.submit_append(schema, key, value, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except (KeyError, ValueError, TypeError) as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora/delete")
    async def agora_delete(schema: str, key: str, wait: bool = True) -> str:
        """Remove a key from a schema. The schema definition is preserved."""
        try:
            await queue.submit_delete(schema, key, wait=wait)
            return json.dumps({"status": "ok", "schema": schema, "key": key})
        except KeyError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora/list")
    async def agora_list(schema: str | None = None) -> str:
        """List registered schemas, or list keys within a specific schema."""
        if schema is None:
            return json.dumps({"schemas": sorted(registry.names())})
        try:
            keys = store.list_keys(schema)
            return json.dumps({"schema": schema, "keys": keys})
        except KeyError as e:
            return json.dumps({"error": str(e)})

    return mcp, queue
