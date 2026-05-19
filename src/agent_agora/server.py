# src/agent_agora/server.py
from __future__ import annotations

import datetime
import json
import os.path
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server import FastMCP
from mcp.server.fastmcp import Context

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher, DispatcherClosed
from agent_agora.errors import AgoraError
from agent_agora.persistence import Persistence
from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.schemas import SchemaRegistry

MCP_SESSION_ID_HEADER = "mcp-session-id"


def _resolve_caller(session_id: str, instance_registry, bot_registry) -> str:
    """session_id를 워커/봇 registry에서 instance_id로 해석. 미등록 시 session_id 반환."""
    for reg in (instance_registry, bot_registry):
        try:
            return reg.resolve_session(session_id).instance_id
        except NotRegisteredError:
            continue
    return session_id


def _schema_conflict_payload(schema_name: str, reason: str, attempted_by: str) -> dict:
    return {
        "msgtype": "schema_conflict",
        "schema_name": schema_name,
        "reason": reason,
        "attempted_by": attempted_by,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _session_id_from_ctx(ctx: Context) -> str:
    try:
        request = ctx.request_context.request
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            return session_id
    except (AttributeError, ValueError, LookupError):
        pass
    raise RuntimeError("Cannot determine MCP session id from Context (no active streamable-HTTP request?)")


def _session_is_bot(bot_registry: BotRegistry, session_id: str) -> bool:
    try:
        bot_registry.resolve_session(session_id)
        return True
    except NotRegisteredError:
        return False


def create_agora_app(
    agora_dir: Path,
    instance_registry: InstanceRegistry,
    schema_registry: SchemaRegistry,
    bot_registry: BotRegistry,
    comm_matrix: CommMatrix,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
    file_store: Any = None,
    file_policy: Any = None,
    add_wait: bool = False,
) -> FastMCP:
    """FastMCP 앱을 생성한다 (v3: messaging-only).

    add_wait: True면 blocking long-poll 도구 agora.wait_notify를 MCP 도구로
    등록한다. 기본 False — 채널 어댑터·봇 SDK는 GET /channel/wait HTTP
    엔드포인트를 쓰므로 워커 도구 표면에서 이 도구를 들어낸다 (--add-wait는
    레거시·디버깅용 옵트인).
    """

    mcp = FastMCP(
        name="AgentAgora",
        host="127.0.0.1",
        port=port,
    )
    mcp._agora_file_store = file_store  # type: ignore[attr-defined]
    mcp._agora_file_policy = file_policy  # type: ignore[attr-defined]

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
        ctx: Context,
        name: str,
        body: dict,
        kind: Literal["conversation", "bot-task"],
        purpose: str,
    ) -> str:
        """Register a schema. Immutable — 동일 이름 다른 body는 거부.
        body에 msgtype property 필수 (결정 20). 호출자가 ref holder가 된다."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        # 호출자 instance_id 해석 — 워커/봇 모두 허용, 미등록이면 session_id를 holder로.
        try:
            holder = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError:
            try:
                holder = bot_registry.resolve_session(session_id).instance_id
            except NotRegisteredError:
                holder = session_id
        try:
            schema_registry.register(name, body, kind=kind, purpose=purpose,
                                     registered_by=holder)
            persistence.save_schema(name, body, kind=kind, purpose=purpose,
                                    registered_by=holder)
        except AgoraError as e:
            if e.code == "schema_immutable":
                await dispatcher.system_notify(holder,
                    _schema_conflict_payload(name, str(e), holder))
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
        # 봇 재등록이면 옛 스키마 ref를 먼저 해제 (새 inline/subscribe로 재획득).
        try:
            prior = bot_registry.resolve_instance_id(instance_id)
            schema_registry.release_holder(prior.instance_id)
        except NotRegisteredError:
            pass
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
                    await dispatcher.system_notify(instance_id,
                        _schema_conflict_payload(
                            name,
                            f"schema '{name}' already registered with a different body",
                            instance_id))
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
            # 구독 schema에 subscriber ref 획득
            for s in info.subscribe_schemas:
                schema_registry.acquire_ref(s, instance_id)
        except AgoraError as e:
            schema_registry.release_holder(instance_id)
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
        # 해제 전에 holder id를 잡아 스키마 ref를 해제한다.
        for reg in (instance_registry, bot_registry):
            try:
                holder = reg.resolve_session(session_id).instance_id
                schema_registry.release_holder(holder)
            except NotRegisteredError:
                pass
        instance_registry.unregister_session(session_id)
        bot_registry.unregister_session(session_id)
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
                "cwd": i.cwd,
                "registered_at": i.registered_at,
                "inbox_depth": m.get("queue_depth", 0),
                "in_flight": m.get("in_flight", 0),
                "last_seen_at": i.last_seen_at,
                "wait_mode": i.wait_mode,
                "accepting": i.accepting,
            })
        return json.dumps({"instances": items}, ensure_ascii=False)

    @mcp.tool(name="agora.bots")
    async def agora_bots() -> str:
        """List registered bots only (결정 16 — workers excluded)."""
        items = [
            {
                "instance_id": b.instance_id, "description": b.description,
                "bot_mode": b.bot_mode,
                "subscribe_schemas": list(b.subscribe_schemas),
                "emit_schemas": list(b.emit_schemas),
                "registered_at": b.registered_at, "last_seen_at": b.last_seen_at,
            }
            for b in bot_registry.list_bots()
        ]
        return json.dumps({"bots": items}, ensure_ascii=False)

    @mcp.tool(name="agora.find")
    async def agora_find(query: str) -> str:
        """Search workers AND bots. Each result tagged kind: 'worker' | 'bot'."""
        if not query:
            return json.dumps({"results": []})
        q = query.lower()
        results = []
        for i in instance_registry.list_instances():
            if q in i.instance_id.lower() or q in i.role.lower() or q in i.description.lower():
                results.append({
                    "kind": "worker", "instance_id": i.instance_id,
                    "role": i.role, "description": i.description,
                    "cwd": i.cwd,
                    "registered_at": i.registered_at,
                })
        for b in bot_registry.list_bots():
            hay = (b.instance_id + " " + b.description + " "
                   + " ".join(b.subscribe_schemas)).lower()
            if q in hay:
                results.append({
                    "kind": "bot", "instance_id": b.instance_id,
                    "description": b.description, "bot_mode": b.bot_mode,
                    "subscribe_schemas": list(b.subscribe_schemas),
                    "registered_at": b.registered_at,
                })
        return json.dumps({"results": results}, ensure_ascii=False)

    @mcp.tool(name="agora.cwd")
    async def agora_cwd(instance_id: str) -> str:
        """Return the working directory (cwd) of a registered worker instance."""
        try:
            info = instance_registry.resolve_instance_id(instance_id)
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"instance_id": info.instance_id, "cwd": info.cwd},
                          ensure_ascii=False)

    @mcp.tool(name="agora.dispatch")
    async def agora_dispatch(
        ctx: Context,
        payload: Any,
        target: str | None = None,
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
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        if _session_is_bot(bot_registry, session_id):
            return json.dumps({"error": "[agora] 봇은 agora.dispatch를 호출할 수 없습니다. agora.bot_emit을 쓰세요."})
        try:
            source = instance_registry.resolve_session(session_id).instance_id
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
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        if _session_is_bot(bot_registry, session_id):
            return json.dumps({"error": "[agora] 봇은 agora.broadcast를 호출할 수 없습니다. agora.bot_emit을 쓰세요."})
        try:
            source = instance_registry.resolve_session(session_id).instance_id
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

    @mcp.tool(name="agora.bot_emit")
    async def agora_bot_emit(
        ctx: Context,
        payload: dict,
        in_reply_to: str | None = None,
        target: str | None = None,
    ) -> str:
        """Emit a bot result. Bots only.

        target 지정 시 해당 워커/봇 인박스에 직접 전달 (라우팅 봇용).
        in_reply_to 지정 시 원 caller로 회신.
        둘 다 미지정 시 payload msgtype 구독 봇에 schema-routed fan-out (결정 25).
        target과 in_reply_to는 동시에 지정 불가.
        """
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        try:
            bot = bot_registry.resolve_session(session_id)
        except NotRegisteredError:
            return json.dumps({"error": str(AgoraError("bot_emit_not_a_bot"))})
        try:
            result = await dispatcher.bot_emit(
                source=bot.instance_id, payload=payload,
                in_reply_to=in_reply_to, target=target)
            return json.dumps({"status": "ok", **result}, ensure_ascii=False)
        except (ValueError, NotRegisteredError) as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    @mcp.tool(name="agora.flush")
    async def agora_flush(
        ctx: Context,
        from_sources: list[str] | None = None,
        sort: Literal["fifo", "priority"] = "priority",
        by_conversation: str | None = None,
    ) -> str:
        """Drain all commands currently queued for this instance and return immediately (non-blocking).

        Returns whatever is in the inbox right now — does not wait for new messages.
        Call this after receiving a channel notification to drain your inbox.

        Default sort='priority': the inbox is ordered by comm-matrix edge weight
        (descending), then message priority (high>normal>low), then created_at.
        sort='fifo' falls back to (created_at asc, command_id asc).
        from_sources / by_conversation: AND-combined filters; unmatched envelopes stay queued.
        The caller MUST be registered before calling flush.
        """
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        try:
            who = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError:
            try:
                who = bot_registry.resolve_session(session_id).instance_id
            except NotRegisteredError as e:
                return json.dumps({"error": str(e)})

        try:
            commands = await dispatcher.flush(
                instance_id=who,
                from_sources=from_sources,
                sort=sort,
                by_conversation=by_conversation,
            )
            return json.dumps({"commands": commands}, ensure_ascii=False)
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})

    if add_wait:
        @mcp.tool(name="agora.wait_notify")
        async def agora_wait_notify(instance_id: str, timeout_ms: int | None = None) -> str:
            """Non-destructive long-poll — block until instance_id has inbound,
            then return {instance_id, pending, sources} without draining the queue.
            Opt-in via --add-wait. The agora-channel adapter and AgoraBot SDK use
            the GET /channel/wait HTTP endpoint instead. instance_id need not be
            registered."""
            try:
                result = await dispatcher.wait_notify(
                    instance_id=instance_id, timeout_ms=timeout_ms)
                return json.dumps(result, ensure_ascii=False)
            except DispatcherClosed:
                return json.dumps({"error": "server is shutting down"})

    if file_store is not None:
        @mcp.tool(name="agora.share_file")
        async def agora_share_file(ctx: Context, path: str) -> str:
            """Share a local file through the store. Returns a handle to dispatch
            in a file_share message."""
            try:
                session_id = _session_id_from_ctx(ctx)
            except RuntimeError as e:
                return json.dumps({"error": f"Session context unavailable: {e}"})
            caller = _resolve_caller(session_id, instance_registry, bot_registry)
            name = os.path.basename(path)
            if file_policy is not None and not file_policy.can_upload(caller, name):
                return json.dumps({"error": str(AgoraError(
                    "file_upload_denied", worker=caller, name=name))})
            try:
                handle = file_store.store_path(Path(path), name, caller)
            except (AgoraError, OSError) as e:
                return json.dumps({"error": str(e)})
            return json.dumps({"status": "ok", "handle": handle}, ensure_ascii=False)

        @mcp.tool(name="agora.fetch_file")
        async def agora_fetch_file(ctx: Context, file_id: str, dest_path: str) -> str:
            """Fetch a shared file from the store into dest_path."""
            try:
                session_id = _session_id_from_ctx(ctx)
            except RuntimeError as e:
                return json.dumps({"error": f"Session context unavailable: {e}"})
            caller = _resolve_caller(session_id, instance_registry, bot_registry)
            meta = file_store.meta(file_id)
            if meta is None:
                return json.dumps({"error": str(AgoraError("unknown_file", file_id=file_id))})
            if file_policy is not None and not file_policy.can_download(caller, meta["name"]):
                return json.dumps({"error": str(AgoraError(
                    "file_download_denied", worker=caller, name=meta["name"]))})
            src = file_store.path_of(file_id)
            if src is None:
                return json.dumps({"error": str(AgoraError("unknown_file", file_id=file_id))})
            try:
                shutil.copyfile(src, dest_path)
            except OSError as e:
                return json.dumps({"error": f"fetch failed: {e}"})
            return json.dumps({"status": "ok", "name": meta["name"], "size": meta["size"]})

    return mcp
