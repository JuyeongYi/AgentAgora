# comm-matrix `register_comm_matrix` 도구 제거 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agora.register_comm_matrix` MCP 도구를 제거한다 — 워커가 자기 ACL을 재작성하는 구멍을 막는다. 도구를 쓰던 예제(`comm_demo`)와 문서를 startup-CSV / admin 엔드포인트 경로로 갱신한다.

**Architecture:** `server.py`에서 `@mcp.tool(name="agora.register_comm_matrix")` 정의를 삭제. `CommMatrix`·dispatch/broadcast ACL 검사는 그대로 — 매트릭스 *기능*은 유지하고 *워커가 변경하는 경로*만 없앤다. 도구를 setup 헬퍼로 쓰던 테스트는 `comm_matrix.load_csv()` 직접 호출로 전환한다.

**Tech Stack:** Python 3.13, pytest. spec: `docs/superpowers/specs/2026-05-17-comm-matrix-governance-design.md` §3.1·§3.4.

**전제:**
- 이 plan은 admin 엔드포인트 plan(`2026-05-17-comm-matrix-admin-endpoint.md`)과 독립이다. admin 엔드포인트가 런타임 교체의 대체 경로이므로, 운영상으론 admin plan을 먼저(또는 함께) 머지하는 것이 매끄럽다 — 본 plan 자체는 admin 코드에 의존하지 않는다(Task 3 문서만 admin 엔드포인트를 *서술*한다).
- 별도 브랜치/worktree에서 실행. 테스트 인터프리터는 저장소 `.venv`(Python 3.13).

---

### Task 1: `agora.register_comm_matrix` 도구 제거 + 테스트 전환

**Files:**
- Modify: `src/agent_agora/server.py`
- Modify: `tests/test_v4_comm_matrix.py`

- [ ] **Step 1: 도구 정의 삭제**

`src/agent_agora/server.py`에서 다음 블록(현 `server.py:102-110`)을 통째로 삭제한다:

```python
    @mcp.tool(name="agora.register_comm_matrix")
    async def agora_register_comm_matrix(csv_text: str) -> str:
        """Replace the worker↔worker comm-matrix ACL from CSV text at runtime.
        CSV: 헤더 1줄(N from) + 데이터 N줄, 셀 0/1. shape 불일치 시 거부."""
        try:
            comm_matrix.load_csv(csv_text)
        except AgoraError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "ok", "active": comm_matrix.active})
```

`create_agora_app`의 `comm_matrix` 매개변수는 그대로 둔다 — Dispatcher가 ACL 검사에 쓴다. `comm_matrix`가 이 도구 외에 `create_agora_app` 본문에서 안 쓰이면 매개변수만 남고 본문 참조는 없어진다(정상 — Dispatcher가 생성자에서 받음).

- [ ] **Step 2: 도구 직접 테스트 2건 삭제**

`tests/test_v4_comm_matrix.py`에서 다음 두 테스트 함수를 통째로 삭제한다:
- `test_register_comm_matrix_activates_acl` (도구로 활성화 → dispatch 거부 확인)
- `test_register_comm_matrix_rejects_bad_shape` (도구 shape 거부)

근거: shape 거부는 `test_load_csv_rejects_row_count_mismatch`·`test_load_csv_rejects_column_count_mismatch`가, 활성화→enforcement는 `test_hub_and_spoke_enforced_end_to_end`와 dispatcher 레벨 테스트(`test_dispatch_denied_pair_raises_comm_denied` 등)가 이미 커버한다.

- [ ] **Step 3: 도구를 setup 헬퍼로 쓰던 테스트 3건 전환**

`tests/test_v4_comm_matrix.py`의 다음 세 테스트에서, `_tool(mcp, "agora.register_comm_matrix")(csv_text=...)` 호출을 `comm_matrix.load_csv(...)` 직접 호출로 바꾼다. `cm_app` fixture는 `(mcp, dispatcher, comm_matrix)`를 yield하므로 언패킹에 `comm_matrix`를 받는다.

`test_hub_and_spoke_enforced_end_to_end`:
```python
async def test_hub_and_spoke_enforced_end_to_end(cm_app):
    """hub-and-spoke: 워커는 hub에만 회신, 워커끼리 직접 dispatch 차단."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv(_HUB)
    r1 = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(m=1), target="Tester1"))
    assert "comm_denied" in r1["error"]
    r2 = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(m=1), target="Inst1"))
    assert r2["status"] == "ok"
```

`test_unregistered_worker_denied`:
```python
async def test_unregistered_worker_denied(cm_app):
    """CSV 미등재 워커는 from/to 모두 거부 (strict whitelist)."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv("Inst1,Coder1\n0,1\n1,0")
    r = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Inst1"), payload=tany(m=1), target="Reviewer1"))
    assert "comm_denied" in r["error"]
```

`test_broadcast_partial_filter_through_tool`:
```python
async def test_broadcast_partial_filter_through_tool(cm_app):
    """agora.broadcast도 매트릭스 필터 — denied 목록 보고."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv(_HUB)
    res = json.loads(await _tool(mcp, "agora.broadcast")(
        _FakeCtx("sess-Coder1"), payload=tany(m=1)))
    assert res["status"] == "ok"
    assert sorted(res["denied"]) == ["Reviewer1", "Tester1"]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -v`
Expected: 전체 PASS (삭제 2건 제외, 전환 3건 포함). `agora.register_comm_matrix` 미정의로 인한 실패 없음.

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS — 다른 테스트에 `register_comm_matrix` 참조가 없음(grep으로 `tests/`에서 `test_v4_comm_matrix.py`만 매칭됨).

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_comm_matrix.py
git commit -m "refactor: agora.register_comm_matrix 도구 제거 — 워커 ACL 자가-재작성 차단"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 2: `comm_demo` 예제 — startup-CSV 경로로 전환

**Files:**
- Create: `examples/comm_demo/comm-matrix.csv`
- Modify: `examples/comm_demo/demo.py`
- Modify: `examples/comm_demo/run-demo.bat`
- Modify: `examples/README.md`

`comm_demo`는 `agora.register_comm_matrix`로 런타임에 매트릭스를 설치했다. 도구가 사라졌으므로, 매트릭스를 **서버 startup 시 `.agentagora/comm-matrix.csv`로 시드**하는 방식으로 바꾼다.

- [ ] **Step 1: 매트릭스 CSV 파일 추가**

`examples/comm_demo/comm-matrix.csv` 생성 (내용 — demo가 쓰던 `DENY_AB_CSV`와 동일):

```
worker_a,worker_b
0,1
0,0
```

(`to=worker_a` 행은 `worker_b`만 1, `to=worker_b` 행은 전부 0 → `worker_a→worker_b` 거부, `worker_b→worker_a` 허용.)

- [ ] **Step 2: `demo.py` — 런타임 설치 제거**

`examples/comm_demo/demo.py`에서:
- `main()` 안의 comm-matrix 런타임 설치 블록을 삭제한다:
  ```python
              # 런타임에 comm-matrix 설치 (서버 전역 ACL 교체).
              cm = _result_json(await sa.call_tool(
                  "agora.register_comm_matrix", {"csv_text": DENY_AB_CSV}))
              print(f"comm-matrix 설치: {cm}", flush=True)
  ```
- 모듈 상단 `DENY_AB_CSV` 상수는 더 이상 코드에서 안 쓰이면 삭제한다(주석 설명용으로 남기지 않는다).
- 모듈 docstring(파일 첫 `"""..."""`)을 갱신: "런타임에 comm-matrix를 설치"·"`register_comm_matrix`는 …" 서술을 제거하고, "매트릭스는 서버 startup 시 `.agentagora/comm-matrix.csv`로 시드된다 — `run-demo.bat`가 처리한다"로 바꾼다. 사전 조건 줄도 그에 맞게 수정한다.

`register`·dispatch 검증(`a→b` 거부, `b→a` 허용) 로직은 그대로 둔다.

- [ ] **Step 3: `run-demo.bat` — CSV 시드 + 서버 기동 포함**

`examples/comm_demo/run-demo.bat`를 읽고, demo가 붙을 서버가 `comm-matrix.csv`를 로드한 채 뜨도록 고친다. 권장 흐름 (실행자가 현 `run-demo.bat` 구조에 맞춰 적용):
- demo 전용 데이터 디렉토리(예: `%TEMP%\agora-comm-demo`)의 `.agentagora\`에 `examples/comm_demo/comm-matrix.csv`를 복사한다.
- 그 디렉토리를 `--dir`로 `agent-agora`를 기동한다 (`--no-tls --no-timeout`).
- 서버 준비 후 `demo.py`를 실행하고, 끝나면 서버를 종료한다.

`run-demo.bat`도 채널 모드 경험에서 확인된 대로 **CRLF + ASCII**로 작성한다(LF·비ASCII 주석은 cmd.exe 파서를 깨뜨림).

- [ ] **Step 4: `examples/README.md` 갱신**

`examples/README.md`의 comm_demo 관련 서술에서 `agora.register_comm_matrix` 도구 언급을 제거하고 startup-CSV 시드로 바꾼다. 특히 "런타임 교체는 `agora.register_comm_matrix(csv_text=...)` 도구로 같은 형식의 텍스트를 넘긴다" 류 문장은 "런타임 교체는 운영자 admin 엔드포인트 `POST /admin/comm-matrix`로 한다(`AGORA_ADMIN_TOKEN` 필요)"로 바꾼다.

- [ ] **Step 5: 데모 검증**

Run: `examples\comm_demo\run-demo.bat`
Expected: `=== PASS — ACL이 기대대로 동작 ===` 출력 (`a→b` 거부, `b→a` 허용).

- [ ] **Step 6: 커밋**

```bash
git add examples/comm_demo/comm-matrix.csv examples/comm_demo/demo.py examples/comm_demo/run-demo.bat examples/README.md
git commit -m "refactor: comm_demo — register_comm_matrix 대신 startup-CSV 시드"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 3: 루트 `README.md` — 도구 레퍼런스 갱신

**Files:**
- Modify: `README.md`

- [ ] **Step 1: `register_comm_matrix` 도구 항목 제거**

Run (bash): `grep -n "register_comm_matrix" README.md`
매칭되는 줄(MCP 도구 레퍼런스의 `agora.register_comm_matrix` 항목 등)을 제거한다. comm-matrix를 *기능*으로 설명하는 "핵심 개념"의 통신 매트릭스 단락은 유지하되, 런타임 교체를 도구로 한다는 서술이 있으면 admin 엔드포인트로 고친다.

- [ ] **Step 2: admin 엔드포인트 문서 추가**

`README.md`의 CLI 옵션 / 서버 운영 관련 절에 짧은 항목을 추가한다 — 운영자가 `AGORA_ADMIN_TOKEN` 환경변수를 설정하면 `POST/GET /admin/comm-matrix` 엔드포인트가 활성화되어 재기동 없이 comm-matrix를 교체·조회할 수 있고, `Authorization: Bearer <token>`이 필요하며, env 미설정 시 엔드포인트는 비활성(404)이라는 점. comm-matrix는 그 외엔 startup 시 `.agentagora/comm-matrix.csv`로 로드된다는 기존 서술과 연결한다.

- [ ] **Step 3: 확인 + 커밋**

Run (bash): `grep -n "register_comm_matrix" README.md || echo "(clean)"`
Expected: `(clean)`

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS (문서 변경 — 회귀 없음).

```bash
git add README.md
git commit -m "docs: README — register_comm_matrix 제거, admin 엔드포인트 문서화"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.1(`agora.register_comm_matrix` 도구 제거)은 Task 1, §3.4의 예제·문서 갱신은 Task 2(`comm_demo`)·Task 3(루트 README)이 구현한다. 매트릭스 *기능*(`CommMatrix`, dispatch/broadcast ACL)은 어느 Task도 건드리지 않는다 — spec §3.1 "기능 유지, 변경 경로만 제거" 준수.
- **Placeholder** — Task 1의 코드·테스트는 완전체. Task 2·3의 문서·예제 산문 편집은 변경 지점과 방향을 구체적으로 지정했다(정확한 산문·`run-demo.bat` 세부는 실행자가 현 파일을 읽고 작성).
- **타입 일관성** — `cm_app` fixture가 yield하는 `(mcp, dispatcher, comm_matrix)` 튜플을 Task 1 Step 3의 전환 테스트가 정확히 언패킹한다. `comm_matrix.load_csv(csv_text)`는 기존 `CommMatrix` API와 일치 — 새 메서드 도입 없음.
