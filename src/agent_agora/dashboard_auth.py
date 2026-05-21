"""대시보드 인증 미들웨어 — trust·token 두 모드.

trust 모드: X-Agora-Operator-User 헤더 값을 그대로 신뢰. 로컬·신뢰 LAN용.
token 모드: Authorization: Bearer <token> 검증 후 token에서 username 도출.
            token이 X-Agora-Operator-User 헤더보다 우선 (impersonation 방지).

향후 모드(basic·OIDC)는 이 파일에 분기만 추가하면 됨 — 엔드포인트 코드 변경 0.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_VALID_MODES = ("trust", "token")


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, mode: str, tokens: dict[str, str],
                 protected_paths: list[str]) -> None:
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
        self._protected = tuple(protected_paths)

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

    def _resolve_user(self, request: Request) -> str | None:
        if self._mode == "token":
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer "):
                return None
            token = auth[len("Bearer "):].strip()
            return self._token_to_user.get(token)
        # trust mode — mode는 __init__에서 _VALID_MODES로 검증됨
        return (request.headers.get("x-agora-operator-user") or "").strip() or None


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
