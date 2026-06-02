"""dashboard_auth 미들웨어 — trust·token 두 모드 검증."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agent_agora.dashboard import DashboardAuthMiddleware, parse_tokens


def _make_app(mode: str, tokens: dict | None = None) -> Starlette:
    async def whoami(req: Request) -> JSONResponse:
        return JSONResponse({"user": req.state.operator_user})

    async def auth_mode(req: Request) -> JSONResponse:
        return JSONResponse({"mode": mode})

    app = Starlette(routes=[
        Route("/whoami", whoami),
        Route("/auth-mode", auth_mode),
    ])
    app.add_middleware(DashboardAuthMiddleware, mode=mode, tokens=tokens or {},
                       protected_paths=["/whoami"])
    # Force middleware stack build so __init__ errors surface eagerly
    # (Starlette는 첫 요청 전까지 미들웨어를 instantiate하지 않음).
    app.build_middleware_stack()
    return app


def test_trust_mode_accepts_header():
    client = TestClient(_make_app("trust"))
    r = client.get("/whoami", headers={"X-Agora-Operator-User": "alice"})
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}


def test_trust_mode_empty_username_401():
    client = TestClient(_make_app("trust"))
    r = client.get("/whoami", headers={"X-Agora-Operator-User": ""})
    assert r.status_code == 401

    r = client.get("/whoami")
    assert r.status_code == 401


def test_token_mode_accepts_bearer():
    tokens = {"alice": "tok-A", "bob": "tok-B"}
    client = TestClient(_make_app("token", tokens))
    r = client.get("/whoami", headers={"Authorization": "Bearer tok-A"})
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}


def test_token_mode_rejects_unknown_token():
    tokens = {"alice": "tok-A"}
    client = TestClient(_make_app("token", tokens))
    r = client.get("/whoami", headers={"Authorization": "Bearer tok-X"})
    assert r.status_code == 401


def test_token_mode_token_overrides_header_user():
    """token에서 도출한 username이 X-Agora-Operator-User 헤더보다 우선 (impersonation 방지)."""
    tokens = {"alice": "tok-A"}
    client = TestClient(_make_app("token", tokens))
    r = client.get("/whoami", headers={
        "Authorization": "Bearer tok-A",
        "X-Agora-Operator-User": "bob",  # 위장 시도
    })
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}  # token이 이김


def test_auth_mode_endpoint_unprotected():
    """/dashboard/auth-mode 같은 unprotected path는 인증 없이 200."""
    client = TestClient(_make_app("trust"))
    r = client.get("/auth-mode")
    assert r.status_code == 200


def test_parse_tokens_env_format():
    """AGORA_DASHBOARD_TOKENS 환경변수 'user1:tok1,user2:tok2' 파싱."""
    assert parse_tokens("alice:tok-A,bob:tok-B") == {"alice": "tok-A", "bob": "tok-B"}
    assert parse_tokens("") == {}
    assert parse_tokens("  alice : tok-A , bob:tok-B ") == {"alice": "tok-A", "bob": "tok-B"}


def test_parse_tokens_rejects_malformed():
    with pytest.raises(ValueError, match="invalid token mapping"):
        parse_tokens("alice")  # ':' 없음

    with pytest.raises(ValueError, match="invalid token mapping"):
        parse_tokens("alice:tok-A,bob")  # 두번째 항목에 ':' 없음


def test_unknown_mode_raises_at_init():
    with pytest.raises(ValueError, match="unknown auth mode"):
        _make_app("tokken")  # typo of "token"


def test_duplicate_token_raises_at_init():
    with pytest.raises(ValueError, match="duplicate token"):
        _make_app("token", {"alice": "tok-X", "bob": "tok-X"})


def test_parse_tokens_rejects_empty_user():
    with pytest.raises(ValueError, match="empty user or token"):
        parse_tokens(":tok-A")


def test_parse_tokens_rejects_empty_token():
    with pytest.raises(ValueError, match="empty user or token"):
        parse_tokens("alice:")


def test_trust_mode_query_param_fallback_for_sse():
    """EventSource는 헤더 첨부 못함 — stream 경로는 ?u=<user> query 허용."""
    client = TestClient(_make_app("trust"))
    # 헤더 없이 query param만으로 — /whoami는 query fallback path가 아니므로 401
    r = client.get("/whoami?u=alice")
    assert r.status_code == 401


def test_trust_mode_stream_path_allows_query():
    """미들웨어 빌드 시 query_param_paths로 지정한 path는 query fallback."""
    from agent_agora.dashboard import DashboardAuthMiddleware
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def stream(req): return JSONResponse({"user": req.state.operator_user})
    app = Starlette(routes=[Route("/stream", stream)])
    app.add_middleware(DashboardAuthMiddleware, mode="trust", tokens={},
                       protected_paths=["/stream"], query_param_paths=["/stream"])
    r = TestClient(app).get("/stream?u=alice")
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}


def test_token_mode_stream_path_allows_token_query():
    from agent_agora.dashboard import DashboardAuthMiddleware
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def stream(req): return JSONResponse({"user": req.state.operator_user})
    app = Starlette(routes=[Route("/stream", stream)])
    app.add_middleware(DashboardAuthMiddleware, mode="token",
                       tokens={"alice": "tok-A"},
                       protected_paths=["/stream"], query_param_paths=["/stream"])
    r = TestClient(app).get("/stream?t=tok-A")
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}
