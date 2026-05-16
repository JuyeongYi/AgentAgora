# comm-matrix admin 엔드포인트 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영자 전용 토큰 게이트 admin HTTP 엔드포인트(`POST/GET /admin/comm-matrix`)를 추가해, 재기동 없이 comm-matrix ACL을 교체·조회할 수 있게 한다 — 워커가 보는 MCP 도구 표면 바깥에서.

**Architecture:** 신규 `admin_routes.py`에 토큰 검증(`hmac.compare_digest`) + GET/POST 핸들러 + `make_admin_route` 팩토리 + `maybe_register` 헬퍼. `__main__.py`의 `run_server`가 `AGORA_ADMIN_TOKEN` 환경변수가 있을 때만 라우트를 `streamable_http_app`에 등록한다.

**Tech Stack:** Python 3.13, Starlette, pytest. spec: `docs/superpowers/specs/2026-05-17-comm-matrix-governance-design.md` §3.2–3.3.

**전제:**
- 이 plan은 additive다 — `agora.register_comm_matrix` 도구 제거(plan `2026-05-17-comm-matrix-remove-tool.md`)와 독립이며, 어느 쪽을 먼저 머지해도 무방하다.
- 별도 브랜치/worktree에서 실행.
- 테스트 인터프리터는 저장소 `.venv`(Python 3.13).

---

### Task 1: `CommMatrix.snapshot()` 조회 메서드

**Files:**
- Modify: `src/agent_agora/comm_matrix.py`
- Modify: `tests/test_v4_comm_matrix.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_v4_comm_matrix.py`의 CommMatrix 단위 테스트 묶음(`test_load_csv_replaces_prior_matrix_in_place` 근처) 뒤에 추가:

```python
def test_snapshot_returns_sorted_allowed_map():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    snap = cm.snapshot()
    assert snap["Inst1"] == ["Coder1", "Reviewer1", "Tester1"]
    assert snap["Coder1"] == ["Inst1"]


def test_snapshot_inactive_is_empty():
    assert CommMatrix().snapshot() == {}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py::test_snapshot_returns_sorted_allowed_map -v`
Expected: FAIL — `AttributeError: 'CommMatrix' object has no attribute 'snapshot'`

- [ ] **Step 3: `snapshot()` 구현**

`src/agent_agora/comm_matrix.py`의 `CommMatrix` 클래스에서 `is_allowed` 메서드 바로 뒤에 추가:

```python
    def snapshot(self) -> dict[str, list[str]]:
        """현재 ACL을 {to: sorted([from, ...])} dict로 반환 (조회용)."""
        return {to: sorted(froms) for to, froms in self._allowed.items()}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -v`
Expected: 전체 PASS (기존 + 신규 2건)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/comm_matrix.py tests/test_v4_comm_matrix.py
git commit -m "feat: CommMatrix.snapshot() — ACL 조회 메서드"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 2: `admin_routes.py` — admin 엔드포인트

**Files:**
- Create: `src/agent_agora/admin_routes.py`
- Create: `tests/test_admin_routes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_admin_routes.py` 전체:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.admin_routes'`

- [ ] **Step 3: `admin_routes.py` 구현**

`src/agent_agora/admin_routes.py` 전체:

```python
"""운영자 전용 admin HTTP 엔드포인트 — comm-matrix 런타임 교체.

워커가 보는 MCP 도구 표면이 아니다. AGORA_ADMIN_TOKEN으로 게이팅되며,
토큰을 가진 운영자만 호출한다.
spec: docs/superpowers/specs/2026-05-17-comm-matrix-governance-design.md.
"""
from __future__ import annotations

import hmac

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_agora.comm_matrix import CommMatrix
from agent_agora.errors import AgoraError

_BEARER_PREFIX = "Bearer "


def _authorized(request: Request, token: str) -> bool:
    """Authorization: Bearer <token> 헤더가 token과 상수시간 일치하는가."""
    header = request.headers.get("authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        return False
    return hmac.compare_digest(header[len(_BEARER_PREFIX):], token)


def make_admin_route(comm_matrix: CommMatrix, token: str) -> Route:
    """comm-matrix admin 라우트를 만든다. comm_matrix·token을 클로저로 캡처.

    POST /admin/comm-matrix — 바디 CSV로 in-memory 매트릭스 교체.
    GET  /admin/comm-matrix — 현재 매트릭스 상태 조회.
    """

    async def endpoint(request: Request) -> JSONResponse:
        if not _authorized(request, token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.method == "GET":
            return JSONResponse({
                "active": comm_matrix.active,
                "matrix": comm_matrix.snapshot(),
            })
        # POST — 바디 CSV로 매트릭스 in-memory 교체
        csv_text = (await request.body()).decode("utf-8")
        try:
            comm_matrix.load_csv(csv_text)
        except AgoraError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "ok", "active": comm_matrix.active})

    return Route("/admin/comm-matrix", endpoint, methods=["GET", "POST"])


def maybe_register(
    app: Starlette, comm_matrix: CommMatrix, token: str | None,
) -> bool:
    """token이 truthy면 app에 admin 라우트를 등록한다. 등록 여부를 반환.

    token이 없으면(env 미설정) admin 엔드포인트는 아예 존재하지 않는다 —
    기본 비활성 = 기본 안전."""
    if not token:
        return False
    app.router.routes.append(make_admin_route(comm_matrix, token))
    return True
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_routes.py -v`
Expected: 전체 PASS (8건)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/admin_routes.py tests/test_admin_routes.py
git commit -m "feat: admin_routes — 운영자 토큰 게이트 comm-matrix 엔드포인트"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 3: `run_server` 배선

**Files:**
- Modify: `src/agent_agora/__main__.py`

- [ ] **Step 1: `import os` 추가**

`src/agent_agora/__main__.py` 상단 import 블록(`import argparse` 등)에 `import os`를 추가한다 (이미 있으면 생략).

- [ ] **Step 2: `run_server`에 admin 라우트 배선**

`run_server` 안에서 다음 두 줄을 찾는다:

```python
        starlette_app = mcp.streamable_http_app()
        starlette_app.add_middleware(AutoRegisterMiddleware, registry=instance_registry)
```

바로 뒤에 추가:

```python
        from agent_agora.admin_routes import maybe_register
        if maybe_register(
            starlette_app, mcp._agora_comm_matrix,  # type: ignore[attr-defined]
            os.environ.get("AGORA_ADMIN_TOKEN"),
        ):
            print("  Admin    : POST/GET /admin/comm-matrix (AGORA_ADMIN_TOKEN set)")
```

- [ ] **Step 3: 전체 테스트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS. `run_server`의 배선은 한 줄 글루이고 `maybe_register`는 Task 2에서 단위 검증됨 — 회귀만 확인한다.

- [ ] **Step 4: 수동 스모크 (선택, 보고용)**

```bash
set AGORA_ADMIN_TOKEN=smoke-token
.venv\Scripts\python.exe -m agent_agora --dir . --port 8420 --no-tls --no-timeout
```
다른 셸에서:
```bash
curl -s http://127.0.0.1:8420/admin/comm-matrix -H "Authorization: Bearer smoke-token"
```
Expected: `{"active": false, "matrix": {}}` (토큰 없는 요청은 401, env 미설정 시 404).

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/__main__.py
git commit -m "feat: run_server — AGORA_ADMIN_TOKEN 있으면 admin 라우트 등록"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.2(admin 엔드포인트 POST/GET)는 Task 2, §3.3(토큰 게이트·`AGORA_ADMIN_TOKEN`·미설정 시 비활성)은 Task 2(`maybe_register`)+Task 3, §3.5(구현 노트 — `comm_matrix` 클로저 캡처, `hmac.compare_digest`, 조건부 등록)는 Task 2·3이 구현한다. `GET`이 쓰는 `snapshot()`은 Task 1.
- **Placeholder** — 없음. 모든 코드·명령·기대 출력 구체적.
- **타입 일관성** — `make_admin_route(comm_matrix: CommMatrix, token: str)`·`maybe_register(app, comm_matrix, token: str | None) -> bool`는 Task 2 정의와 Task 3 호출이 일치. `snapshot() -> dict[str, list[str]]`(Task 1)을 GET 핸들러가 그대로 직렬화.
