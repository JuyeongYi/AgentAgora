from __future__ import annotations

import pytest

from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.session_hook import SessionCloseMiddleware


@pytest.fixture
def registry_with_a():
    reg = InstanceRegistry()
    reg.register(session_id="abc-123", instance_id="A", role="orch")
    return reg


async def test_unregisters_on_http_disconnect(registry_with_a):
    """When a client disconnects (http.disconnect arrives during the request), unregister."""
    reg = registry_with_a

    async def app(scope, receive, send):
        # Simulate an app that reads the disconnect from receive
        msg = await receive()
        assert msg["type"] == "http.disconnect"

    mw = SessionCloseMiddleware(app=app, registry=reg)

    scope = {
        "type": "http",
        "headers": [(b"mcp-session-id", b"abc-123")],
    }

    async def receive():
        return {"type": "http.disconnect"}

    sends = []
    async def send(msg):
        sends.append(msg)

    await mw(scope, receive, send)

    with pytest.raises(NotRegisteredError):
        reg.resolve_session("abc-123")


async def test_keeps_registered_on_normal_completion(registry_with_a):
    """When the request completes normally (no http.disconnect), do not unregister."""
    reg = registry_with_a

    async def app(scope, receive, send):
        # Normal app that does NOT receive http.disconnect — it just returns.
        return

    mw = SessionCloseMiddleware(app=app, registry=reg)

    scope = {
        "type": "http",
        "headers": [(b"mcp-session-id", b"abc-123")],
    }

    async def receive():
        # Should not be called for this app, but provide a sensible default
        return {"type": "http.request"}

    async def send(msg):
        pass

    await mw(scope, receive, send)

    # Still registered
    info = reg.resolve_session("abc-123")
    assert info.instance_id == "A"


async def test_no_unregister_when_session_id_header_absent(registry_with_a):
    """If the request has no session id header, middleware is a no-op for unregistration."""
    reg = registry_with_a

    async def app(scope, receive, send):
        msg = await receive()
        assert msg["type"] == "http.disconnect"

    mw = SessionCloseMiddleware(app=app, registry=reg)

    scope = {
        "type": "http",
        "headers": [],
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def send(msg):
        pass

    await mw(scope, receive, send)

    # Still registered — no session id, no targeted unregister
    info = reg.resolve_session("abc-123")
    assert info.instance_id == "A"


async def test_passes_through_non_http_scope(registry_with_a):
    """Lifespan or websocket scopes pass through without touching the registry."""
    reg = registry_with_a

    inner_called = {"value": False}
    async def app(scope, receive, send):
        inner_called["value"] = True

    mw = SessionCloseMiddleware(app=app, registry=reg)

    scope = {"type": "lifespan"}
    async def receive():
        return {"type": "lifespan.startup"}
    async def send(msg):
        pass

    await mw(scope, receive, send)
    assert inner_called["value"] is True
    # Registry untouched
    info = reg.resolve_session("abc-123")
    assert info.instance_id == "A"


async def test_unregister_on_app_exception(registry_with_a):
    """If the inner app raises after http.disconnect arrives, still unregister (finally block)."""
    reg = registry_with_a

    class _AppError(Exception):
        pass

    async def app(scope, receive, send):
        msg = await receive()
        assert msg["type"] == "http.disconnect"
        raise _AppError("boom")

    mw = SessionCloseMiddleware(app=app, registry=reg)

    scope = {
        "type": "http",
        "headers": [(b"mcp-session-id", b"abc-123")],
    }
    async def receive():
        return {"type": "http.disconnect"}
    async def send(msg):
        pass

    with pytest.raises(_AppError):
        await mw(scope, receive, send)

    with pytest.raises(NotRegisteredError):
        reg.resolve_session("abc-123")
