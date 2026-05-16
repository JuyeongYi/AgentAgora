"""admin 엔드포인트 (comm-matrix 런타임 교체) 테스트."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.admin_routes import make_admin_route, maybe_register
from agent_agora.comm_matrix import CommMatrix

_TOKEN = "test-secret"
_HUB = "Inst1,Coder1\n0,1\n1,0\n"


def _client(comm_matrix: CommMatrix) -> TestClient:
    app = Starlette(routes=[make_admin_route(comm_matrix, _TOKEN)])
    return TestClient(app)


def test_post_without_token_is_401():
    cm = CommMatrix()
    r = _client(cm).post("/admin/comm-matrix", content=_HUB)
    assert r.status_code == 401
    assert cm.active is False


def test_post_with_bad_token_is_401():
    cm = CommMatrix()
    r = _client(cm).post("/admin/comm-matrix", content=_HUB,
                         headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert cm.active is False


def test_post_with_token_replaces_matrix():
    cm = CommMatrix()
    r = _client(cm).post("/admin/comm-matrix", content=_HUB,
                         headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "active": True}
    assert cm.is_allowed("Coder1", "Inst1") is True
    assert cm.is_allowed("Inst1", "Inst1") is False


def test_post_bad_csv_is_400():
    cm = CommMatrix()
    r = _client(cm).post("/admin/comm-matrix", content="A,B,C\n0,1,1\n1,0,0",
                         headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 400
    assert "error" in r.json()
    assert cm.active is False


def test_get_returns_matrix_snapshot():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    r = _client(cm).get("/admin/comm-matrix",
                        headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["matrix"]["Coder1"] == ["Inst1"]


def test_get_without_token_is_401():
    r = _client(CommMatrix()).get("/admin/comm-matrix")
    assert r.status_code == 401


def test_maybe_register_with_token_adds_route():
    cm = CommMatrix()
    app = Starlette()
    added = maybe_register(app, cm, _TOKEN)
    assert added is True
    r = TestClient(app).post("/admin/comm-matrix", content=_HUB,
                             headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200


def test_maybe_register_without_token_skips():
    cm = CommMatrix()
    app = Starlette()
    added = maybe_register(app, cm, None)
    assert added is False
    r = TestClient(app).post("/admin/comm-matrix", content=_HUB,
                             headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 404
