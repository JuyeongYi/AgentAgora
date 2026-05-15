# 통신 매트릭스 (Communication Matrix) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 서버에 worker↔worker dispatch ACL을 추가한다 — `.agentagora/comm-matrix.csv`로 정의된 N×N 매트릭스로 broker가 금지된 워커 쌍의 `dispatch`/`broadcast`를 거부한다.

**Architecture:** 새 `CommMatrix`(in-memory ACL, CSV 파싱 + `is_allowed` 질의)를 `_build_app` → `create_agora_app` → `Dispatcher`로 배선한다. 배선은 *동작 변경 없는 리팩터*로 먼저 끝낸 뒤(빈 `CommMatrix`는 비활성 = all-allow), `dispatch`(worker target → `comm_denied` 거부)와 `broadcast`(금지 worker target 필터 + `denied` 보고)에 검사를 켠다. 파일이 없으면 ACL 비활성. 봇·schema-routed dispatch는 매트릭스 밖.

**Tech Stack:** Python 3.13, FastMCP, SQLite(WAL), pytest + pytest-asyncio.

**범위:** spec [`2026-05-15-comm-matrix-design.md`](../specs/2026-05-15-comm-matrix-design.md)의 §8 구현 우선순위 전체. cc-agora bots(Plan 1 스키마 강제 + Plan 2 봇 라우팅)가 **이미 master에 머지된 상태를 전제**한다.

**현재 코드 기준 (이 plan의 출발점, master):**
- `Dispatcher.__init__(registry, persistence, write_queue, *, schema_registry, bot_registry, default_timeout_ms=..., ...)`.
- `dispatch(source, target, payload, ...)` — `target: str | None`; 본문에서 `target_kind`(`"worker"` | `"bot"` | `None`)를 정한 뒤 봇 fan-out한다.
- `broadcast(source, payload, ...)` — `targets`를 `_registry.list_instances()`(워커)에서 뽑고 봇 fan-out한다.
- `create_agora_app(agora_dir, instance_registry, schema_registry, bot_registry, persistence, dispatcher, port)`.
- `errors.py` — `AgoraError(ValueError)` + `ERROR_MESSAGES`. `__main__._build_app`가 `InstanceRegistry`/`BotRegistry`/`SchemaRegistry`를 구성·배선.
- `tests/_helpers.py` — `make_schema_registry()`, `tany()`, `wf()`. `conftest.py`에 `schema_registry`/`bot_registry` fixture.

---

## Spec 정합 보정

1. **`comm_denied`·`comm_matrix_shape_mismatch`는 `AgoraError`로 raise한다.** spec §3·§4.2는 `ValueError("comm_denied: ...")` / `ValueError("comm_matrix_shape_mismatch")`로 적었으나 — 현 코드베이스는 agora 도메인 에러를 `AgoraError`(= `ValueError` 서브클래스)로 통일하고 한국어 메시지를 `errors.py`의 `ERROR_MESSAGES`에 둔다(Plan 1). `AgoraError`는 `ValueError`라서 spec의 "ValueError" 요건을 만족하며 server.py의 `except (NotRegisteredError, ValueError)` 경로가 그대로 잡는다.
2. **comm-matrix 검사는 primary `target`에만 적용, cc observer는 미적용.** spec §4.2는 `dispatch(from, to)`와 `broadcast(from)`의 `to`만 명시한다. `cc` observer는 흐름 강제(§2 목적)의 대상이 아닌 *관찰자 지정*이므로 매트릭스 검사를 하지 않는다. 이를 §7-style 열린 점으로 기록한다.
3. **`Dispatcher`에 `comm_matrix` 주입.** spec §5·§8(item 3)대로 검사는 Dispatcher hook에 둔다 — `close_thread`의 내부 dispatch까지 broker가 일관 강제하기 위함. (`close_thread`는 내부 dispatch 실패를 `except (ValueError, NotRegisteredError): continue`로 흡수하므로, ACL이 한 참가자를 막아도 crash 없이 그 참가자 통지만 생략된다 — 허용 가능한 degrade.)

---

## File Structure

### 신규 파일
- `src/agent_agora/comm_matrix.py` — `CommMatrix`(CSV 파싱, shape 검증, `is_allowed`) + `load_comm_matrix(path)` 로더.
- `tests/test_v4_comm_matrix.py` — `CommMatrix` 단위 + dispatcher/server 통합 테스트.

### 수정 파일
- `src/agent_agora/errors.py` — `comm_denied`·`comm_matrix_shape_mismatch` 에러 코드.
- `src/agent_agora/dispatcher.py` — `comm_matrix` 주입; `dispatch` worker target ACL 검사; `broadcast` 금지 target 필터 + `denied`.
- `src/agent_agora/server.py` — `create_agora_app`에 `comm_matrix`; `agora.register_comm_matrix` 도구.
- `src/agent_agora/__main__.py` — `_build_app`에 `CommMatrix` 배선 + 시작 시 `.agentagora/comm-matrix.csv` 로드.
- `tests/conftest.py` — `comm_matrix` fixture.
- `tests/test_v3_dispatcher.py` · `test_v3_recovery.py` · `test_v3_ttl_gc.py` · `test_integration.py` · `test_v4_routing.py` · `test_v4_schema_enforcement.py` · `test_v4_bots.py` · `test_main.py` — `Dispatcher`/`create_agora_app` 생성 시그니처에 `comm_matrix` 추가.

### 책임 경계
- `comm_matrix.py` — ACL 데이터 + 질의. dispatch 모름.
- `dispatcher.py` — `comm_matrix`를 *소비*만 한다(worker 라우팅 게이트).
- `server.py` — `register_comm_matrix` 도구 표면.

---

## Task 1: errors.py — comm-matrix 에러 코드

**Files:**
- Modify: `src/agent_agora/errors.py`
- Create: `tests/test_v4_comm_matrix.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_comm_matrix.py`:

```python
import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES


def test_comm_matrix_error_codes_present():
    assert {"comm_denied", "comm_matrix_shape_mismatch"} <= set(ERROR_MESSAGES)


def test_comm_denied_message_formats_from_and_to():
    e = AgoraError("comm_denied", from_="Coder1", to="Tester1")
    assert e.code == "comm_denied"
    assert "Coder1" in str(e) and "Tester1" in str(e)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v`
Expected: FAIL — codes not in `ERROR_MESSAGES`.

- [ ] **Step 3: errors.py 수정** — `ERROR_MESSAGES` dict에 항목 추가(기존 코드들 뒤, dict 리터럴 안):

```python
    # comm-matrix codes
    "comm_denied": "[agora] comm_denied: {from_} -> {to} (통신 매트릭스가 이 쌍의 dispatch를 금지함).",
    "comm_matrix_shape_mismatch": "[agora] comm-matrix CSV shape 불일치: {detail}",
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/errors.py tests/test_v4_comm_matrix.py
git commit -m "feat: add comm-matrix error codes"
```

---

## Task 2: comm_matrix.py — CommMatrix + 로더

**Files:**
- Create: `src/agent_agora/comm_matrix.py`
- Test: `tests/test_v4_comm_matrix.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_comm_matrix.py`에 추가:

```python
from agent_agora.comm_matrix import CommMatrix, load_comm_matrix

_HUB = "\n".join([
    "Inst1,Coder1,Reviewer1,Tester1",
    "0,1,1,1",
    "1,0,0,0",
    "1,0,0,0",
    "1,0,0,0",
])


def test_fresh_matrix_is_inactive_and_allows_all():
    cm = CommMatrix()
    assert cm.active is False
    assert cm.is_allowed("anyone", "anyone_else") is True


def test_load_csv_activates_and_enforces_hub_and_spoke():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.active is True
    # row to=Inst1: all froms except self allowed
    assert cm.is_allowed("Coder1", "Inst1") is True
    assert cm.is_allowed("Inst1", "Inst1") is False
    # row to=Coder1: only Inst1 allowed
    assert cm.is_allowed("Inst1", "Coder1") is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False
    assert cm.is_allowed("Tester1", "Coder1") is False


def test_unregistered_worker_is_denied():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.is_allowed("Ghost", "Inst1") is False      # unknown from
    assert cm.is_allowed("Inst1", "Ghost") is False      # unknown to


def test_load_csv_rejects_row_count_mismatch():
    cm = CommMatrix()
    bad = "A,B,C\n0,1,1\n1,0,0"  # 3 header cols, only 2 data rows
    with pytest.raises(AgoraError) as ei:
        cm.load_csv(bad)
    assert ei.value.code == "comm_matrix_shape_mismatch"


def test_load_csv_rejects_column_count_mismatch():
    cm = CommMatrix()
    bad = "A,B,C\n0,1,1\n1,0\n1,0,0"  # row 2 has 2 cols, not 3
    with pytest.raises(AgoraError) as ei:
        cm.load_csv(bad)
    assert ei.value.code == "comm_matrix_shape_mismatch"


def test_load_csv_replaces_prior_matrix_in_place():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    cm.load_csv("A,B\n1,1\n1,1")  # fully-open 2-worker matrix
    assert cm.is_allowed("A", "B") is True
    assert cm.is_allowed("Coder1", "Inst1") is False  # old labels gone


def test_load_comm_matrix_absent_file_returns_inactive(tmp_path):
    cm = load_comm_matrix(tmp_path / "comm-matrix.csv")
    assert cm.active is False
    assert cm.is_allowed("x", "y") is True


def test_load_comm_matrix_present_file_loads(tmp_path):
    p = tmp_path / "comm-matrix.csv"
    p.write_text(_HUB, encoding="utf-8")
    cm = load_comm_matrix(p)
    assert cm.active is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False
```

(`AgoraError` is already imported at the top of `test_v4_comm_matrix.py` from Task 1.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v -k "matrix or load_csv or load_comm"`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.comm_matrix'`

- [ ] **Step 3: comm_matrix.py 구현** — `src/agent_agora/comm_matrix.py`:

```python
"""worker↔worker dispatch ACL — N×N comm matrix (comm-matrix design spec)."""
from __future__ import annotations

from pathlib import Path

from agent_agora.errors import AgoraError


class CommMatrix:
    """worker↔worker dispatch 권한. CSV로 로드. 비활성(파일 없음) 시 all-allow.

    `_allowed[to]` = `to`에게 dispatch가 허용된 `from` instance_id 집합.
    """

    def __init__(self) -> None:
        self._allowed: dict[str, set[str]] = {}
        self.active: bool = False

    def load_csv(self, csv_text: str) -> None:
        """CSV 텍스트(헤더 1줄 + 데이터 N줄, 셀 0/1)를 파싱해 매트릭스를 *제자리 교체*한다.
        shape 불일치 시 AgoraError(comm_matrix_shape_mismatch)."""
        rows = [line.split(",") for line in csv_text.splitlines() if line.strip()]
        if not rows:
            raise AgoraError("comm_matrix_shape_mismatch", detail="빈 CSV")
        header = [h.strip() for h in rows[0]]
        n = len(header)
        data = rows[1:]
        if len(data) != n:
            raise AgoraError(
                "comm_matrix_shape_mismatch",
                detail=f"데이터 {len(data)}행 != 헤더 {n}컬럼")
        allowed: dict[str, set[str]] = {}
        for i, row in enumerate(data):
            cells = [c.strip() for c in row]
            if len(cells) != n:
                raise AgoraError(
                    "comm_matrix_shape_mismatch",
                    detail=f"{i + 1}번째 데이터 행이 {len(cells)}컬럼 (헤더 {n}컬럼)")
            to_label = header[i]
            allowed[to_label] = {header[j] for j in range(n) if cells[j] == "1"}
        self._allowed = allowed
        self.active = True

    def is_allowed(self, from_: str, to: str) -> bool:
        """from_ -> to dispatch가 허용되는가. 비활성이면 항상 True.
        활성이면 strict whitelist — 미등재 from/to는 거부(False)."""
        if not self.active:
            return True
        return from_ in self._allowed.get(to, set())


def load_comm_matrix(path: Path) -> CommMatrix:
    """path의 comm-matrix.csv를 로드한다. 파일이 없으면 비활성 CommMatrix(all-allow)."""
    cm = CommMatrix()
    if path.exists():
        cm.load_csv(path.read_text("utf-8"))
    return cm
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/comm_matrix.py tests/test_v4_comm_matrix.py
git commit -m "feat: CommMatrix — CSV worker dispatch ACL + loader"
```

---

## Task 3: CommMatrix 배선 — 동작 변경 없는 리팩터

> `Dispatcher` 생성자에 `comm_matrix`를 주입하고 `_build_app`/`create_agora_app`/모든 테스트 fixture를 같은 커밋에서 갱신한다. `Dispatcher`는 `comm_matrix`를 *저장만* 한다 — `dispatch`/`broadcast`는 아직 `is_allowed`를 호출하지 않는다. 빈 `CommMatrix()`는 비활성이라 동작은 완전히 동일하다.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`, `src/agent_agora/server.py`, `src/agent_agora/__main__.py`
- Modify: `tests/conftest.py` + 모든 `Dispatcher(`/`create_agora_app(` 사용 테스트 파일
- Test: `tests/test_main.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_main.py`에 추가:

```python
def test_build_app_wires_comm_matrix(tmp_path):
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp = _build_app(agora_dir=agora_dir, port=0)
    comm_matrix = mcp._agora_comm_matrix
    # comm-matrix.csv가 없으므로 비활성 (all-allow)
    assert comm_matrix.active is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_main.py -v -k wires_comm`
Expected: FAIL — `AttributeError: ... _agora_comm_matrix`

- [ ] **Step 3: Dispatcher 생성자 수정** — `dispatcher.py`:

import 추가(기존 import 블록):
```python
from agent_agora.comm_matrix import CommMatrix
```

`Dispatcher.__init__` 시그니처에 `bot_registry` 다음 줄로 `comm_matrix`를 추가(keyword-only 필수):
```python
        *,
        schema_registry: SchemaRegistry,
        bot_registry: BotRegistry,
        comm_matrix: CommMatrix,
        default_timeout_ms: int = 60000,
```

`__init__` 본문, `self._bot_registry = bot_registry` 다음 줄에 추가:
```python
        self._comm_matrix = comm_matrix
```

이 task에서 `_comm_matrix`는 *저장만* 한다 — 어디서도 읽지 않는다.

- [ ] **Step 4: create_agora_app 시그니처 수정** — `server.py`:

import 추가:
```python
from agent_agora.comm_matrix import CommMatrix
```

`create_agora_app` 시그니처에 `bot_registry` 다음으로 `comm_matrix`를 추가:
```python
def create_agora_app(
    agora_dir: Path,
    instance_registry: InstanceRegistry,
    schema_registry: SchemaRegistry,
    bot_registry: BotRegistry,
    comm_matrix: CommMatrix,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
) -> FastMCP:
```

본문은 변경하지 않는다 — `comm_matrix`는 Task 6까지 미사용.

- [ ] **Step 5: __main__.py `_build_app` 수정**

`_build_app` 본문의 import 블록에 추가:
```python
    from agent_agora.comm_matrix import load_comm_matrix
```

`bot_registry = BotRegistry()` 다음, schema 로드부 *앞이나 뒤* 적절한 위치에 추가:
```python
    comm_matrix = load_comm_matrix(agora_dir / "comm-matrix.csv")
```

`Dispatcher(...)` 호출에 `bot_registry=bot_registry,` 다음 줄로 추가:
```python
        comm_matrix=comm_matrix,
```

`create_agora_app(...)` 호출에 `bot_registry=bot_registry,` 다음 줄로 추가:
```python
        comm_matrix=comm_matrix,
```

`mcp._agora_bot_registry = bot_registry  # type: ignore[attr-defined]` 다음 줄에 추가:
```python
    mcp._agora_comm_matrix = comm_matrix  # type: ignore[attr-defined]
```

- [ ] **Step 6: conftest.py — comm_matrix fixture**

`tests/conftest.py` 끝(`bot_registry` fixture 옆)에 추가:
```python
from agent_agora.comm_matrix import CommMatrix  # noqa: E402


@pytest.fixture
def comm_matrix():
    return CommMatrix()
```

- [ ] **Step 7: 모든 Dispatcher / create_agora_app 생성 사이트 갱신**

`grep -rn "Dispatcher(" tests/`와 `grep -rn "create_agora_app(" tests/`로 모든 생성 지점을 찾는다. 각 `Dispatcher(...)`에 `comm_matrix=CommMatrix()`를 추가, 각 `create_agora_app(...)`에 `comm_matrix=...`를 추가한다. 해당 테스트 파일 상단에 `from agent_agora.comm_matrix import CommMatrix` import를 추가한다.

예 — `Dispatcher(` 사이트:
```python
dispatcher = Dispatcher(registry, persistence, queue,
                        schema_registry=make_schema_registry(),
                        bot_registry=BotRegistry(),
                        comm_matrix=CommMatrix(),
                        default_timeout_ms=500)
```

`test_v4_bots.py`/`test_v4_schema_enforcement.py`의 `app` fixture는 `create_agora_app`도 호출하므로 — fixture 본문에서 `comm_matrix = CommMatrix()`를 만들어 `Dispatcher`와 `create_agora_app` 두 호출에 같은 인스턴스를 넘긴다.

대상 파일: `test_v3_dispatcher.py`, `test_v3_recovery.py`, `test_v3_ttl_gc.py`, `test_integration.py`, `test_v4_routing.py`, `test_v4_schema_enforcement.py`, `test_v4_bots.py` — grep 결과를 신뢰해 빠짐없이 적용.

- [ ] **Step 8: 전체 테스트 + 부팅 스모크**

Run: `pytest tests/ -v` — 전체 통과(기존 + 신규 1, 회귀 0 — 순수 리팩터).

Boot smoke (임시 dir, Bash timeout ~8000ms):
`& 'C:\Users\Jooyo\AppData\Roaming\uv\tools\agent-agora\Scripts\python.exe' -m agent_agora --dir $env:TEMP\agora_cmt3 --port 8781 --no-tls --no-timeout`
Expected: `AgentAgora starting on ...`, traceback 없음. 이후 임시 dir 삭제.

- [ ] **Step 9: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/server.py src/agent_agora/__main__.py tests/
git commit -m "refactor: wire CommMatrix through build_app/create_agora_app/Dispatcher (no behavior change)"
```

---

## Task 4: Dispatcher.dispatch — comm_denied 검사

> worker→worker primary dispatch만 검사한다. 봇 target·schema-routed(`target=None`)·cc observer는 검사 밖.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_comm_matrix.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_comm_matrix.py`에 추가:

```python
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.bot_registry import BotRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.comm_matrix import CommMatrix
from _helpers import make_schema_registry, tany


async def _make_dispatcher(tmp_path, comm_matrix):
    registry = InstanceRegistry()
    for name in ("Inst1", "Coder1", "Reviewer1", "Tester1"):
        registry.register(f"sess-{name}", name)
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    return registry, persistence, queue


@pytest.mark.asyncio
async def test_dispatch_denied_pair_raises_comm_denied(tmp_path):
    cm = CommMatrix()
    cm.load_csv(_HUB)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        # Coder1 -> Reviewer1 is denied by hub-and-spoke
        with pytest.raises(AgoraError) as ei:
            await d.dispatch(source="Coder1", target="Reviewer1", payload=tany(m=1))
        assert ei.value.code == "comm_denied"


@pytest.mark.asyncio
async def test_dispatch_allowed_pair_passes(tmp_path):
    cm = CommMatrix()
    cm.load_csv(_HUB)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        # Coder1 -> Inst1 is allowed (worker -> hub)
        res = await d.dispatch(source="Coder1", target="Inst1", payload=tany(m=1))
        assert res["command_id"]
        drained = await d.wait("Inst1", timeout_ms=200)
        assert len(drained) == 1


@pytest.mark.asyncio
async def test_dispatch_inactive_matrix_allows_all(tmp_path):
    cm = CommMatrix()  # inactive
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        res = await d.dispatch(source="Coder1", target="Reviewer1", payload=tany(m=1))
        assert res["command_id"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v -k "denied_pair or allowed_pair or inactive_matrix"`
Expected: `test_dispatch_denied_pair_raises_comm_denied` FAIL — dispatch가 ACL을 검사하지 않음.

- [ ] **Step 3: dispatch에 검사 추가**

`dispatcher.py`의 `dispatch` 메서드에서, target resolution 블록 다음(즉 `for c in cc_list: self._registry.resolve_instance_id(c)` 루프 *다음 줄*), `# 봇 체커` 주석 *앞*에 추가:

```python
        # comm-matrix ACL — worker→worker primary dispatch만 검사 (봇·schema-routed·cc 제외)
        if target_kind == "worker" and not self._comm_matrix.is_allowed(source, target):
            raise AgoraError("comm_denied", from_=source, to=target)
```

(`target_kind == "worker"`이면 `target`은 non-None str이다. `is_allowed`는 비활성 매트릭스에서 항상 True라 기존 테스트는 영향받지 않는다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체 — 회귀 0, 기존 테스트는 비활성 매트릭스)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_comm_matrix.py
git commit -m "feat: dispatch() enforces comm-matrix ACL on worker targets"
```

---

## Task 5: Dispatcher.broadcast — 금지 target 필터 + denied 보고

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_comm_matrix.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_comm_matrix.py`에 추가:

```python
@pytest.mark.asyncio
async def test_broadcast_filters_denied_targets_and_reports(tmp_path):
    cm = CommMatrix()
    cm.load_csv(_HUB)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        # Inst1 broadcasts — hub -> all spokes is allowed
        res1 = await d.broadcast(source="Inst1", payload=tany(m=1))
        assert res1["denied"] == []
        delivered = {x["instance_id"] for x in res1["dispatched_to"]}
        assert delivered == {"Coder1", "Reviewer1", "Tester1"}
        # Coder1 broadcasts — only Coder1 -> Inst1 allowed; spokes denied
        res2 = await d.broadcast(source="Coder1", payload=tany(m=2))
        assert {x["instance_id"] for x in res2["dispatched_to"]} == {"Inst1"}
        assert sorted(res2["denied"]) == ["Reviewer1", "Tester1"]


@pytest.mark.asyncio
async def test_broadcast_inactive_matrix_denied_empty(tmp_path):
    cm = CommMatrix()  # inactive
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        res = await d.broadcast(source="Coder1", payload=tany(m=1))
        assert res["denied"] == []
        assert {x["instance_id"] for x in res["dispatched_to"]} == {"Inst1", "Reviewer1", "Tester1"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v -k broadcast`
Expected: FAIL — `KeyError: 'denied'` / 모든 target에 전달됨.

- [ ] **Step 3: broadcast에 필터 추가**

`dispatcher.py`의 `broadcast` 메서드에서, `targets = [...]` 리스트 컴프리헨션 *다음 줄*(즉 `subscriber_bots = ...` 줄 *앞*)에 추가:

```python
        # comm-matrix ACL — 금지된 worker target은 fan-out에서 제외, denied로 보고
        denied: list[str] = []
        allowed_targets: list[str] = []
        for t in targets:
            (allowed_targets if self._comm_matrix.is_allowed(source, t) else denied).append(t)
        targets = allowed_targets
        denied.sort()
```

`broadcast`의 반환 dict에 `"denied": denied`를 추가한다. 반환 dict에서 `"skipped_full": skipped_full,` 줄 옆(같은 dict 안)에:

```python
            "denied": denied,
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체 — 비활성 매트릭스에서 `denied`는 항상 `[]`)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_comm_matrix.py
git commit -m "feat: broadcast() filters comm-matrix-denied targets, reports denied"
```

---

## Task 6: server.py — agora.register_comm_matrix 도구

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v4_comm_matrix.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_comm_matrix.py`에 추가:

```python
import json
from agent_agora.server import create_agora_app


class _FakeCtx:
    def __init__(self, session_id):
        self.request_context = type("RC", (), {"request": type("R", (), {
            "headers": {"mcp-session-id": session_id}})()})()


def _tool(mcp, name):
    return mcp._tool_manager.get_tool(name).fn


@pytest.fixture
async def cm_app(tmp_path):
    instance_registry = InstanceRegistry()
    for name in ("Inst1", "Coder1", "Reviewer1", "Tester1"):
        instance_registry.register(f"sess-{name}", name)
    bot_registry = BotRegistry()
    comm_matrix = CommMatrix()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, default_timeout_ms=200)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            comm_matrix=comm_matrix, persistence=persistence,
            dispatcher=dispatcher, port=0)
        yield mcp, dispatcher, comm_matrix


@pytest.mark.asyncio
async def test_register_comm_matrix_activates_acl(cm_app):
    mcp, dispatcher, comm_matrix = cm_app
    res = json.loads(await _tool(mcp, "agora.register_comm_matrix")(csv_text=_HUB))
    assert res["status"] == "ok"
    assert comm_matrix.active is True
    # ACL now enforced through the shared CommMatrix instance
    r = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Coder1"), payload=tany(m=1), target="Reviewer1"))
    assert "comm_denied" in r["error"]


@pytest.mark.asyncio
async def test_register_comm_matrix_rejects_bad_shape(cm_app):
    mcp, _, comm_matrix = cm_app
    res = json.loads(await _tool(mcp, "agora.register_comm_matrix")(
        csv_text="A,B,C\n0,1,1\n1,0,0"))
    assert "shape" in res["error"]
    assert comm_matrix.active is False  # rejected — not activated
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v -k register_comm_matrix`
Expected: FAIL — `agora.register_comm_matrix` 도구 없음.

- [ ] **Step 3: server.py에 도구 추가**

`create_agora_app` 안, `agora.register_schema` 도구 *다음*에 추가(이 nested 함수는 `comm_matrix`를 closure로 잡는다):

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

> `comm_matrix.load_csv`는 `CommMatrix`를 *제자리 교체*하므로(Task 2), `Dispatcher`가 들고 있는 같은 인스턴스의 ACL이 즉시 갱신된다 — 새 객체를 만들지 않는다. shape 불일치로 `load_csv`가 raise하면 기존 매트릭스 상태가 보존된다(부분 적용 없음 — `load_csv`는 검증을 모두 통과한 뒤에야 `self._allowed`/`self.active`를 쓴다).

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 회귀 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체)

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_comm_matrix.py
git commit -m "feat: agora.register_comm_matrix tool — runtime ACL replacement"
```

---

## Task 7: 통합 테스트 + backlog 갱신

**Files:**
- Modify: `tests/test_v4_comm_matrix.py` (추가)
- Modify: `docs/backlog.md`

- [ ] **Step 1: 통합 테스트 작성** — `tests/test_v4_comm_matrix.py`에 추가. spec §8 item 5의 시나리오를 커버한다:

```python
@pytest.mark.asyncio
async def test_no_file_means_all_allow(tmp_path):
    """comm-matrix.csv가 없으면 ACL 비활성 — 모든 worker↔worker dispatch 허용."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp = _build_app(agora_dir=agora_dir, port=0)
    assert mcp._agora_comm_matrix.active is False


@pytest.mark.asyncio
async def test_startup_loads_comm_matrix_file(tmp_path):
    """서버 시작 시 .agentagora/comm-matrix.csv가 있으면 ACL 활성."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    (agora_dir / "comm-matrix.csv").write_text(_HUB, encoding="utf-8")
    mcp = _build_app(agora_dir=agora_dir, port=0)
    cm = mcp._agora_comm_matrix
    assert cm.active is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False


@pytest.mark.asyncio
async def test_hub_and_spoke_enforced_end_to_end(cm_app):
    """hub-and-spoke: 워커는 hub에만 회신, 워커끼리 직접 dispatch 차단."""
    mcp, _, _ = cm_app
    await _tool(mcp, "agora.register_comm_matrix")(csv_text=_HUB)
    # spoke -> spoke denied
    r1 = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(m=1), target="Tester1"))
    assert "comm_denied" in r1["error"]
    # spoke -> hub allowed
    r2 = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(m=1), target="Inst1"))
    assert r2["status"] == "ok"


@pytest.mark.asyncio
async def test_unregistered_worker_denied(cm_app):
    """CSV 미등재 워커는 from/to 모두 거부 (strict whitelist)."""
    mcp, _, _ = cm_app
    await _tool(mcp, "agora.register_comm_matrix")(csv_text="Inst1,Coder1\n0,1\n1,0")
    # Reviewer1 is registered as a worker but absent from this 2-worker matrix
    r = json.loads(await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Inst1"), payload=tany(m=1), target="Reviewer1"))
    assert "comm_denied" in r["error"]


@pytest.mark.asyncio
async def test_broadcast_partial_filter_through_tool(cm_app):
    """agora.broadcast도 매트릭스 필터 — denied 목록 보고."""
    mcp, _, _ = cm_app
    await _tool(mcp, "agora.register_comm_matrix")(csv_text=_HUB)
    res = json.loads(await _tool(mcp, "agora.broadcast")(
        _FakeCtx("sess-Coder1"), payload=tany(m=1)))
    assert res["status"] == "ok"
    assert sorted(res["denied"]) == ["Reviewer1", "Tester1"]
```

- [ ] **Step 2: 통합 테스트 통과 확인**

Run: `pytest tests/test_v4_comm_matrix.py -v`
Expected: PASS (전체)

- [ ] **Step 3: 전체 테스트 + 부팅 스모크**

Run: `pytest tests/ -v` — 전체 통과, 회귀 0.

Boot smoke (임시 dir, Bash timeout ~8000ms):
`& 'C:\Users\Jooyo\AppData\Roaming\uv\tools\agent-agora\Scripts\python.exe' -m agent_agora --dir $env:TEMP\agora_cmt7 --port 8782 --no-tls --no-timeout`
Expected: `AgentAgora starting on ...`, traceback 없음. 이후 임시 dir 삭제.

- [ ] **Step 4: backlog 갱신** — `docs/backlog.md`의 "통신 매트릭스" 항목을 **구현 완료**로 갱신. `CommMatrix`(CSV ACL), `dispatch`/`broadcast` 검사, `agora.register_comm_matrix` 도구. 남은 후속은 spec §7(런타임 등록분 영속, 동적 워커 자동 행·열, role 기반 ACL, 매트릭스 조회 도구). 간결하게, backlog.md 스타일(한국어·terse) 유지.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_v4_comm_matrix.py docs/backlog.md
git commit -m "test: comm-matrix integration — hub-and-spoke, startup load, broadcast filter"
```

---

## 완료 기준

- [ ] `pytest tests/ -v` 전체 통과 (회귀 0).
- [ ] `.agentagora/comm-matrix.csv` 없으면 ACL 비활성(all-allow), 있으면 whitelist 강제.
- [ ] worker→worker `dispatch`가 금지 쌍에서 `comm_denied` 거부, `broadcast`가 금지 target을 필터하고 `denied`로 보고.
- [ ] `agora.register_comm_matrix`로 런타임 ACL 교체, shape 불일치 거부.
- [ ] 봇·schema-routed dispatch는 매트릭스 검사 밖.

## 범위 밖 (후속 — spec §7)

- 런타임 등록(`register_comm_matrix`) 매트릭스의 영속 — 현재 재시작 시 휘발(파일만 재로드). 파일 write-back / SQLite 저장은 후속.
- 동적 워커 자동 행·열 추가 (현재 미등재 = deny).
- role 쌍 기반 ACL (현재 instance_id 단위).
- `cc` observer는 매트릭스 검사 밖 (본 plan Spec 정합 보정 #2) — cc까지 ACL 적용이 필요하면 후속.
- 매트릭스 조회 도구 `agora.comm_matrix()` (ACL이 dispatch 거부로만 드러나면 디버깅이 어렵다 — spec §7).
