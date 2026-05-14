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

MCP_SESSION_ID_HEADER = "mcp-session-id"

# Name kept as a module-level constant so the list_tools wrapper below
# stays in sync if the @mcp.tool name is ever changed.
_WAIT_TOOL_NAME = "agora.wait"


def _header_int(ctx: Context, header_name: str) -> int | None:
    """Parse an int from an inbound HTTP header on the current MCP request.
    Returns None if the header is absent, the context isn't HTTP-backed, or the
    value isn't a valid int."""
    try:
        v = ctx.request_context.request.headers.get(header_name)
    except (AttributeError, ValueError, LookupError):
        return None
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


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
    instance_registry: InstanceRegistry,
    dispatcher: Dispatcher,
    port: int,
) -> FastMCP:
    """FastMCP 앱을 생성한다 (v3: messaging-only, no KV)."""

    mcp = FastMCP(
        name="AgentAgora",
        host="127.0.0.1",
        port=port,
    )

    start_time = time.time()

    @mcp.tool(name="agora.info")
    async def agora_info() -> str:
        """Return AgentAgora server metadata: data directory path, port, uptime."""
        return json.dumps({
            "path": str(agora_dir),
            "port": port,
            "uptime": int(time.time() - start_time),
        }, ensure_ascii=False)

    @mcp.tool(name="agora.register")
    async def agora_register(
        ctx: Context,
        instance_id: str,
        role: str = "worker",
        description: str = "",
    ) -> str:
        """Register this session as an addressable instance.

        `role` is a short category ("orchestrator", "worker", "reviewer", etc.).
        `description` is a free-form sentence or two about what this instance does —
        used by `agora.find` for capability-based discovery."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        info = instance_registry.register(
            session_id=session_id,
            instance_id=instance_id,
            role=role,
            description=description,
        )
        return json.dumps({
            "status": "ok",
            "instance_id": info.instance_id,
            "role": info.role,
            "description": info.description,
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
        """List all registered instances visible to the server. Includes role and description."""
        items = [
            {
                "instance_id": i.instance_id,
                "role": i.role,
                "description": i.description,
                "registered_at": i.registered_at,
            }
            for i in instance_registry.list_instances()
        ]
        return json.dumps({"instances": items}, ensure_ascii=False)

    @mcp.tool(name="agora.find")
    async def agora_find(query: str) -> str:
        """Find instances whose instance_id, role, or description contains `query`
        (case-insensitive substring match). Returns the same shape as `agora.instances`
        but filtered. Empty query returns an empty list."""
        if not query:
            return json.dumps({"instances": []})
        q = query.lower()
        items = [
            {
                "instance_id": i.instance_id,
                "role": i.role,
                "description": i.description,
                "registered_at": i.registered_at,
            }
            for i in instance_registry.list_instances()
            if q in i.instance_id.lower()
            or q in i.role.lower()
            or q in i.description.lower()
        ]
        return json.dumps({"instances": items}, ensure_ascii=False)

    @mcp.tool(name="agora.dispatch")
    async def agora_dispatch(
        ctx: Context,
        target: list[str],
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
    ) -> str:
        """Dispatch a command to one or more registered instances.

        target: ALWAYS a list of instance_ids (length >= 1). Single recipient:
            ["Inst2"]. Fan-out to all other registered instances: ["_broadcast"]
            (length 1, exclusive with explicit ids).

        payload: free-form JSON. Application-level content.

        reply_to: instance_id that should receive the recipient's reply. Leave
            null and the recipient will reply to YOU (the source). Set this when
            you are brokering a request on behalf of another instance and want
            the downstream worker to reply directly to that original requester.
            Validated against the registry — must be a currently registered id.

        in_reply_to: command_id of the message you're answering. Set this when
            you are SENDING A REPLY to a command you received. Lets the original
            requester correlate the reply with their original request.

        expect_result: informational hint that the sender expects a reply.

        Caller MUST be registered (via agora.register or X-Agora-Instance-Id header)."""
        try:
            source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            result = await dispatcher.dispatch(
                source=source,
                target=target,
                payload=payload,
                expect_result=expect_result,
                reply_to=reply_to,
                in_reply_to=in_reply_to,
            )
            return json.dumps({
                "status": "ok",
                "command_id": result["command_id"],
                "created_at": result["created_at"],
                "target": target,
            })
        except (NotRegisteredError, ValueError) as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    @mcp.tool(name=_WAIT_TOOL_NAME)
    async def agora_wait(
        ctx: Context,
        timeout_ms: int | None = None,
        from_sources: list[str] | None = None,
    ) -> str:
        """Wait for commands targeted at this instance.

        timeout_ms resolution order (first non-None wins):
            1. Explicit `timeout_ms` argument
            2. `X-Agora-Wait-Timeout-Ms` header (if set in client's `.mcp.json`)
            3. Server CLI default (`--default-wait-timeout-ms` / `--no-timeout`)

        Values: positive = wait at most N ms then return empty; 0 = unbounded.

        from_sources: if provided, only drain commands whose `source` matches one
                      of the names in the list. Unmatched commands stay queued.
        Returns {commands: [...]}. Empty list means timeout (or filter mismatch)
        with no commands.
        The caller MUST be registered before waiting."""
        try:
            info = instance_registry.resolve_session(_session_id_from_ctx(ctx))
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})

        if timeout_ms is None:
            timeout_ms = _header_int(ctx, "x-agora-wait-timeout-ms")

        try:
            commands = await dispatcher.wait(
                instance_id=info.instance_id,
                timeout_ms=timeout_ms,
                from_sources=from_sources,
            )
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

    return mcp
