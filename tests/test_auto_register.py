from __future__ import annotations

import pytest

from agent_agora.auto_register import AutoRegisterMiddleware
from agent_agora.registry import InstanceRegistry, NotRegisteredError


@pytest.fixture
def reg():
    return InstanceRegistry()


async def _send(_msg):
    pass


async def _receive():
    return {"type": "http.request"}


async def _noop_app(scope, receive, send):
    pass


async def test_auto_registers_when_both_headers_present(reg):
    inner_called = {"v": False}

    async def app(scope, receive, send):
        inner_called["v"] = True

    mw = AutoRegisterMiddleware(app=app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-1"),
            (b"x-agora-instance-id", b"Inst1"),
            (b"x-agora-role", b"orchestrator"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-1")
    assert info.instance_id == "Inst1"
    assert info.role == "orchestrator"
    assert inner_called["v"] is True


async def test_no_register_without_instance_id_header(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [(b"mcp-session-id", b"sess-2")],
    }
    await mw(scope, _receive, _send)
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("sess-2")


async def test_no_register_without_session_id_header(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [(b"x-agora-instance-id", b"Inst1")],
    }
    await mw(scope, _receive, _send)
    assert reg.list_instances() == []


async def test_updates_when_role_or_instance_changes(reg):
    """If a session re-presents itself with a different instance_id or role,
    the registry should be updated to match the latest headers."""
    reg.register(session_id="sess-3", instance_id="A", role="orch")
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-3"),
            (b"x-agora-instance-id", b"OTHER"),
            (b"x-agora-role", b"different"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-3")
    assert info.instance_id == "OTHER"
    assert info.role == "different"


async def test_skips_register_when_already_matching(reg):
    """If a session arrives with the same instance_id and role that are already
    registered, the middleware should not re-register (registered_at preserved)."""
    initial = reg.register(session_id="sess-skip", instance_id="A", role="orch")
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-skip"),
            (b"x-agora-instance-id", b"A"),
            (b"x-agora-role", b"orch"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-skip")
    assert info.registered_at == initial.registered_at


async def test_default_role_is_worker_when_role_header_missing(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-4"),
            (b"x-agora-instance-id", b"InstX"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-4")
    assert info.role == "worker"


async def test_passes_through_non_http_scope(reg):
    called = {"v": False}

    async def app(scope, receive, send):
        called["v"] = True

    mw = AutoRegisterMiddleware(app=app, registry=reg)
    scope = {"type": "lifespan"}
    await mw(scope, _receive, _send)
    assert called["v"] is True
    assert reg.list_instances() == []


async def test_description_header_is_captured(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-d1"),
            (b"x-agora-instance-id", b"Reviewer"),
            (b"x-agora-role", b"reviewer"),
            (b"x-agora-description", b"Python code review specialist"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-d1")
    assert info.description == "Python code review specialist"


async def test_description_default_is_empty_when_header_missing(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-d2"),
            (b"x-agora-instance-id", b"A"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-d2")
    assert info.description == ""


async def test_description_change_triggers_update(reg):
    reg.register(session_id="sess-d3", instance_id="A", role="r", description="old")
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-d3"),
            (b"x-agora-instance-id", b"A"),
            (b"x-agora-role", b"r"),
            (b"x-agora-description", b"new"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-d3")
    assert info.description == "new"


async def test_header_lookup_is_case_insensitive(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"Mcp-Session-Id", b"sess-5"),
            (b"X-Agora-Instance-Id", b"InstC"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-5")
    assert info.instance_id == "InstC"


async def test_cwd_header_is_captured(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-cwd1"),
            (b"x-agora-instance-id", b"Worker1"),
            (b"x-agora-role", b"worker"),
            (b"x-agora-cwd", b"/home/user/project"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-cwd1")
    assert info.cwd == "/home/user/project"


async def test_cwd_default_is_empty_when_header_missing(reg):
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-cwd2"),
            (b"x-agora-instance-id", b"Worker2"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-cwd2")
    assert info.cwd == ""


async def test_cwd_change_triggers_update(reg):
    reg.register(session_id="sess-cwd3", instance_id="A", role="r", cwd="/old/path")
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-cwd3"),
            (b"x-agora-instance-id", b"A"),
            (b"x-agora-role", b"r"),
            (b"x-agora-cwd", b"/new/path"),
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-cwd3")
    assert info.cwd == "/new/path"


async def test_empty_cwd_header_does_not_clobber_registered_cwd(reg):
    """Durability: a request with NO X-Agora-CWD header must not wipe a cwd that
    was already set (by the agora.register tool or an earlier non-empty header).
    Empty header means 'no info', not 'clear cwd'."""
    reg.register(session_id="sess-cwd4", instance_id="A", role="r", cwd="/work/set")
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-cwd4"),
            (b"x-agora-instance-id", b"A"),
            (b"x-agora-role", b"r"),
            # deliberately no x-agora-cwd header → extracted cwd == ""
        ],
    }
    await mw(scope, _receive, _send)
    info = reg.resolve_session("sess-cwd4")
    assert info.cwd == "/work/set"  # preserved, NOT clobbered to ""
