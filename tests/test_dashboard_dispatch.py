"""dashboard_routes — dispatch·broadcast·operator inbox 통합 테스트."""
from __future__ import annotations

import contextlib
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dashboard_auth import DashboardAuthMiddleware
from agent_agora.dashboard_routes import register
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry


def _auth(user: str) -> dict:
    return {"X-Agora-Operator-User": user}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def real_server_app(tmp_path):
    """Full Starlette app wired with dispatcher + dashboard_routes + trust-mode auth.

    Uses Starlette lifespan to start/stop the AsyncWriteQueue worker task so that
    dispatcher.dispatch() persistence writes complete (rather than hanging on the future).
    """
    reg = InstanceRegistry()
    bot_reg = BotRegistry()
    cm = CommMatrix()
    schema_reg = make_schema_registry()
    db_path = tmp_path / "agora_test.db"
    persistence = Persistence(db_path)
    persistence.migrate()
    write_queue = AsyncWriteQueue(persistence)

    dispatcher = Dispatcher(
        reg, persistence, write_queue,
        schema_registry=schema_reg,
        bot_registry=bot_reg,
        comm_matrix=cm,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with write_queue:
            yield

    app = Starlette(
        lifespan=lifespan,
        middleware=[
            Middleware(
                DashboardAuthMiddleware,
                mode="trust",
                tokens={},
                protected_paths=["/dashboard/dispatch", "/dashboard/broadcast",
                                  "/dashboard/operator",
                                  "/dashboard/conversation",
                                  "/dashboard/instance",
                                  "/dashboard/schemas"],
            )
        ]
    )
    register(
        app,
        dispatcher=dispatcher,
        instance_registry=reg,
        bot_registry=bot_reg,
        comm_matrix=cm,
        persistence=persistence,
        write_queue=write_queue,
        schema_registry=schema_reg,
    )

    # Expose internals on the app for fixtures to use
    app.state.dispatcher = dispatcher
    app.state.instance_registry = reg
    app.state.write_queue = write_queue
    app.state.persistence = persistence

    return app


@pytest.fixture
def dashboard_client(real_server_app):
    """TestClient wrapped in lifespan context (starts AsyncWriteQueue worker)."""
    with TestClient(real_server_app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture
def register_worker(real_server_app):
    """Returns a helper that registers a worker into the app's instance_registry."""
    reg: InstanceRegistry = real_server_app.state.instance_registry

    def _register(instance_id: str, role: str = "coder") -> None:
        reg.register(f"sess-{instance_id}", instance_id, role=role,
                     description=f"test worker {instance_id}")

    return _register


@pytest.fixture
def persistence(real_server_app) -> Persistence:
    """Direct access to the app's Persistence handle for round-trip assertions."""
    return real_server_app.state.persistence


@pytest.fixture
def post_reply_from_worker(real_server_app):
    """Returns a helper that inserts a message directly into persistence.

    Bypasses the async dispatcher entirely to avoid event loop bridging issues
    in synchronous TestClient tests. Writes a row directly to the messages table
    (and a matching conversation row) so that fetch_messages_for sees it.
    """
    import json as _json
    import uuid as _uuid
    import datetime as _datetime
    persistence = real_server_app.state.persistence

    def _post(source: str, target: str, payload: dict,
               conversation_id: str | None = None) -> dict:
        if isinstance(payload, dict) and "msgtype" not in payload:
            payload = {**payload, "msgtype": "status_report"}

        cmd_id = str(_uuid.uuid4())
        conv_id = conversation_id or str(_uuid.uuid4())
        now = _datetime.datetime.now(_datetime.timezone.utc).isoformat()

        conn = persistence.conn
        conn.execute(
            "INSERT OR IGNORE INTO conversations "
            "(conversation_id, status, started_at, last_message_at, kind) "
            "VALUES (?, 'open', ?, ?, 'direct')",
            (conv_id, now, now),
        )
        conn.execute(
            "INSERT INTO messages "
            "(command_id, target, conversation_id, source, created_at, "
            "expect_result, delivered_as, dispatch_kind, closing, priority, "
            "priority_rank, payload, reply_only) "
            "VALUES (?, ?, ?, ?, ?, 0, 'primary', 'direct', 0, 'normal', 1, ?, 0)",
            (cmd_id, target, conv_id, source, now, _json.dumps(payload)),
        )
        return {"command_id": cmd_id, "conversation_id": conv_id}

    return _post


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dispatch_to_specific_worker(dashboard_client, register_worker, persistence):
    register_worker("W1", role="coder")
    r = dashboard_client.post(
        "/dashboard/dispatch",
        headers=_auth("alice"),
        json={"to": "W1", "schema": "operator_message", "payload": {"text": "hi"},
              "reply_only": False},
    )
    assert r.status_code == 201
    body = r.json()
    assert "message_id" in body
    assert "conversation_id" in body
    # Default reply_only=False must round-trip through dispatch → persistence as False.
    msgs = persistence.fetch_messages_for(recipient="W1", include_acked=True)
    matching = [m for m in msgs if m["message_id"] == body["message_id"]]
    assert len(matching) == 1
    assert matching[0]["reply_only"] is False


def test_dispatch_to_nonexistent_worker_404(dashboard_client):
    r = dashboard_client.post(
        "/dashboard/dispatch",
        headers=_auth("alice"),
        json={"to": "DoesNotExist", "schema": "operator_message", "payload": {},
              "reply_only": False},
    )
    assert r.status_code == 404


def test_broadcast_to_multiple_workers(dashboard_client, register_worker):
    register_worker("W1")
    register_worker("W2")
    r = dashboard_client.post(
        "/dashboard/broadcast",
        headers=_auth("alice"),
        json={"targets": ["W1", "W2"], "schema": "operator_message",
              "payload": {"text": "all"}, "reply_only": True},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 2
    assert all("message_id" in res for res in results)


def test_broadcast_empty_targets_422(dashboard_client):
    r = dashboard_client.post(
        "/dashboard/broadcast",
        headers=_auth("alice"),
        json={"targets": [], "schema": "operator_message", "payload": {},
              "reply_only": False},
    )
    assert r.status_code == 422


def test_operator_inbox_empty_initially(dashboard_client):
    r = dashboard_client.get("/dashboard/operator/inbox", headers=_auth("alice"))
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_operator_inbox_receives_reply(dashboard_client, register_worker, post_reply_from_worker):
    register_worker("W1")
    # operator -> worker dispatch
    dashboard_client.post(
        "/dashboard/dispatch",
        headers=_auth("alice"),
        json={"to": "W1", "schema": "operator_message", "payload": {"q": 1},
              "reply_only": True},
    )
    # worker -> operator reply (direct dispatcher call)
    post_reply_from_worker("W1", "operator:alice", {"answer": 42})

    r = dashboard_client.get("/dashboard/operator/inbox", headers=_auth("alice"))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "W1"
    assert msgs[0]["payload"]["answer"] == 42


def test_operator_inbox_ack_removes_from_default_view(
    dashboard_client, register_worker, post_reply_from_worker
):
    register_worker("W1")
    dashboard_client.post(
        "/dashboard/dispatch",
        headers=_auth("alice"),
        json={"to": "W1", "schema": "operator_message", "payload": {},
              "reply_only": True},
    )
    post_reply_from_worker("W1", "operator:alice", {"a": 1})

    msgs = dashboard_client.get(
        "/dashboard/operator/inbox", headers=_auth("alice")
    ).json()["messages"]
    assert len(msgs) == 1
    msg_id = msgs[0]["message_id"]

    r = dashboard_client.post(
        "/dashboard/operator/inbox/ack",
        headers=_auth("alice"),
        json={"message_ids": [msg_id]},
    )
    assert r.status_code == 200

    # default view: message is gone
    msgs2 = dashboard_client.get(
        "/dashboard/operator/inbox", headers=_auth("alice")
    ).json()["messages"]
    assert len(msgs2) == 0

    # include_acked=true: message reappears
    msgs3 = dashboard_client.get(
        "/dashboard/operator/inbox?include_acked=true", headers=_auth("alice")
    ).json()["messages"]
    assert len(msgs3) == 1
    assert msgs3[0]["message_id"] == msg_id


def test_dispatch_reply_only_persisted(dashboard_client, register_worker, persistence):
    """reply_only=True from the request body must reach the DB."""
    register_worker("W1", role="coder")
    r = dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message",
        "payload": {"q": 1}, "reply_only": True,
    })
    assert r.status_code == 201
    msgs = persistence.fetch_messages_for(recipient="W1", include_acked=True)
    assert len(msgs) >= 1
    matching = [m for m in msgs if m.get("source") == "operator:alice"]
    assert len(matching) >= 1
    # fetch_messages_for converts INTEGER reply_only to bool — assert both forms.
    assert matching[0]["reply_only"] is True or matching[0]["reply_only"] == 1


def test_conversation_thread_returns_all_messages(dashboard_client, register_worker, post_reply_from_worker):
    register_worker("W1")
    sent = dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message", "payload": {"q": 1},
        "reply_only": False,
    }).json()
    conv_id = sent["conversation_id"]
    post_reply_from_worker("W1", "operator:alice", {"answer": 42}, conversation_id=conv_id)

    r = dashboard_client.get(f"/dashboard/conversation/{conv_id}", headers=_auth("alice"))
    assert r.status_code == 200
    thread = r.json()["messages"]
    assert len(thread) == 2
    assert thread[0]["payload"]["q"] == 1
    assert thread[1]["payload"]["answer"] == 42


def test_instance_inbox_returns_worker_inbox(dashboard_client, register_worker):
    register_worker("W1")
    dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message", "payload": {"task": "x"},
        "reply_only": False,
    })
    r = dashboard_client.get("/dashboard/instance/W1/inbox", headers=_auth("alice"))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) >= 1
    # The dispatched message's payload has msgtype injected by dispatch_endpoint.
    assert any(m.get("payload", {}).get("task") == "x" for m in msgs)


def test_schemas_catalog(dashboard_client):
    r = dashboard_client.get("/dashboard/schemas", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()
    assert "schemas" in body
    assert isinstance(body["schemas"], list)
    # At least one default schema must be registered.
    assert len(body["schemas"]) > 0
    assert "id" in body["schemas"][0]
    assert "schema" in body["schemas"][0]
