"""dashboard_routes — dispatch·broadcast·operator inbox 통합 테스트."""
from __future__ import annotations

import contextlib
import time
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dashboard import (
    DashboardAuthMiddleware, EventBroker, HealthCollector,
    register, DASHBOARD_PROTECTED_PATHS,
)
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry


def _auth(user: str) -> dict:
    return {"X-Agora-Operator-User": user}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# single source — see agent_agora.dashboard_routes.DASHBOARD_PROTECTED_PATHS
_PROTECTED_PATHS = DASHBOARD_PROTECTED_PATHS


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

    health = HealthCollector(
        started_at=time.time(),
        db_path=db_path,
        persistence=write_queue,
        sweeper=dispatcher.sweeper,
    )
    event_broker = EventBroker(max_queue=100)
    event_broker.attach_to_dispatcher(dispatcher)

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
                protected_paths=_PROTECTED_PATHS,
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
        health_collector=health,
        event_broker=event_broker,
        auth_mode="trust",
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


def test_dashboard_data_comm_matrix_includes_cycles(dashboard_client):
    """comm_matrix.cycles()(라우팅 루프 진단)가 /dashboard/data에 노출된다."""
    r = dashboard_client.get("/dashboard/data", headers=_auth("alice"))
    assert r.status_code == 200
    cm = r.json()["comm_matrix"]
    assert "cycles" in cm and isinstance(cm["cycles"], list)


def test_coverage_endpoint_returns_structure(dashboard_client, register_worker):
    """GET /dashboard/coverage/{command_id} — expect_result 응답 커버리지 구조 노출."""
    register_worker("W1")
    d = dashboard_client.post(
        "/dashboard/dispatch", headers=_auth("alice"),
        json={"to": "W1", "schema": "operator_message", "payload": {}}).json()
    cmd = d["message_id"]
    r = dashboard_client.get(f"/dashboard/coverage/{cmd}", headers=_auth("alice"))
    assert r.status_code == 200
    cov = r.json()
    assert cov["command_id"] == cmd
    for key in ("pending", "responded", "deadline_ts", "expired"):
        assert key in cov


def test_schemas_endpoint_includes_meta_and_refs(dashboard_client):
    """스키마 explorer 백엔드 — /dashboard/schemas가 kind/purpose/registered_by/ref_count
    메타를 함께 반환하되, 기존 dispatch dropdown용 id/schema도 보존(하위호환)."""
    r = dashboard_client.get("/dashboard/schemas", headers=_auth("alice"))
    assert r.status_code == 200
    schemas = r.json()["schemas"]
    assert schemas, "스키마 카탈로그가 비어있지 않아야 함(번들 + test_any)"
    s0 = schemas[0]
    for key in ("id", "name", "kind", "purpose", "registered_by", "ref_count", "schema"):
        assert key in s0, f"스키마 항목에 '{key}' 누락"


def test_dispatch_response_surfaces_deliveries(dashboard_client, register_worker):
    """dispatch 응답이 deliveries/skipped_full/target_inbox_depth_after를 통과시킨다 —
    운영자가 fan-out 결과(만석 skip 포함)를 즉시 인지."""
    register_worker("W1")
    r = dashboard_client.post(
        "/dashboard/dispatch", headers=_auth("alice"),
        json={"to": "W1", "schema": "operator_message", "payload": {}, "reply_only": False})
    assert r.status_code == 201
    body = r.json()
    assert "deliveries" in body and "skipped_full" in body
    assert "target_inbox_depth_after" in body
    assert any(d["target"] == "W1" and d["status"] == "delivered" for d in body["deliveries"])


def test_broadcast_results_surface_deliveries(dashboard_client, register_worker):
    register_worker("W1")
    r = dashboard_client.post(
        "/dashboard/broadcast", headers=_auth("alice"),
        json={"targets": ["W1"], "schema": "operator_message", "payload": {}, "reply_only": False})
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert "deliveries" in res and "skipped_full" in res


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


def test_data_includes_server_health(dashboard_client):
    r = dashboard_client.get("/dashboard/data", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()
    assert "server" in body
    health = body["server"]
    assert "uptime_seconds" in health
    assert "db_size_bytes" in health
    assert "write_queue_depth" in health
    assert "sweeper_runs_total" in health


def test_auth_mode_returns_current_mode(dashboard_client):
    """/dashboard/auth-mode는 인증 없이 접근 가능."""
    # 헤더 없이도 200
    r = dashboard_client.get("/dashboard/auth-mode")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("trust", "token")


def test_stream_endpoint_emits_initial_snapshot(tmp_path):
    """SSE 첫 응답으로 data_snapshot 이벤트 1회 push.

    httpx.ASGITransport은 응답 바디를 전부 버퍼링하므로 무한 SSE 스트림과 호환되지 않는다.
    대신 ASGI 레벨에서 생성기를 직접 구동해 첫 이벤트를 검증한다.

    검증 항목:
    1. /dashboard/stream 라우트가 등록됐는지 확인
    2. build_dashboard_data 스냅샷이 SSE data: 형식으로 emit되는지 확인
    3. 첫 이벤트 type이 "data_snapshot"인지 확인
    """
    import asyncio
    import json as _json
    import time as _time

    async def _run_asgi_direct():
        reg = InstanceRegistry()
        bot_reg = BotRegistry()
        cm = CommMatrix()
        schema_reg = make_schema_registry()
        db_path = tmp_path / "sse_test.db"
        persistence = Persistence(db_path)
        persistence.migrate()
        write_queue = AsyncWriteQueue(persistence)

        dispatcher = Dispatcher(
            reg, persistence, write_queue,
            schema_registry=schema_reg,
            bot_registry=bot_reg,
            comm_matrix=cm,
        )

        health = HealthCollector(
            started_at=_time.time(),
            db_path=db_path,
            persistence=write_queue,
            sweeper=dispatcher.sweeper,
        )
        event_broker = EventBroker(max_queue=100)

        app = Starlette(
            middleware=[
                Middleware(
                    DashboardAuthMiddleware,
                    mode="trust",
                    tokens={},
                    protected_paths=["/dashboard/stream"],
                )
            ]
        )
        register(
            app,
            dispatcher=dispatcher,
            instance_registry=reg,
            bot_registry=bot_reg,
            comm_matrix=cm,
            health_collector=health,
            event_broker=event_broker,
            auth_mode="trust",
        )

        # /dashboard/stream 라우트가 등록됐는지 확인
        route_paths = [getattr(r, "path", None) for r in app.router.routes]
        assert "/dashboard/stream" in route_paths, f"stream route missing: {route_paths}"

        # ASGI 스코프를 직접 구성해 SSE 생성기를 구동
        # httpx.ASGITransport 대신 직접 ASGI 레이어를 호출한다
        chunks_received = []
        stop_event = asyncio.Event()
        status_code_holder = []
        headers_holder = []

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "headers": [(b"x-agora-operator-user", b"alice")],
            "scheme": "http",
            "path": "/dashboard/stream",
            "raw_path": b"/dashboard/stream",
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
        }

        request_complete = False

        async def receive():
            nonlocal request_complete
            if not request_complete:
                request_complete = True
                return {"type": "http.request", "body": b"", "more_body": False}
            # 첫 이벤트 수신 후 disconnect 신호를 반환한다
            await stop_event.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                status_code_holder.append(message["status"])
                headers_holder.append(dict(message.get("headers", [])))
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    chunks_received.append(body.decode("utf-8"))
                    combined = "".join(chunks_received)
                    if "\n\n" in combined:
                        stop_event.set()  # 첫 완전한 이벤트 수신 → disconnect 신호

        try:
            await asyncio.wait_for(app(scope, receive, send), timeout=5.0)
        except asyncio.TimeoutError:
            pass  # 정상 — SSE 스트림은 무한하므로 timeout이 예상됨

        return {
            "status": status_code_holder[0] if status_code_holder else None,
            "body": "".join(chunks_received),
        }

    result = asyncio.run(_run_asgi_direct())

    assert result["status"] == 200
    first_event = result["body"]
    assert "data:" in first_event
    data_line = next((line for line in first_event.split("\n")
                      if line.startswith("data:")), None)
    assert data_line is not None
    parsed = _json.loads(data_line[len("data:"):].strip())
    assert parsed["type"] == "data_snapshot"
