"""대시보드 인증 미들웨어 — trust·token·basic 세 모드.

trust 모드: X-Agora-Operator-User 헤더 값을 그대로 신뢰. 로컬·신뢰 LAN용.
token 모드: Authorization: Bearer <token> 검증 후 token에서 username 도출.
            token이 X-Agora-Operator-User 헤더보다 우선 (impersonation 방지).
basic 모드: Authorization: Basic <b64(user:pass)> 검증. users는 username→passhash
            ({SHA256}<b64> 또는 pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>) 맵. 신규
            의존성 0(hashlib+hmac). EventSource는 Authorization 헤더를 못 실으므로
            basic 모드에서 SSE(/stream)는 401 — SSE가 필요하면 token/trust 사용.

OIDC는 외부 IdP 없이 로컬 검증 불가라 스코프 아웃 — _VALID_MODES에 넣지 않는다.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_VALID_MODES = ("trust", "token", "basic")


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, mode: str, tokens: dict[str, str],
                 protected_paths: list[str],
                 query_param_paths: list[str] | None = None,
                 users: dict[str, str] | None = None) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"unknown auth mode {mode!r}; expected one of {_VALID_MODES}"
            )
        super().__init__(app)
        self._mode = mode
        # token 모드 lookup: token → username (중복 token 거부 — 두 user가 같은 token이면 한 명이 unreachable)
        self._token_to_user: dict[str, str] = {}
        for user, token in tokens.items():
            if token in self._token_to_user:
                raise ValueError(
                    f"duplicate token: users {self._token_to_user[token]!r} and {user!r} share the same token"
                )
            self._token_to_user[token] = user
        # basic 모드 lookup: username → passhash
        self._users: dict[str, str] = dict(users or {})
        self._protected = tuple(protected_paths)
        self._query_param_paths = tuple(query_param_paths or [])

    async def dispatch(self, request: Request, call_next):
        if not self._is_protected(request.url.path):
            return await call_next(request)

        user = self._resolve_user(request)
        if not user:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        request.state.operator_user = user
        return await call_next(request)

    def _is_protected(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self._protected)

    def _is_query_param_path(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self._query_param_paths)

    def _resolve_user(self, request: Request) -> str | None:
        allow_query = self._is_query_param_path(request.url.path)

        if self._mode == "token":
            # Authorization 헤더 우선
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[len("Bearer "):].strip()
                return self._token_to_user.get(token)
            # query fallback (EventSource 등 헤더 미지원 클라이언트)
            if allow_query:
                token = request.query_params.get("t")
                if token:
                    return self._token_to_user.get(token)
            return None

        if self._mode == "basic":
            # Authorization: Basic <b64(user:pass)>. EventSource 헤더 불가라 query
            # fallback은 부여하지 않는다(password URL 노출 금지).
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Basic "):
                return None
            try:
                decoded = base64.b64decode(auth[len("Basic "):].strip()).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                return None
            if ":" not in decoded:
                return None
            username, password = decoded.split(":", 1)
            stored = self._users.get(username)
            if stored and verify_password(password, stored):
                return username
            return None

        # trust mode — mode는 __init__에서 _VALID_MODES로 검증됨
        user = (request.headers.get("x-agora-operator-user") or "").strip()
        if user:
            return user
        if allow_query:
            user = (request.query_params.get("u") or "").strip()
            return user or None
        return None


def verify_password(plain: str, stored: str) -> bool:
    """basic 모드 passhash 검증. 인식 못하는 포맷은 안전 실패(False).

    지원 포맷:
      - '{SHA256}<b64(sha256(plain))>'
      - 'pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>'
    상수시간 비교(hmac.compare_digest)로 타이밍 누수 방지.
    """
    try:
        if stored.startswith("{SHA256}"):
            expected = stored[len("{SHA256}"):]
            actual = base64.b64encode(
                hashlib.sha256(plain.encode("utf-8")).digest()).decode("ascii")
            return hmac.compare_digest(actual, expected)
        if stored.startswith("pbkdf2_sha256$"):
            _, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
            iters = int(iters_s)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            actual = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iters)
            return hmac.compare_digest(actual, expected)
    except (ValueError, binascii.Error):
        return False
    return False


def parse_basic_users(env_value: str) -> dict[str, str]:
    """AGORA_DASHBOARD_BASIC_USERS 환경변수 파싱.

    Format: "user1:hash1,user2:hash2". hash에 ':'·'$'·'{' 가 들어갈 수 있어
    split(':', 1)로 첫 ':'만 분리. 빈 user/hash → ValueError, 중복 user → ValueError.
    """
    env_value = env_value.strip()
    if not env_value:
        return {}
    result: dict[str, str] = {}
    for entry in env_value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(f"invalid basic user mapping (missing ':'): {entry!r}")
        user, passhash = entry.split(":", 1)
        user = user.strip()
        passhash = passhash.strip()
        if not user or not passhash:
            raise ValueError(f"invalid basic user mapping (empty user or hash): {entry!r}")
        if user in result:
            raise ValueError(f"duplicate user in basic users: {user!r}")
        result[user] = passhash
    return result


def parse_tokens(env_value: str) -> dict[str, str]:
    """AGORA_DASHBOARD_TOKENS 환경변수 파싱.

    Format: "user1:token1,user2:token2". 공백 허용. 빈 문자열 → {}.
    ':'이 없는 항목 → ValueError.
    """
    env_value = env_value.strip()
    if not env_value:
        return {}
    result: dict[str, str] = {}
    for entry in env_value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(f"invalid token mapping (missing ':'): {entry!r}")
        user, token = entry.split(":", 1)
        user = user.strip()
        token = token.strip()
        if not user or not token:
            raise ValueError(f"invalid token mapping (empty user or token): {entry!r}")
        result[user] = token
    return result
