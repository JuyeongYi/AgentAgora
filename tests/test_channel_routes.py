"""GET /channel/wait HTTP 엔드포인트 테스트."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.registry import BotRegistry
from agent_agora.http.channel_routes import register
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


@pytest.fixture
async def client(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 4):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=300)
        app = Starlette()
        register(app, dispatcher=dispatcher)
        yield TestClient(app), dispatcher


@pytest.mark.asyncio
async def test_wait_returns_snapshot_when_queue_nonempty(client):
    tc, dispatcher = client
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    r = tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 200})
    assert r.status_code == 200
    body = r.json()
    assert body == {"instance_id": "Inst2", "pending": 1, "sources": ["Inst1"]}


@pytest.mark.asyncio
async def test_wait_timeout_returns_empty_snapshot(client):
    tc, dispatcher = client
    r = tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 50})
    assert r.status_code == 200
    assert r.json() == {"instance_id": "Inst2", "pending": 0, "sources": []}


@pytest.mark.asyncio
async def test_wait_missing_instance_id_is_400(client):
    tc, _ = client
    r = tc.get("/channel/wait", params={"timeout_ms": 50})
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.asyncio
async def test_wait_bad_timeout_is_400(client):
    tc, _ = client
    r = tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": "soon"})
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.asyncio
async def test_wait_is_non_destructive(client):
    tc, dispatcher = client
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 100})
    drained = await dispatcher.flush("Inst2")
    assert len(drained) == 1


@pytest.mark.asyncio
async def test_wait_omitted_timeout_uses_server_default(client):
    tc, dispatcher = client
    # default_timeout_ms=300 → no timeout_ms param still returns within ~300ms
    r = tc.get("/channel/wait", params={"instance_id": "Inst2"})
    assert r.status_code == 200
    assert r.json()["pending"] == 0


@pytest.mark.asyncio
async def test_wait_timeout_clamped_to_upper_bound():
    """An excessive timeout_ms is clamped to the upper bound (caps unbounded
    waits). Omitted timeout still resolves to the server default (separate test)."""
    seen = {}

    class _FakeDispatcher:
        async def wait_notify(self, *, instance_id, timeout_ms):
            seen["timeout_ms"] = timeout_ms
            return {"instance_id": instance_id, "pending": 0, "sources": []}

    app = Starlette()
    register(app, dispatcher=_FakeDispatcher())
    tc = TestClient(app)
    r = tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 999999})
    assert r.status_code == 200
    assert seen["timeout_ms"] == 60000
