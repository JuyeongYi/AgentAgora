# src/agent_agora/server.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from mcp.types import ToolExecution

from agent_agora.bot_registry import BotRegistry
from agent_agora.dispatcher import Dispatcher, DispatcherClosed
from agent_agora.errors import AgoraError
from agent_agora.persistence import Persistence
from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.schemas import SchemaRegistry

MCP_SESSION_ID_HEADER = "mcp-session-id"

_WAIT_TOOL_NAME = "agora.wait"


def _header_int(ctx: Context, header_name: str) -> int | None:
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
    schema_registry: SchemaRegistry,
    bot_registry: BotRegistry,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
) -> FastMCP:
    """FastMCP 앱을 생성한다 (v3: messaging-only)."""

    mcp = FastMCP(
        name="AgentAgora",
        host="127.0.0.1",
        port=port,
    )

    start_time = time.time()

    @mcp.tool(name="agora.info")
    async def agora_info() -> str:
        return json.dumps({
            "path": str(agora_dir),
            "port": port,
            "uptime": int(time.time() - start_time),
        }, ensure_ascii=False)

    @mcp.tool(name="agora.register_schema")
    async def agora_register_schema(
        name: str,
        body: dict,
        kind: Literal["conversation", "bot-task"],
        purpose: str,
    ) -> str:
        """Register a schema. Immutable — 동일 이름 다른 body는 거부.
        body에 msgtype property 필수 (결정 20)."""
        try:
            schema_registry.register(name, body, kind=kind, purpose=purpose)
            persistence.save_schema(name, body, kind=kind, purpose=purpose)
        except AgoraError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "ok", "name": name, "kind": kind})

    @mcp.tool(name="agora.schemas")
    async def agora_schemas() -> str:
        """Full schema catalog — name, kind, purpose, body."""
        return json.dumps({"schemas": [
            {"name": e.name, "kind": e.kind, "purpose": e.purpose, "body": e.body}
            for e in schema_registry.list_all()
        ]}, ensure_ascii=False)

    @mcp.tool(name="agora.schemas_list")
    async def agora_schemas_list() -> str:
        """Schema metadata only — name, kind, purpose (body 제외)."""
        return json.dumps({"schemas": schema_registry.list_meta()}, ensure_ascii=False)

    @mcp.tool(name="agora.register")
    async def agora_register(
        ctx: Context,
        instance_id: str,
        role: str = "worker",
        description: str = "",
        wait_mode: Literal["auto", "manual"] | None = None,
    ) -> str:
        """Register this session as an addressable instance.

        wait_mode: 'auto' means this worker uses an auto-loop on agora.wait,
        'manual' means a human triggers waits. Defaults to 'unknown' if omitted.
        """
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        info = instance_registry.register(
            session_id=session_id,
            instance_id=instance_id,
            role=role,
            description=description,
            wait_mode=wait_mode,
        )
        return json.dumps({
            "status": "ok",
            "instance_id": info.instance_id,
            "role": info.role,
            "description": info.description,
            "registered_at": info.registered_at,
            "wait_mode": info.wait_mode,
        })

    @mcp.tool(name="agora.register_bot")
    async def agora_register_bot(
        ctx: Context,
        instance_id: str,
        description: str,
        bot_mode: Literal["handler", "observer"] = "handler",
        subscribe_schemas: list[str] | None = None,
        emit_schemas: list[str] | None = None,
        schemas: dict[str, dict] | None = None,
    ) -> str:
        """Register this session as a bot (schema subscriber). 결정 16·25.

        bot_mode='handler': subscribe_schemas (모두 bot-task kind) 필수.
        bot_mode='observer': schema 무관 전체 메시지를 cc로 수신.
        schemas: 신규 schema 동시 등록. {name: {kind, purpose, body}} (kind는 'bot-task').
        """
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        subscribe = list(subscribe_schemas or [])
        emit = list(emit_schemas or [])
        schemas = schemas or {}
        try:
            if not description:
                raise AgoraError("description_required")
            if bot_mode == "handler" and not subscribe:
                raise AgoraError("subscribe_required")

            # (1) inline schemas 사전 검증 — diff preflight (§3.3, §9.6)
            for name, defn in schemas.items():
                if defn.get("kind") != "bot-task":
                    raise AgoraError("schema_kind_not_bot_task", name=name)
                existing = schema_registry.get(name)
                if existing is not None and existing.body != defn.get("body"):
                    raise AgoraError("schema_immutable", name=name)
            # (2) 일괄 등록 — 모두 검증 통과 후
            for name, defn in schemas.items():
                schema_registry.register(
                    name, defn["body"], kind="bot-task",
                    purpose=defn.get("purpose", ""), registered_by=instance_id)
                persistence.save_schema(
                    name, defn["body"], kind="bot-task",
                    purpose=defn.get("purpose", ""), registered_by=instance_id)
            # (3) 구독 schema 검증 — 존재 + bot-task kind
            if bot_mode == "handler":
                for s in subscribe:
                    entry = schema_registry.get(s)
                    if entry is None:
                        raise AgoraError("unknown_msgtype", msgtype=s)
                    if entry.kind != "bot-task":
                        raise AgoraError("cannot_subscribe_conversation", name=s)

            info = bot_registry.register(
                session_id=session_id, instance_id=instance_id,
                description=description, bot_mode=bot_mode,
                subscribe_schemas=subscribe if bot_mode == "handler" else (),
                emit_schemas=emit if bot_mode == "handler" else ())
            persistence.save_bot_subscriptions(
                instance_id, subscribe=list(info.subscribe_schemas),
                emit=list(info.emit_schemas))
        except AgoraError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({
            "status": "ok", "instance_id": info.instance_id,
            "bot_mode": info.bot_mode,
            "subscribe_schemas": list(info.subscribe_schemas),
            "emit_schemas": list(info.emit_schemas),
            "registered_at": info.registered_at,
        })

    @mcp.tool(name="agora.unregister")
    async def agora_unregister(ctx: Context) -> str:
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        instance_registry.unregister_session(session_id)
        return json.dumps({"status": "ok"})

    @mcp.tool(name="agora.instances")
    async def agora_instances() -> str:
        """List all registered instances with v3 load metadata."""
        meta = dispatcher.peek([i.instance_id for i in instance_registry.list_instances()])
        items = []
        for i in instance_registry.list_instances():
            m = meta.get(i.instance_id, {})
            items.append({
                "instance_id": i.instance_id,
                "role": i.role,
                "description": i.description,
                "registered_at": i.registered_at,
                "inbox_depth": m.get("queue_depth", 0),
                "in_flight": m.get("in_flight", 0),
                "last_seen_at": i.last_seen_at,
                "wait_mode": i.wait_mode,
                "accepting": i.accepting,
            })
        return json.dumps({"instances": items}, ensure_ascii=False)

    @mcp.tool(name="agora.find")
    async def agora_find(query: str) -> str:
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
        target: str,
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low", "normal", "high"] = "normal",
        deadline_ts: str | None = None,
    ) -> str:
        """Dispatch a command to one registered instance, with optional cc observers.

        target: single instance_id (use agora.broadcast for fan-out).
        cc: list of observer instance_ids — they receive a copy with delivered_as='cc'
            and have no reply obligation. cc does not auto-inherit.
        closing=True signals end-of-conversation (single-direction advisory).
        priority: 'high' must be reserved for actual blocking reasons.
        Caller MUST be registered.
        """
        try:
            source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            result = await dispatcher.dispatch(
                source=source, target=target, payload=payload,
                expect_result=expect_result, reply_to=reply_to, cc=cc,
                in_reply_to=in_reply_to, conversation_id=conversation_id,
                closing=closing, priority=priority, deadline_ts=deadline_ts,
            )
            return json.dumps({"status": "ok", **result})
        except (NotRegisteredError, ValueError) as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    @mcp.tool(name="agora.broadcast")
    async def agora_broadcast(
        ctx: Context,
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low", "normal", "high"] = "normal",
        deadline_ts: str | None = None,
    ) -> str:
        """Fan-out to ALL other registered instances. closing=True → announcement (immediate close)."""
        try:
            source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            result = await dispatcher.broadcast(
                source=source, payload=payload,
                expect_result=expect_result, reply_to=reply_to,
                in_reply_to=in_reply_to, conversation_id=conversation_id,
                closing=closing, priority=priority, deadline_ts=deadline_ts,
            )
            return json.dumps({"status": "ok", **result})
        except (NotRegisteredError, ValueError) as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    @mcp.tool(name="agora.peek")
    async def agora_peek(targets: list[str] | None = None) -> str:
        """Snapshot of queue depth, in_flight count, and consumer activity per instance.

        ADVISORY ONLY — atomicity not guaranteed (TOCTOU race vs subsequent dispatch).
        targets=None returns all registered instances. Unregistered ids return registered=False.
        """
        return json.dumps(dispatcher.peek(targets), ensure_ascii=False)

    @mcp.tool(name="agora.conversation_status")
    async def agora_conversation_status(conversation_id: str) -> str:
        """Query the status, kind, participants, and message_count of a conversation."""
        return json.dumps(dispatcher.conversation_status(conversation_id), ensure_ascii=False)

    @mcp.tool(name="agora.conversations_list")
    async def agora_conversations_list(
        participant: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> str:
        """List conversations (open/half_closed/closed) ordered by last_message_at desc."""
        return json.dumps(dispatcher.conversations_list(participant=participant, status=status, limit=limit), ensure_ascii=False)

    @mcp.tool(name="agora.close_thread")
    async def agora_close_thread(ctx: Context, conversation_id: str, reason: str = "") -> str:
        """Explicit close of a conversation. Equivalent to dispatching closing=True
        to every other primary participant. caller MUST be a participant."""
        try:
            caller = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            return json.dumps(await dispatcher.close_thread(caller, conversation_id, reason=reason))
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name=_WAIT_TOOL_NAME)
    async def agora_wait(
        ctx: Context,
        timeout_ms: int | None = None,
        from_sources: list[str] | None = None,
        sort: Literal["fifo", "priority"] = "fifo",
        by_conversation: str | None = None,
    ) -> str:
        """Wait for commands targeted at this instance.

        timeout_ms resolution order (first non-None wins):
            1. Explicit argument
            2. X-Agora-Wait-Timeout-Ms header
            3. Server CLI default

        Values: positive = wait at most N ms then return empty; 0 = unbounded.

        sort='fifo' returns by (created_at asc, command_id asc). 'priority' uses
        (priority_rank asc, created_at asc, command_id asc) — high before normal before low.
        from_sources / by_conversation: AND-combined filters; unmatched envelopes stay queued.
        The caller MUST be registered before waiting.
        """
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
                sort=sort,
                by_conversation=by_conversation,
            )
            return json.dumps({"commands": commands}, ensure_ascii=False)
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    # --- MCP execution.taskSupport hint on agora.wait ---
    _original_list_tools = mcp.list_tools

    async def _list_tools_with_wait_execution():
        tools = await _original_list_tools()
        return [
            tool.model_copy(update={"execution": ToolExecution(taskSupport="optional")})
            if tool.name == _WAIT_TOOL_NAME
            else tool
            for tool in tools
        ]

    mcp.list_tools = _list_tools_with_wait_execution  # type: ignore[method-assign]
    mcp._mcp_server.list_tools()(_list_tools_with_wait_execution)

    assert any(t.name == _WAIT_TOOL_NAME for t in mcp._tool_manager.list_tools()), (
        f"Internal error: list_tools wrapper expects '{_WAIT_TOOL_NAME}' but no such tool registered"
    )

    return mcp
