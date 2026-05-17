"""팀 대시보드 라우트 테스트."""
from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.dashboard_routes import register, build_dashboard_data
from _helpers import make_schema_registry


def _deps(tmp_path):
    reg = InstanceRegistry()
    reg.register("sess-Inst1", "Inst1", role="orchestrator", description="PM")
    reg.register("sess-Coder1", "Coder1", role="coder", description="코더")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    return reg, persistence


def test_build_dashboard_data_shape(tmp_path):
    reg, persistence = _deps(tmp_path)
    bot_registry = BotRegistry()
    cm = CommMatrix()
    queue = AsyncWriteQueue(persistence)
    d = Dispatcher(reg, persistence, queue, schema_registry=make_schema_registry(),
                   bot_registry=bot_registry, comm_matrix=cm)
    data = build_dashboard_data(
        dispatcher=d, instance_registry=reg, bot_registry=bot_registry, comm_matrix=cm)
    assert set(data) == {"generated_at", "summary", "instances", "bots",
                         "conversations", "comm_matrix"}
    assert data["summary"]["instances"] == 2
    assert {i["instance_id"] for i in data["instances"]} == {"Inst1", "Coder1"}
    assert data["comm_matrix"]["active"] is False
    inst = next(i for i in data["instances"] if i["instance_id"] == "Inst1")
    assert set(inst) >= {"instance_id", "role", "inbox_depth", "in_flight",
                         "last_seen_at", "accepting"}


def test_data_route_returns_json(tmp_path):
    reg, persistence = _deps(tmp_path)
    bot_registry = BotRegistry()
    cm = CommMatrix()
    queue = AsyncWriteQueue(persistence)
    d = Dispatcher(reg, persistence, queue, schema_registry=make_schema_registry(),
                   bot_registry=bot_registry, comm_matrix=cm)
    app = Starlette()
    register(app, dispatcher=d, instance_registry=reg,
             bot_registry=bot_registry, comm_matrix=cm)
    r = TestClient(app).get("/dashboard/data")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["instances"] == 2


def test_dashboard_route_serves_html(tmp_path):
    reg, persistence = _deps(tmp_path)
    bot_registry = BotRegistry()
    cm = CommMatrix()
    queue = AsyncWriteQueue(persistence)
    d = Dispatcher(reg, persistence, queue, schema_registry=make_schema_registry(),
                   bot_registry=bot_registry, comm_matrix=cm)
    app = Starlette()
    register(app, dispatcher=d, instance_registry=reg,
             bot_registry=bot_registry, comm_matrix=cm)
    r = TestClient(app).get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "/dashboard/data" in r.text  # JS가 폴링하는 엔드포인트
