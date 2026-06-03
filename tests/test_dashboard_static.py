"""Static asset mount 검증."""
from __future__ import annotations

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "agent_agora" / "dashboard" / "dashboard_static"


def test_vendor_libraries_present():
    assert (STATIC_DIR / "vendor" / "tabulator.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "tabulator.min.css").is_file()
    assert (STATIC_DIR / "vendor" / "jsoneditor.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "jsoneditor.min.css").is_file()


def test_js_modules_present():
    for name in ("api.js", "stream.js", "login.js", "dashboard.js",
                 "health.js", "dispatch.js", "inbox.js", "drilldown.js",
                 "schemas.js", "logs.js", "files.js", "flow.js", "actions.js",
                 "search.js", "sparkline.js", "formats.js"):
        assert (STATIC_DIR / "js" / name).is_file(), f"missing js/{name}"


def test_dashboard_css_present():
    assert (STATIC_DIR / "css" / "dashboard.css").is_file()


def test_dashboard_js_guards_tabulator_build_race():
    """Tabulator replaceData를 tableBuilt 전에 부르면 'verticalFillMode' null 에러로
    테이블이 빈 채 남는다 — 빌드 가드(tableBuilt + 생성 시 data 주입)가 있어야 한다."""
    js = (STATIC_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert "tableBuilt" in js
    # 생성 직후 즉시 replaceData하는 옛 레이스 패턴이 없어야 한다.
    assert "window._convTab.replaceData(rows)" not in js


def test_static_route_served(real_server_app):
    """/dashboard/static/* 가 StaticFiles로 mount되어 응답 (404 not 500/missing route)."""
    from starlette.testclient import TestClient
    with TestClient(real_server_app, raise_server_exceptions=True) as client:
        # The static_dir exists (created in Task 12) but the file doesn't — 404 is correct.
        r = client.get("/dashboard/static/nonexistent_file_for_test.txt")
        # Must be 404 (StaticFiles handles it) — NOT 500 or connection error.
        assert r.status_code == 404


def test_static_assets_sent_no_cache(real_server_app):
    """정적 자산은 Cache-Control: no-cache — 브라우저가 매번 재검증해 대시보드 갱신을
    즉시 반영(기본 StaticFiles는 헤더 없어 stale JS가 남음)."""
    from starlette.testclient import TestClient
    with TestClient(real_server_app, raise_server_exceptions=True) as client:
        r = client.get("/dashboard/static/js/dashboard.js")
        assert r.status_code == 200
        assert "no-cache" in r.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# Fixtures (local — mirrors test_dashboard_dispatch.py setup without auth)
# ---------------------------------------------------------------------------

import contextlib
from starlette.applications import Starlette
from starlette.middleware import Middleware
from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dashboard import (
    DashboardAuthMiddleware, EventBroker, HealthCollector, register,
)
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry


def _make_schema_registry():
    from agent_agora.storage.schemas import SchemaRegistry
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

    # single source — see agent_agora.dashboard_routes.DASHBOARD_PROTECTED_PATHS
    from agent_agora.dashboard import DASHBOARD_PROTECTED_PATHS as PROTECTED_PATHS

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
