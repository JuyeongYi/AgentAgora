"""dashboard_auth 미들웨어 — trust·token 두 모드 검증."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agent_agora.dashboard import DashboardAuthMiddleware, parse_tokens


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _make_jwt(payload: dict, secret: str, *, alg: str = "HS256") -> str:
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    if alg == "none":
        return f"{header}.{body}."
    sig = _b64url(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def _make_app(mode: str, tokens: dict | None = None,
              users: dict | None = None, jwt_secret: str | None = None) -> Starlette:
    async def whoami(req: Request) -> JSONResponse:
        return JSONResponse({"user": req.state.operator_user})

    async def auth_mode(req: Request) -> JSONResponse:
        return JSONResponse({"mode": mode})

    app = Starlette(routes=[
        Route("/whoami", whoami),
        Route("/auth-mode", auth_mode),
    ])
    app.add_middleware(DashboardAuthMiddleware, mode=mode, tokens=tokens or {},
                       protected_paths=["/whoami"], users=users or {},
                       query_param_paths=["/stream"], jwt_secret=jwt_secret)
    # Force middleware stack build so __init__ errors surface eagerly
    # (Starlette는 첫 요청 전까지 미들웨어를 instantiate하지 않음).
    app.build_middleware_stack()
    return app


def _sha256_hash(plain: str) -> str:
    return "{SHA256}" + base64.b64encode(
        hashlib.sha256(plain.encode("utf-8")).digest()).decode("ascii")


def _basic_header(user: str, password: str) -> dict:
    raw = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + raw}


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


def test_basic_mode_accepts_valid_credentials():
    users = {"alice": _sha256_hash("secret")}
    client = TestClient(_make_app("basic", users=users))
    r = client.get("/whoami", headers=_basic_header("alice", "secret"))
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}


def test_basic_mode_rejects_wrong_password():
    users = {"alice": _sha256_hash("secret")}
    client = TestClient(_make_app("basic", users=users))
    r = client.get("/whoami", headers=_basic_header("alice", "wrong"))
    assert r.status_code == 401


def test_basic_mode_rejects_unknown_user():
    users = {"alice": _sha256_hash("secret")}
    client = TestClient(_make_app("basic", users=users))
    r = client.get("/whoami", headers=_basic_header("mallory", "x"))
    assert r.status_code == 401


def test_basic_mode_no_header_401():
    users = {"alice": _sha256_hash("secret")}
    client = TestClient(_make_app("basic", users=users))
    r = client.get("/whoami")
    assert r.status_code == 401


def test_verify_password_sha256_and_pbkdf2():
    from agent_agora.dashboard import verify_password
    # {SHA256}
    assert verify_password("secret", _sha256_hash("secret")) is True
    assert verify_password("nope", _sha256_hash("secret")) is False
    # pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>
    salt = b"saltsalt"
    iters = 50_000
    dk = hashlib.pbkdf2_hmac("sha256", b"hunter2", salt, iters)
    stored = (f"pbkdf2_sha256${iters}$"
              f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}")
    assert verify_password("hunter2", stored) is True
    assert verify_password("wrong", stored) is False
    # 인식 불가 포맷은 안전 실패(False)
    assert verify_password("secret", "plaintext-no-prefix") is False


def test_parse_basic_users_format_and_malformed():
    from agent_agora.dashboard import parse_basic_users
    parsed = parse_basic_users("alice:{SHA256}abc,bob:pbkdf2_sha256$1$s$h")
    assert parsed == {"alice": "{SHA256}abc", "bob": "pbkdf2_sha256$1$s$h"}
    assert parse_basic_users("") == {}
    with pytest.raises(ValueError, match="missing ':'"):
        parse_basic_users("alice")
    with pytest.raises(ValueError, match="empty user or hash"):
        parse_basic_users(":hash")
    with pytest.raises(ValueError, match="empty user or hash"):
        parse_basic_users("alice:")
    with pytest.raises(ValueError, match="duplicate user"):
        parse_basic_users("alice:h1,alice:h2")


def test_unknown_mode_still_raises_basic_and_jwt_valid():
    # basic·jwt는 유효 — 빈 users/secret 허용
    _make_app("basic")
    _make_app("jwt", jwt_secret="s3cr3t")
    # oidc는 스코프 아웃 — 여전히 unknown
    with pytest.raises(ValueError, match="unknown auth mode"):
        _make_app("oidc")


def test_jwt_mode_accepts_valid_token():
    secret = "topsecret"
    client = TestClient(_make_app("jwt", jwt_secret=secret))
    tok = _make_jwt({"sub": "alice", "exp": time.time() + 3600}, secret)
    r = client.get("/whoami", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    assert r.json() == {"user": "alice"}


def test_jwt_mode_rejects_wrong_secret():
    client = TestClient(_make_app("jwt", jwt_secret="topsecret"))
    tok = _make_jwt({"sub": "alice", "exp": time.time() + 3600}, "WRONG")
    r = client.get("/whoami", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401


def test_jwt_mode_rejects_alg_none():
    """alg:none 공격 차단 — 서명 없는 토큰 거부."""
    client = TestClient(_make_app("jwt", jwt_secret="topsecret"))
    tok = _make_jwt({"sub": "alice"}, "topsecret", alg="none")
    r = client.get("/whoami", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401


def test_jwt_mode_rejects_expired():
    secret = "topsecret"
    client = TestClient(_make_app("jwt", jwt_secret=secret))
    tok = _make_jwt({"sub": "alice", "exp": time.time() - 10}, secret)
    r = client.get("/whoami", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401


def test_jwt_mode_rejects_tampered_payload():
    secret = "topsecret"
    tok = _make_jwt({"sub": "alice", "exp": time.time() + 3600}, secret)
    head, body, sig = tok.split(".")
    forged_body = _b64url(json.dumps({"sub": "admin", "exp": time.time() + 3600}).encode())
    forged = f"{head}.{forged_body}.{sig}"  # 서명 불일치
    client = TestClient(_make_app("jwt", jwt_secret=secret))
    r = client.get("/whoami", headers={"Authorization": "Bearer " + forged})
    assert r.status_code == 401


def test_jwt_mode_no_sub_rejected():
    secret = "topsecret"
    client = TestClient(_make_app("jwt", jwt_secret=secret))
    tok = _make_jwt({"exp": time.time() + 3600}, secret)  # sub 없음
    r = client.get("/whoami", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401


def test_verify_jwt_unit():
    from agent_agora.dashboard import verify_jwt
    secret = "k"
    assert verify_jwt(_make_jwt({"sub": "bob"}, secret), secret) == "bob"
    assert verify_jwt(_make_jwt({"sub": "bob"}, secret), "other") is None
    assert verify_jwt(_make_jwt({"sub": "bob"}, secret, alg="none"), secret) is None
    assert verify_jwt("not.a.jwt", secret) is None
    assert verify_jwt("", secret) is None


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
