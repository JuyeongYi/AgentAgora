"""Static asset mount 검증."""
from __future__ import annotations

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "agent_agora" / "dashboard_static"


def test_vendor_libraries_present():
    assert (STATIC_DIR / "vendor" / "tabulator.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "tabulator.min.css").is_file()
    assert (STATIC_DIR / "vendor" / "jsoneditor.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "jsoneditor.min.css").is_file()


@pytest.mark.xfail(reason="Tasks 13-18 populate JS modules")
def test_js_modules_present():
    for name in ("api.js", "stream.js", "login.js", "dashboard.js",
                 "health.js", "dispatch.js", "inbox.js", "drilldown.js"):
        assert (STATIC_DIR / "js" / name).is_file(), f"missing js/{name}"


def test_dashboard_css_present():
    assert (STATIC_DIR / "css" / "dashboard.css").is_file()


def test_static_route_served(real_server_app):
    """/dashboard/static/* 가 StaticFiles로 mount되어 응답 (404 not 500/missing route)."""
    from starlette.testclient import TestClient
    with TestClient(real_server_app, raise_server_exceptions=True) as client:
        # The static_dir exists (created in Task 12) but the file doesn't — 404 is correct.
        r = client.get("/dashboard/static/nonexistent_file_for_test.txt")
        # Must be 404 (StaticFiles handles it) — NOT 500 or connection error.
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Fixtures (local — mirrors test_dashboard_dispatch.py setup without auth)
# ---------------------------------------------------------------------------

import contextlib
from starlette.applications import Starlette
from starlette.middleware import Middleware
from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dashboard_auth import DashboardAuthMiddleware
from agent_agora.dashboard_events import EventBroker
from agent_agora.dashboard_health import HealthCollector
from agent_agora.dashboard_routes import register
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry


def _make_schema_registry():
    from agent_agora.schemas import SchemaRegistry
    return SchemaRegistry()


@pytest.fixture
def real_server_app(tmp_path):
    """Full Starlette app with health_collector + event_broker wired."""
    import time
    reg = InstanceRegistry()
    bot_reg = BotRegistry()
    cm = CommMatrix()
    schema_reg = _make_schema_registry()
    db_path = tmp_path / "agora_static_test.db"
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

    PROTECTED_PATHS = [
        "/dashboard/data",
        "/dashboard/dispatch",
        "/dashboard/broadcast",
        "/dashboard/operator",
        "/dashboard/conversation",
        "/dashboard/instance",
        "/dashboard/schemas",
        "/dashboard/stream",
    ]

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
                protected_paths=PROTECTED_PATHS,
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

    app.state.dispatcher = dispatcher
    app.state.instance_registry = reg

    return app
