# Interactive Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 대시보드를 운영자(사람)가 직접 워커에 dispatch/broadcast하고 답신 받는 인터랙티브 다중 운영자 UI로 진화시킨다. 메시지·인박스 드릴다운, SSE 푸시 갱신, trust+token 두 모드 인증, 서버 헬스 메트릭 포함.

**Architecture:** Pseudo-instance `operator:<username>` 모델로 기존 dispatcher/registry 재사용. envelope에 `reply_only` 필드 추가. dispatcher event hook + `dashboard_events` pub/sub로 SSE 푸시. `dashboard_auth` 미들웨어로 swap-ready 인증. 새 정적 자산 디렉터리 + vendored Tabulator·JSONEditor.

**Tech Stack:** Python 3.13 (Starlette·StaticFiles·dataclasses·asyncio), SQLite (acked_at 컬럼 마이그레이션), pytest, vanilla JS + EventSource + localStorage, Tabulator (정렬·필터 테이블), JSONEditor (schema 기반 payload 폼).

**Spec:** `docs/superpowers/specs/2026-05-21-interactive-dashboard-design.md`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/agent_agora/envelope.py` | 메시지 envelope schema (+ `reply_only` 필드) |
| `src/agent_agora/registry.py` | instance_registry — `operator:` 네임스페이스 lazy 등록 |
| `src/agent_agora/sweeper.py` | dead-session GC — operator 면제 + 통계 노출 |
| `src/agent_agora/comm_matrix.py` | dispatch ACL — operator bypass 규칙 |
| `src/agent_agora/dispatcher.py` | 메시지 라우터 + event hook (on_dispatch·on_register·on_unregister) |
| `src/agent_agora/persistence.py` | SQLite WAL — `acked_at` 컬럼 + write queue depth getter |
| `src/agent_agora/dashboard_health.py` | **신규** — uptime·db_size·queue·sweeper 메트릭 수집 |
| `src/agent_agora/dashboard_auth.py` | **신규** — trust·token 인증 미들웨어 |
| `src/agent_agora/dashboard_events.py` | **신규** — SSE pub/sub + dispatcher hook 구독 |
| `src/agent_agora/dashboard_routes.py` | 9개 신규 엔드포인트 + StaticFiles mount + /data 확장 |
| `src/agent_agora/dashboard.html` | 교체 — shell + script tags |
| `src/agent_agora/dashboard_static/css/dashboard.css` | 신규 스타일 |
| `src/agent_agora/dashboard_static/js/api.js` | fetch wrapper + 인증 헤더 자동 첨부 |
| `src/agent_agora/dashboard_static/js/stream.js` | EventSource wrapper + 재연결 + 폴링 fallback |
| `src/agent_agora/dashboard_static/js/login.js` | mode-aware 로그인 모달 |
| `src/agent_agora/dashboard_static/js/dashboard.js` | 메인 hydration + 레이아웃 |
| `src/agent_agora/dashboard_static/js/health.js` | 서버 헬스 카드 |
| `src/agent_agora/dashboard_static/js/dispatch.js` | dispatch 모달 |
| `src/agent_agora/dashboard_static/js/inbox.js` | 운영자 인박스 패널 |
| `src/agent_agora/dashboard_static/js/drilldown.js` | 대화·인박스 드릴다운 모달 |
| `src/agent_agora/dashboard_static/vendor/{tabulator.min.js,tabulator.min.css,jsoneditor.min.js,jsoneditor.min.css}` | 벤더 라이브러리 |
| `plugin/cc-agora/skills/agora-protocol/SKILL.md` | reply_only 존중 규칙 한 줄 |
| `docs/dashboard.md` | 신규 기능·SSE·인증·원격 설정 가이드 |

---

## Task 1: envelope `reply_only` 필드

**Files:**
- Modify: `src/agent_agora/envelope.py`
- Test: `tests/test_envelope.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_envelope.py` (create if not exists):

```python
"""Envelope 직렬화·검증 단위 테스트."""
from __future__ import annotations

from agent_agora.envelope import Envelope, envelope_from_dict, envelope_to_dict


def test_envelope_reply_only_default_false():
    env = Envelope(
        message_id="m1", conversation_id="c1",
        sender="operator:alice", recipient="worker1",
        schema="test", payload={"q": 1}, timestamp="2026-05-21T00:00:00Z",
    )
    assert env.reply_only is False


def test_envelope_reply_only_roundtrip():
    env = Envelope(
        message_id="m1", conversation_id="c1",
        sender="operator:alice", recipient="worker1",
        schema="test", payload={"q": 1}, timestamp="2026-05-21T00:00:00Z",
        reply_only=True,
    )
    data = envelope_to_dict(env)
    assert data["reply_only"] is True
    back = envelope_from_dict(data)
    assert back.reply_only is True


def test_envelope_from_dict_missing_reply_only_defaults_false():
    data = {
        "message_id": "m1", "conversation_id": "c1",
        "sender": "operator:alice", "recipient": "worker1",
        "schema": "test", "payload": {"q": 1},
        "timestamp": "2026-05-21T00:00:00Z",
        # reply_only 누락
    }
    env = envelope_from_dict(data)
    assert env.reply_only is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_envelope.py -v`
Expected: FAIL — `reply_only` 속성 또는 `envelope_from_dict`/`envelope_to_dict` 함수 미존재.

- [ ] **Step 3: Read current envelope.py**

Read `src/agent_agora/envelope.py` to identify the existing Envelope dataclass / serializer pattern. The field/function names in Step 1's test must match what's actually used in the existing code. If function names differ (e.g., `Envelope.to_dict()` method vs free function), adjust both the test and impl to match the existing convention before proceeding.

- [ ] **Step 4: Add reply_only field + serialization**

In `src/agent_agora/envelope.py`, add `reply_only: bool = False` to the Envelope dataclass (or equivalent class). Ensure both serialization (`to_dict` / `envelope_to_dict`) emit the field, and deserialization (`from_dict` / `envelope_from_dict`) reads it with a default of `False` if missing.

- [ ] **Step 5: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_envelope.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Run full suite (regression)**

Run: `py -3.13 -m pytest tests/ -q`
Expected: all pass (existing envelope tests still green; reply_only is additive).

- [ ] **Step 7: Commit**

```bash
git add src/agent_agora/envelope.py tests/test_envelope.py
git commit -m "feat: envelope.reply_only 필드 (default False)"
```

---

## Task 2: registry `operator:<x>` 네임스페이스 지원

**Files:**
- Modify: `src/agent_agora/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_register_operator_pseudo_instance():
    reg = InstanceRegistry()
    reg.register(
        session_id="dashboard:alice", instance_id="operator:alice",
        role="operator", description="Dashboard operator",
    )
    info = reg.resolve_instance_id("operator:alice")
    assert info is not None
    assert info.instance_id == "operator:alice"
    assert info.role == "operator"


def test_is_operator_helper():
    from agent_agora.registry import is_operator
    assert is_operator("operator:alice") is True
    assert is_operator("operator:") is False  # 접두사만 있고 username 없음
    assert is_operator("Worker1") is False
    assert is_operator("") is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_registry.py -v`
Expected: FAIL — `is_operator` import 실패.

- [ ] **Step 3: Add `is_operator` helper to registry.py**

Add to `src/agent_agora/registry.py` (module level, before InstanceRegistry class):

```python
OPERATOR_PREFIX = "operator:"


def is_operator(instance_id: str) -> bool:
    """True iff instance_id is a dashboard operator pseudo-instance.

    Pseudo-instances use the `operator:<username>` namespace and are
    exempt from sweeper GC and comm-matrix ACL.
    """
    if not instance_id.startswith(OPERATOR_PREFIX):
        return False
    return len(instance_id) > len(OPERATOR_PREFIX)
```

(`InstanceRegistry.register` requires no change — `operator:<x>` is just another instance_id from its perspective. Lazy registration happens in the dashboard routes layer.)

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_registry.py -v`
Expected: all pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/registry.py tests/test_registry.py
git commit -m "feat: registry operator:<x> 네임스페이스 helper"
```

---

## Task 3: sweeper operator 면제 + 실행 통계

**Files:**
- Modify: `src/agent_agora/sweeper.py`
- Test: `tests/test_sweeper.py` (또는 기존 sweeper 테스트 파일)

- [ ] **Step 1: Discover existing sweeper tests**

Run: `ls tests/test_sweeper*.py 2>/dev/null; grep -l "sweeper\|Sweeper" tests/*.py | head -5`
If `tests/test_sweeper.py` exists, append to it. Else create new file with appropriate imports (study an existing test file for the import pattern).

- [ ] **Step 2: Write the failing tests**

Add to the test file:

```python
import time
from agent_agora.registry import InstanceRegistry
from agent_agora.sweeper import Sweeper  # or actual class name — verify


def test_sweeper_skips_operator_instances():
    reg = InstanceRegistry()
    # 운영자: last_seen이 아무리 오래 전이어도 GC 면제
    reg.register(session_id="dashboard:alice", instance_id="operator:alice",
                 role="operator", description="op")
    reg.touch_last_seen("operator:alice", ts=time.time() - 99999)

    # 일반 워커: TTL 초과 시 GC 대상
    reg.register(session_id="s1", instance_id="Worker1",
                 role="coder", description="w")
    reg.touch_last_seen("Worker1", ts=time.time() - 99999)

    sweeper = Sweeper(instance_registry=reg, dead_session_ttl=300)
    removed = sweeper.sweep_dead_sessions()
    assert "operator:alice" not in removed
    assert "Worker1" in removed


def test_sweeper_exposes_run_stats():
    reg = InstanceRegistry()
    sweeper = Sweeper(instance_registry=reg, dead_session_ttl=300)
    assert sweeper.runs_total == 0
    assert sweeper.last_run_at is None

    sweeper.sweep_dead_sessions()
    assert sweeper.runs_total == 1
    assert sweeper.last_run_at is not None
```

Adjust class/method names to match the actual `sweeper.py` after reading it.

- [ ] **Step 3: Read sweeper.py and adapt**

Read `src/agent_agora/sweeper.py`. Identify the sweep method and dead-session GC loop. The test names/structure must match the real API — adjust the test code if names differ.

- [ ] **Step 4: Implement operator exemption + stats**

In `src/agent_agora/sweeper.py`:
- Import `is_operator` from `agent_agora.registry`.
- In the dead-session GC loop, skip any instance where `is_operator(instance_id)` is True.
- Add instance attributes `runs_total: int = 0` and `last_run_at: float | None = None`. Increment / update at the end of each sweep run.

- [ ] **Step 5: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_sweeper.py tests/test_registry.py -v`
Expected: all pass.

- [ ] **Step 6: Run full suite (regression)**

Run: `py -3.13 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/agent_agora/sweeper.py tests/test_sweeper.py
git commit -m "feat: sweeper operator 인스턴스 GC 면제 + 실행 통계 노출"
```

---

## Task 4: comm_matrix operator bypass

**Files:**
- Modify: `src/agent_agora/comm_matrix.py`
- Test: `tests/test_comm_matrix.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_comm_matrix.py`:

```python
def test_operator_bypasses_active_matrix():
    """operator:<x>는 매트릭스 활성 여부와 무관하게 dispatch 양방향 allow."""
    matrix = CommMatrix()
    # 워커끼리 일부만 허용되는 매트릭스 로드
    matrix.load_csv("from,Worker1,Worker2\nWorker1,0,1\nWorker2,0,0\n")
    assert matrix.active

    # 워커→워커: 매트릭스 따름
    assert matrix.is_allowed(sender="Worker1", recipient="Worker2") is True
    assert matrix.is_allowed(sender="Worker2", recipient="Worker1") is False

    # 운영자 → 어떤 워커든 allow
    assert matrix.is_allowed(sender="operator:alice", recipient="Worker2") is True
    assert matrix.is_allowed(sender="operator:bob", recipient="Worker1") is True

    # 어떤 워커든 → 운영자 allow (답신 경로)
    assert matrix.is_allowed(sender="Worker2", recipient="operator:alice") is True
    assert matrix.is_allowed(sender="Worker1", recipient="operator:bob") is True
```

(Test method names like `is_allowed` may not exist — read the file in Step 3 and adjust.)

- [ ] **Step 2: Run test to verify failure**

Run: `py -3.13 -m pytest tests/test_comm_matrix.py::test_operator_bypasses_active_matrix -v`
Expected: FAIL — assertion fails because matrix denies operator paths.

- [ ] **Step 3: Read comm_matrix.py**

Read `src/agent_agora/comm_matrix.py` to identify the dispatch-check method (likely named `is_allowed`, `check`, or similar). Adjust test method name in Step 1 to match.

- [ ] **Step 4: Implement bypass**

In the dispatch-check method, at the top, add:

```python
from agent_agora.registry import is_operator

if is_operator(sender) or is_operator(recipient):
    return True
```

(or whatever the truthy return value is — match the existing return type. If method is non-boolean check, raise vs return, mirror that.)

- [ ] **Step 5: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_comm_matrix.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/comm_matrix.py tests/test_comm_matrix.py
git commit -m "feat: comm_matrix operator:<x> dispatch bypass"
```

---

## Task 5: dispatcher event hooks

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_dispatcher_hooks.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dispatcher_hooks.py`:

```python
"""dispatcher.py의 event hook 등록·발화·예외 안전 검증."""
from __future__ import annotations

import pytest

from agent_agora.dispatcher import Dispatcher  # adjust if class name differs


def test_dispatch_hook_called(dispatcher_fixture):
    """dispatch 발생 시 on_dispatch hook이 envelope과 함께 호출된다."""
    captured: list = []
    dispatcher_fixture.register_dispatch_hook(lambda env: captured.append(env))

    dispatcher_fixture.dispatch_envelope(_build_envelope("Worker1"))

    assert len(captured) == 1
    assert captured[0].recipient == "Worker1"


def test_register_hook_called(dispatcher_fixture, instance_registry):
    captured: list = []
    dispatcher_fixture.register_register_hook(lambda info: captured.append(info))

    instance_registry.register(
        session_id="s1", instance_id="W1", role="coder", description="d")

    assert len(captured) == 1
    assert captured[0].instance_id == "W1"


def test_hook_exception_does_not_break_dispatch(dispatcher_fixture):
    """hook이 raise해도 dispatch 본 로직은 진행."""
    def bad(env): raise RuntimeError("boom")
    dispatcher_fixture.register_dispatch_hook(bad)
    # 예외 swallow + dispatch는 성공해야 함
    result = dispatcher_fixture.dispatch_envelope(_build_envelope("Worker1"))
    assert result is not None  # 본 dispatch 성공
```

The fixtures `dispatcher_fixture`, `instance_registry`, `_build_envelope` need to be defined in a conftest.py or in this test file. Look at existing dispatcher tests in `tests/test_v4_*` for the established fixture pattern and reuse.

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dispatcher_hooks.py -v`
Expected: FAIL — `register_dispatch_hook` / `register_register_hook` methods missing.

- [ ] **Step 3: Implement hooks in dispatcher.py**

Add to `src/agent_agora/dispatcher.py` (inside `Dispatcher` class or wherever appropriate):

```python
import logging

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, ...):  # existing __init__
        # ... existing init ...
        self._dispatch_hooks: list = []
        self._register_hooks: list = []
        self._unregister_hooks: list = []

    def register_dispatch_hook(self, callback) -> None:
        """callback(envelope) — dispatch 발생 시 호출."""
        self._dispatch_hooks.append(callback)

    def register_register_hook(self, callback) -> None:
        """callback(instance_info) — 인스턴스 등록 시 호출."""
        self._register_hooks.append(callback)

    def register_unregister_hook(self, callback) -> None:
        """callback(instance_id) — 인스턴스 해제 시 호출."""
        self._unregister_hooks.append(callback)

    def _fire_dispatch_hooks(self, envelope) -> None:
        for cb in self._dispatch_hooks:
            try:
                cb(envelope)
            except Exception:
                logger.exception("dispatch hook raised")

    def _fire_register_hooks(self, info) -> None:
        for cb in self._register_hooks:
            try:
                cb(info)
            except Exception:
                logger.exception("register hook raised")

    def _fire_unregister_hooks(self, instance_id: str) -> None:
        for cb in self._unregister_hooks:
            try:
                cb(instance_id)
            except Exception:
                logger.exception("unregister hook raised")
```

Call `_fire_dispatch_hooks(envelope)` after a successful dispatch in `dispatch_envelope` (or equivalent method). For register/unregister hooks, the cleanest is to have `InstanceRegistry` emit them, or wire dispatcher to observe registry. **Pragmatic choice**: have the dashboard auto-register code (Task 8/9 layer) call `_fire_register_hooks` directly when it creates operator instances. For worker register/unregister observation, see Task 9's notes — `dashboard_events` may subscribe via the registry's existing observer pattern if any, or hook into `auto_register.py`. Defer that wiring to Task 9; Task 5 only adds the hook infrastructure on Dispatcher and the dispatch path firing.

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dispatcher_hooks.py -v`
Expected: `test_dispatch_hook_called` and `test_hook_exception_does_not_break_dispatch` pass. `test_register_hook_called` may need adjustment depending on where register hooks fire (see Step 3 note) — if registry doesn't fire the hook directly, test must call `dispatcher._fire_register_hooks(info)` manually. Adjust test to match wiring.

- [ ] **Step 5: Run full suite**

Run: `py -3.13 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/dispatcher.py tests/test_dispatcher_hooks.py
git commit -m "feat: dispatcher event hooks (dispatch·register·unregister) + 예외 안전"
```

---

## Task 6: persistence write_queue_depth

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_persistence.py` (또는 기존 파일에 추가)

- [ ] **Step 1: Discover write queue location**

Run: `grep -n "AsyncWriteQueue\|write_queue\|_queue" src/agent_agora/persistence.py | head -10`
Identify the queue object and its measurable size attribute (likely `qsize()` on `asyncio.Queue`).

- [ ] **Step 2: Write the failing test**

Append to the appropriate test file:

```python
def test_write_queue_depth_initially_zero(persistence_fixture):
    assert persistence_fixture.write_queue_depth() == 0


def test_write_queue_depth_reports_queued_items(persistence_fixture):
    # 큐에 미처리 항목을 push (실제 enqueue API 사용)
    persistence_fixture.enqueue_dummy_write()
    persistence_fixture.enqueue_dummy_write()
    assert persistence_fixture.write_queue_depth() >= 2
```

(`enqueue_dummy_write` is a test helper to bypass the actual write path — match it to the persistence API. If the enqueue is auto-drained by a background task, ensure the test pauses the drain or uses a backpressure scenario.)

- [ ] **Step 3: Add write_queue_depth method**

In `src/agent_agora/persistence.py`, add a method on the persistence/AsyncWriteQueue class:

```python
def write_queue_depth(self) -> int:
    """Current async write queue depth — operator dashboard health metric."""
    return self._queue.qsize()  # adjust to actual queue attribute
```

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_persistence.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/persistence.py tests/test_persistence.py
git commit -m "feat: persistence.write_queue_depth() — 헬스 메트릭"
```

---

## Task 7: dashboard_health 모듈 (메트릭 수집)

**Files:**
- Create: `src/agent_agora/dashboard_health.py`
- Test: `tests/test_dashboard_health.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_health.py`:

```python
"""dashboard_health 메트릭 수집 단위 테스트."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent_agora.dashboard_health import HealthCollector


class _FakePersistence:
    def __init__(self, depth: int) -> None:
        self._depth = depth

    def write_queue_depth(self) -> int:
        return self._depth


class _FakeSweeper:
    dead_session_sweep_runs_total = 5
    dead_session_sweep_last_run_at = 1700000000.0


def test_uptime_seconds_increases(tmp_path):
    db = tmp_path / "agora.db"
    db.write_bytes(b"x" * 1024)  # 1KB

    started_at = time.time() - 60.0
    health = HealthCollector(
        started_at=started_at, db_path=db,
        persistence=_FakePersistence(0), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["uptime_seconds"] >= 60
    assert snap["uptime_seconds"] < 70


def test_db_size_reflects_file_size(tmp_path):
    db = tmp_path / "agora.db"
    db.write_bytes(b"x" * 4096)

    health = HealthCollector(
        started_at=time.time(), db_path=db,
        persistence=_FakePersistence(0), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["db_size_bytes"] == 4096


def test_write_queue_and_sweeper_passthrough(tmp_path):
    db = tmp_path / "agora.db"
    db.write_bytes(b"")

    health = HealthCollector(
        started_at=time.time(), db_path=db,
        persistence=_FakePersistence(7), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["write_queue_depth"] == 7
    assert snap["sweeper_runs_total"] == 5
    assert snap["sweeper_last_run_at"] == 1700000000.0


def test_missing_db_file_returns_null(tmp_path):
    """DB 파일이 없으면 db_size_bytes는 None (collector는 raise 안 함)."""
    health = HealthCollector(
        started_at=time.time(), db_path=tmp_path / "missing.db",
        persistence=_FakePersistence(0), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["db_size_bytes"] is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_health.py -v`
Expected: FAIL — `HealthCollector` not importable.

- [ ] **Step 3: Implement dashboard_health.py**

Create `src/agent_agora/dashboard_health.py`:

```python
"""대시보드 서버 헬스 메트릭 수집기.

읽기만 하는 collector — 외부 상태(서버 시작 시각, DB 경로, persistence,
sweeper)를 참조해 snapshot dict를 만든다. 어느 메트릭이든 수집 실패 시
None으로 폴백 (전체 snapshot이 깨지지 않도록).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class HealthCollector:
    started_at: float
    db_path: Path
    persistence: Any  # write_queue_depth() 메서드 보유
    sweeper: Any      # runs_total, last_run_at 속성 보유

    def snapshot(self) -> dict:
        return {
            "uptime_seconds": self._uptime(),
            "db_size_bytes": self._db_size(),
            "write_queue_depth": self._queue_depth(),
            "sweeper_runs_total": self._sweeper_runs(),
            "sweeper_last_run_at": self._sweeper_last(),
        }

    def _uptime(self) -> int:
        try:
            return int(time.time() - self.started_at)
        except Exception:
            return None

    def _db_size(self) -> int | None:
        try:
            return self.db_path.stat().st_size
        except (OSError, FileNotFoundError):
            return None

    def _queue_depth(self) -> int | None:
        try:
            return int(self.persistence.write_queue_depth())
        except Exception:
            return None

    def _sweeper_runs(self) -> int | None:
        try:
            return int(self.sweeper.dead_session_sweep_runs_total)
        except Exception:
            return None

    def _sweeper_last(self) -> float | None:
        try:
            return self.sweeper.dead_session_sweep_last_run_at
        except Exception:
            return None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_health.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dashboard_health.py tests/test_dashboard_health.py
git commit -m "feat: dashboard_health 모듈 — uptime·db_size·queue·sweeper 메트릭"
```

---

## Task 8: dashboard_auth 모듈 (trust + token)

**Files:**
- Create: `src/agent_agora/dashboard_auth.py`
- Test: `tests/test_dashboard_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_auth.py`:

```python
"""dashboard_auth 미들웨어 — trust·token 두 모드 검증."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agent_agora.dashboard_auth import DashboardAuthMiddleware, parse_tokens


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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_auth.py -v`
Expected: all FAIL — module not importable.

- [ ] **Step 3: Implement dashboard_auth.py**

Create `src/agent_agora/dashboard_auth.py`:

```python
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


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, mode: str, tokens: dict[str, str],
                 protected_paths: list[str]) -> None:
        super().__init__(app)
        self._mode = mode
        # token 모드 lookup: token → username
        self._token_to_user = {v: k for k, v in tokens.items()}
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
        # trust mode (and any unknown mode falls through to trust for safety —
        # operator must explicitly set token mode to gate)
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
        result[user.strip()] = token.strip()
    return result
```

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_auth.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dashboard_auth.py tests/test_dashboard_auth.py
git commit -m "feat: dashboard_auth 미들웨어 — trust·token 두 모드 (impersonation 방지)"
```

---

## Task 9: dashboard_events 모듈 (SSE pub/sub)

**Files:**
- Create: `src/agent_agora/dashboard_events.py`
- Test: `tests/test_dashboard_events.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_events.py`:

```python
"""dashboard_events pub/sub — SSE broker 단위 테스트."""
from __future__ import annotations

import asyncio
import pytest

from agent_agora.dashboard_events import EventBroker


@pytest.mark.asyncio
async def test_subscriber_receives_broadcast():
    broker = EventBroker(max_queue=100)
    sub = broker.subscribe(operator_user="alice")
    broker.publish({"type": "data_snapshot", "payload": {"x": 1}})
    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert evt == {"type": "data_snapshot", "payload": {"x": 1}}


@pytest.mark.asyncio
async def test_two_subscribers_each_receive():
    broker = EventBroker(max_queue=100)
    a = broker.subscribe(operator_user="alice")
    b = broker.subscribe(operator_user="bob")
    broker.publish({"type": "instance_registered", "instance_id": "W1"})
    ea = await asyncio.wait_for(a.get(), timeout=1.0)
    eb = await asyncio.wait_for(b.get(), timeout=1.0)
    assert ea == eb


@pytest.mark.asyncio
async def test_operator_inbox_event_routes_to_target_only():
    """operator_inbox_message는 target_operator 매칭 구독자에게만 전달."""
    broker = EventBroker(max_queue=100)
    a = broker.subscribe(operator_user="alice")
    b = broker.subscribe(operator_user="bob")
    broker.publish({
        "type": "operator_inbox_message",
        "target_operator": "alice",
        "envelope_preview": {"sender": "W1"},
    })
    # alice 받음
    ea = await asyncio.wait_for(a.get(), timeout=1.0)
    assert ea["target_operator"] == "alice"
    # bob에겐 안 옴 (1초 timeout으로 빈 큐 확인)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(b.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    broker = EventBroker(max_queue=100)
    sub = broker.subscribe(operator_user="alice")
    broker.unsubscribe(sub)
    broker.publish({"type": "data_snapshot"})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_queue_overflow_drops_oldest():
    broker = EventBroker(max_queue=3)
    sub = broker.subscribe(operator_user="alice")
    for i in range(5):
        broker.publish({"type": "data_snapshot", "i": i})
    # queue 최대 3개 보유 + 가장 오래된 것 drop
    items = []
    for _ in range(3):
        items.append(await asyncio.wait_for(sub.get(), timeout=0.2))
    indices = [item["i"] for item in items]
    assert indices == [2, 3, 4]  # 0, 1 dropped
    # 더 이상 항목 없음
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_attach_to_dispatcher_hooks():
    """attach_to_dispatcher가 dispatch/register/unregister hook을 등록."""
    class FakeDispatcher:
        def __init__(self) -> None:
            self.d_hooks = []
            self.r_hooks = []
            self.u_hooks = []
        def register_dispatch_hook(self, cb): self.d_hooks.append(cb)
        def register_register_hook(self, cb): self.r_hooks.append(cb)
        def register_unregister_hook(self, cb): self.u_hooks.append(cb)

    d = FakeDispatcher()
    broker = EventBroker(max_queue=100)
    broker.attach_to_dispatcher(d)
    assert len(d.d_hooks) == 1
    assert len(d.r_hooks) == 1
    assert len(d.u_hooks) == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_events.py -v`
Expected: FAIL — module not importable.

- [ ] **Step 3: Implement dashboard_events.py**

Create `src/agent_agora/dashboard_events.py`:

```python
"""대시보드 SSE 이벤트 브로커 — in-process pub/sub.

각 SSE 구독자마다 asyncio.Queue. publisher는 모든 큐에 broadcast.
operator_inbox_message는 target_operator 매칭 구독자에게만 전달.
큐 overflow 시 가장 오래된 이벤트를 drop.

attach_to_dispatcher로 dispatcher의 event hook에 자동 구독 — dispatch·
register·unregister 이벤트를 SSE 이벤트로 변환해 publish.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Subscriber:
    operator_user: str
    queue: asyncio.Queue

    async def get(self) -> dict:
        return await self.queue.get()


class EventBroker:
    def __init__(self, *, max_queue: int = 1000) -> None:
        self._subscribers: list[Subscriber] = []
        self._max_queue = max_queue

    def subscribe(self, *, operator_user: str) -> Subscriber:
        q: asyncio.Queue = asyncio.Queue()
        sub = Subscriber(operator_user=operator_user, queue=q)
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        try:
            self._subscribers.remove(sub)
        except ValueError:
            pass

    def publish(self, event: dict) -> None:
        """이벤트를 모든 매칭 구독자에게 비동기 broadcast.

        operator_inbox_message는 target_operator 매칭 구독자에게만.
        큐 만원이면 가장 오래된 이벤트 drop.
        """
        target = event.get("target_operator") if event.get("type") == "operator_inbox_message" else None
        for sub in self._subscribers:
            if target is not None and sub.operator_user != target:
                continue
            self._push(sub, event)

    def _push(self, sub: Subscriber, event: dict) -> None:
        q = sub.queue
        if q.qsize() >= self._max_queue:
            # drop oldest non-blockingly
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(event)

    def attach_to_dispatcher(self, dispatcher) -> None:
        """dispatcher의 event hook에 자동 구독."""
        dispatcher.register_dispatch_hook(self._on_dispatch)
        dispatcher.register_register_hook(self._on_register)
        dispatcher.register_unregister_hook(self._on_unregister)

    def _on_dispatch(self, envelope) -> None:
        self.publish({
            "type": "message_dispatched",
            "from": getattr(envelope, "sender", None),
            "to": getattr(envelope, "recipient", None),
            "schema": getattr(envelope, "schema", None),
            "conversation_id": getattr(envelope, "conversation_id", None),
            "timestamp": getattr(envelope, "timestamp", None),
        })
        # 운영자 대상 메시지면 별도 이벤트로도 publish
        recipient = getattr(envelope, "recipient", "") or ""
        if recipient.startswith("operator:"):
            self.publish({
                "type": "operator_inbox_message",
                "target_operator": recipient[len("operator:"):],
                "sender": getattr(envelope, "sender", None),
                "schema": getattr(envelope, "schema", None),
                "timestamp": getattr(envelope, "timestamp", None),
            })

    def _on_register(self, info) -> None:
        self.publish({
            "type": "instance_registered",
            "instance_id": getattr(info, "instance_id", None),
            "role": getattr(info, "role", None),
        })

    def _on_unregister(self, instance_id: str) -> None:
        self.publish({
            "type": "instance_unregistered",
            "instance_id": instance_id,
        })
```

- [ ] **Step 4: Install pytest-asyncio if missing**

Run: `py -3.13 -c "import pytest_asyncio" 2>&1 | head -1`
If error: `py -3.13 -m pip install pytest-asyncio` and add `[tool.pytest.ini_options] asyncio_mode = "auto"` to `pyproject.toml` (or `pytest.ini`).

- [ ] **Step 5: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_events.py -v`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/dashboard_events.py tests/test_dashboard_events.py pyproject.toml
git commit -m "feat: dashboard_events 모듈 — SSE pub/sub + dispatcher hook 구독"
```

---

## Task 10: dashboard_routes — dispatch + broadcast + operator inbox

**Files:**
- Modify: `src/agent_agora/dashboard_routes.py`
- Modify: `src/agent_agora/persistence.py` (acked_at 컬럼 마이그레이션)
- Test: `tests/test_dashboard_routes.py`

- [ ] **Step 1: Add acked_at column to messages table**

In `src/agent_agora/persistence.py`, locate the messages table creation SQL. Add an `acked_at REAL` column (nullable). Add a startup migration: `ALTER TABLE messages ADD COLUMN acked_at REAL` wrapped in try/except (SQLite raises if column already exists; treat as idempotent).

- [ ] **Step 2: Write the failing tests for dispatch + inbox**

Create or extend `tests/test_dashboard_routes.py`:

```python
"""dashboard_routes — dispatch·broadcast·operator inbox 통합 테스트."""
from __future__ import annotations

import json
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def dashboard_client(real_server_app):
    """real_server_app: 실제 dispatcher·registry·dashboard_routes 와이어된 Starlette app.
    설정: trust 모드 인증. conftest.py에 픽스처 정의."""
    return TestClient(real_server_app)


def _auth(user: str) -> dict:
    return {"X-Agora-Operator-User": user}


def test_dispatch_to_specific_worker(dashboard_client, register_worker):
    register_worker("W1", role="coder")
    r = dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message",
        "payload": {"text": "hi"}, "reply_only": False,
    })
    assert r.status_code == 201
    body = r.json()
    assert "message_id" in body
    assert "conversation_id" in body


def test_dispatch_to_nonexistent_worker_404(dashboard_client):
    r = dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "DoesNotExist", "schema": "operator_message",
        "payload": {}, "reply_only": False,
    })
    assert r.status_code == 404


def test_broadcast_to_multiple_workers(dashboard_client, register_worker):
    register_worker("W1"); register_worker("W2")
    r = dashboard_client.post("/dashboard/broadcast", headers=_auth("alice"), json={
        "targets": ["W1", "W2"], "schema": "operator_message",
        "payload": {"text": "all"}, "reply_only": True,
    })
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 2
    assert all("message_id" in res for res in results)


def test_broadcast_empty_targets_422(dashboard_client):
    r = dashboard_client.post("/dashboard/broadcast", headers=_auth("alice"), json={
        "targets": [], "schema": "operator_message", "payload": {},
        "reply_only": False,
    })
    assert r.status_code == 422


def test_operator_inbox_empty_initially(dashboard_client):
    r = dashboard_client.get("/dashboard/operator/inbox", headers=_auth("alice"))
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_operator_inbox_receives_reply(dashboard_client, register_worker, post_reply_from_worker):
    register_worker("W1")
    # 운영자 → 워커 dispatch
    dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message",
        "payload": {"q": 1}, "reply_only": True,
    })
    # 워커 → 운영자 답신 (test 헬퍼로 직접 dispatcher 호출)
    post_reply_from_worker("W1", "operator:alice", {"answer": 42})

    r = dashboard_client.get("/dashboard/operator/inbox", headers=_auth("alice"))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "W1"
    assert msgs[0]["payload"] == {"answer": 42}


def test_operator_inbox_ack_removes_from_default_view(dashboard_client, register_worker, post_reply_from_worker):
    register_worker("W1")
    dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message", "payload": {},
        "reply_only": True,
    })
    post_reply_from_worker("W1", "operator:alice", {"a": 1})
    msgs = dashboard_client.get("/dashboard/operator/inbox", headers=_auth("alice")).json()["messages"]
    msg_id = msgs[0]["message_id"]

    r = dashboard_client.post("/dashboard/operator/inbox/ack", headers=_auth("alice"), json={
        "message_ids": [msg_id],
    })
    assert r.status_code == 200

    # 기본 view에서 미반환
    msgs2 = dashboard_client.get("/dashboard/operator/inbox", headers=_auth("alice")).json()["messages"]
    assert len(msgs2) == 0

    # include_acked=true면 보임
    msgs3 = dashboard_client.get("/dashboard/operator/inbox?include_acked=true", headers=_auth("alice")).json()["messages"]
    assert len(msgs3) == 1
    assert msgs3[0]["message_id"] == msg_id
```

The fixtures (`real_server_app`, `register_worker`, `post_reply_from_worker`) need to be added to `tests/conftest.py` — these are integration helpers that wire dispatcher + registry + dashboard_routes for testing. Look at how existing dispatcher tests set up the dispatcher and reuse that scaffolding.

- [ ] **Step 3: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_routes.py -v`
Expected: FAIL — endpoints not implemented.

- [ ] **Step 4: Implement dispatch + broadcast + operator inbox + ack endpoints**

In `src/agent_agora/dashboard_routes.py`, add 4 new endpoints (sketch):

```python
async def dispatch_endpoint(request: Request) -> JSONResponse:
    """POST /dashboard/dispatch — sender=operator:<user>."""
    body = await request.json()
    to = body.get("to"); schema = body.get("schema")
    payload = body.get("payload", {}); reply_only = bool(body.get("reply_only", False))
    conv = body.get("conversation_id")
    if not to:
        return JSONResponse({"error": "to required"}, status_code=422)
    user = request.state.operator_user
    sender = f"operator:{user}"
    # Lazy register operator if missing
    if instance_registry.resolve_instance_id(sender) is None:
        instance_registry.register(
            session_id=f"dashboard:{user}", instance_id=sender,
            role="operator", description=f"Dashboard operator {user}",
        )
    # 워커 존재 확인
    if instance_registry.resolve_instance_id(to) is None:
        return JSONResponse({"error": "recipient not registered"}, status_code=404)
    try:
        result = dispatcher.dispatch(  # 실제 메서드명 dispatch.py에서 확인
            sender=sender, recipient=to, schema=schema,
            payload=payload, reply_only=reply_only, conversation_id=conv,
        )
    except AgoraError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return JSONResponse({
        "message_id": result.message_id,
        "conversation_id": result.conversation_id,
    }, status_code=201)


async def broadcast_endpoint(request: Request) -> JSONResponse:
    body = await request.json()
    targets = body.get("targets") or []
    if not targets:
        return JSONResponse({"error": "targets required"}, status_code=422)
    user = request.state.operator_user
    sender = f"operator:{user}"
    if instance_registry.resolve_instance_id(sender) is None:
        instance_registry.register(
            session_id=f"dashboard:{user}", instance_id=sender,
            role="operator", description=f"Dashboard operator {user}",
        )
    results = []
    for to in targets:
        try:
            r = dispatcher.dispatch(
                sender=sender, recipient=to, schema=body.get("schema"),
                payload=body.get("payload", {}),
                reply_only=bool(body.get("reply_only", False)),
            )
            results.append({"to": to, "message_id": r.message_id})
        except Exception as e:
            results.append({"to": to, "error": str(e)})
    return JSONResponse({"results": results})


async def operator_inbox_endpoint(request: Request) -> JSONResponse:
    user = request.state.operator_user
    sender = f"operator:{user}"
    include_acked = request.query_params.get("include_acked") == "true"
    # persistence에서 sender의 모든 메시지 (혹은 acked_at IS NULL 기본)
    msgs = persistence.fetch_messages_for(recipient=sender, include_acked=include_acked)
    return JSONResponse({"messages": [m.to_dict() for m in msgs]})


async def operator_inbox_ack_endpoint(request: Request) -> JSONResponse:
    body = await request.json()
    ids = body.get("message_ids") or []
    persistence.mark_messages_acked(ids)
    return JSONResponse({"acked": len(ids)})
```

Wire these via `app.router.routes.append(Route(...))` in the existing `register()`. The functions `persistence.fetch_messages_for` and `persistence.mark_messages_acked` will need to be added in this task as well (small queries on `messages` table with `acked_at` filter).

- [ ] **Step 5: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_routes.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/dashboard_routes.py src/agent_agora/persistence.py tests/test_dashboard_routes.py tests/conftest.py
git commit -m "feat: dashboard /dispatch /broadcast /operator/inbox /ack 엔드포인트 + acked_at 컬럼"
```

---

## Task 11: dashboard_routes — drilldown (conversation, instance inbox, schemas)

**Files:**
- Modify: `src/agent_agora/dashboard_routes.py`
- Test: `tests/test_dashboard_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_routes.py`:

```python
def test_conversation_thread_returns_all_messages(dashboard_client, register_worker, post_reply_from_worker):
    register_worker("W1")
    sent = dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message", "payload": {"q": 1},
        "reply_only": False,
    }).json()
    conv_id = sent["conversation_id"]
    post_reply_from_worker("W1", "operator:alice", {"answer": 42}, conversation_id=conv_id)

    r = dashboard_client.get(f"/dashboard/conversation/{conv_id}", headers=_auth("alice"))
    assert r.status_code == 200
    thread = r.json()["messages"]
    assert len(thread) == 2
    assert thread[0]["payload"] == {"q": 1}
    assert thread[1]["payload"] == {"answer": 42}


def test_instance_inbox_returns_worker_inbox(dashboard_client, register_worker):
    register_worker("W1")
    dashboard_client.post("/dashboard/dispatch", headers=_auth("alice"), json={
        "to": "W1", "schema": "operator_message", "payload": {"task": "x"},
        "reply_only": False,
    })
    r = dashboard_client.get("/dashboard/instance/W1/inbox", headers=_auth("alice"))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) >= 1
    assert msgs[0]["payload"] == {"task": "x"}


def test_schemas_catalog(dashboard_client):
    r = dashboard_client.get("/dashboard/schemas", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()
    assert "schemas" in body
    assert isinstance(body["schemas"], list)
    # 적어도 하나의 default schema가 등록되어 있어야 함
    assert len(body["schemas"]) > 0
    assert "id" in body["schemas"][0]
    assert "schema" in body["schemas"][0]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_routes.py::test_conversation_thread_returns_all_messages -v`
Expected: FAIL — endpoint 미구현.

- [ ] **Step 3: Implement endpoints**

In `dashboard_routes.py`:

```python
async def conversation_endpoint(request: Request) -> JSONResponse:
    conv_id = request.path_params["conversation_id"]
    msgs = persistence.fetch_messages_for(conversation_id=conv_id)
    return JSONResponse({"messages": [m.to_dict() for m in msgs]})


async def instance_inbox_endpoint(request: Request) -> JSONResponse:
    instance_id = request.path_params["instance_id"]
    msgs = dispatcher.get_inbox_messages(instance_id)  # 실제 메서드명 검증
    return JSONResponse({"messages": [m.to_dict() for m in msgs]})


async def schemas_endpoint(request: Request) -> JSONResponse:
    # schemas.py의 schema registry 사용
    items = [{"id": s.id, "schema": s.json_schema} for s in schema_registry.list_all()]
    return JSONResponse({"schemas": items})
```

Wire via Route(). The exact `persistence.fetch_messages_for(conversation_id=...)`, `dispatcher.get_inbox_messages(...)`, `schema_registry.list_all()` APIs need to be added or named to match existing methods — verify by reading dispatcher.py, persistence.py, schemas.py first.

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_routes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dashboard_routes.py src/agent_agora/persistence.py tests/test_dashboard_routes.py
git commit -m "feat: dashboard /conversation /instance/inbox /schemas 드릴다운 엔드포인트"
```

---

## Task 12: dashboard_routes — SSE stream + auth-mode + /data 확장 + StaticFiles

**Files:**
- Modify: `src/agent_agora/dashboard_routes.py`
- Test: `tests/test_dashboard_routes.py` (확장) + `tests/test_dashboard_static.py` (신규)

- [ ] **Step 1: Write the failing tests for /data extension + /auth-mode**

Append to `tests/test_dashboard_routes.py`:

```python
def test_data_includes_server_health(dashboard_client):
    r = dashboard_client.get("/dashboard/data", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()
    assert "server" in body
    health = body["server"]
    assert "uptime_seconds" in health
    assert "db_size_bytes" in health
    assert "write_queue_depth" in health
    assert "sweeper_runs_total" in health


def test_auth_mode_returns_current_mode(dashboard_client):
    """/dashboard/auth-mode는 인증 없이 접근 가능."""
    # 헤더 없이도 200
    r = dashboard_client.get("/dashboard/auth-mode")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("trust", "token")
```

Create `tests/test_dashboard_static.py`:

```python
"""Static asset mount 검증."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "agent_agora" / "dashboard_static"


def test_vendor_libraries_present():
    assert (STATIC_DIR / "vendor" / "tabulator.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "tabulator.min.css").is_file()
    assert (STATIC_DIR / "vendor" / "jsoneditor.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "jsoneditor.min.css").is_file()


def test_js_modules_present():
    for name in ("api.js", "stream.js", "login.js", "dashboard.js",
                 "health.js", "dispatch.js", "inbox.js", "drilldown.js"):
        assert (STATIC_DIR / "js" / name).is_file(), f"missing js/{name}"


def test_dashboard_css_present():
    assert (STATIC_DIR / "css" / "dashboard.css").is_file()


def test_static_route_served(dashboard_client):
    """/dashboard/static/* 가 StaticFiles로 mount되어 응답."""
    r = dashboard_client.get("/dashboard/static/js/api.js", headers=_auth("alice"))
    assert r.status_code == 200
    assert "fetch" in r.text or "X-Agora-Operator-User" in r.text  # api.js 식별 문자열
```

(Vendor / JS files are created in Task 13+. This test will fail until those tasks land — keep the test for forward compatibility; this task only tests /data, /auth-mode, /stream.)

- [ ] **Step 2: Write the failing test for SSE stream**

Append to `tests/test_dashboard_routes.py`:

```python
def test_stream_endpoint_emits_initial_snapshot(dashboard_client):
    """SSE 첫 응답으로 data_snapshot 이벤트 1회 push."""
    with dashboard_client.stream("GET", "/dashboard/stream", headers=_auth("alice")) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        # 첫 이벤트 (timeout 1s 내)
        first_event = ""
        for chunk in r.iter_text():
            first_event += chunk
            if "\n\n" in first_event:
                break
        assert "data:" in first_event
        # parse SSE data line
        data_line = next((l for l in first_event.split("\n") if l.startswith("data:")), None)
        assert data_line is not None
        import json as _json
        parsed = _json.loads(data_line[len("data:"):].strip())
        assert parsed["type"] == "data_snapshot"
```

- [ ] **Step 3: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_routes.py::test_data_includes_server_health tests/test_dashboard_routes.py::test_auth_mode_returns_current_mode tests/test_dashboard_routes.py::test_stream_endpoint_emits_initial_snapshot -v`
Expected: FAIL.

- [ ] **Step 4: Implement /data extension + /auth-mode + /stream + StaticFiles mount**

In `dashboard_routes.py` (or its `register()`):

```python
from starlette.responses import StreamingResponse
from starlette.staticfiles import StaticFiles
from starlette.routing import Mount
import asyncio
import json

# (build_dashboard_data를 server health 포함하도록 확장)
def build_dashboard_data(*, dispatcher, instance_registry, bot_registry,
                        comm_matrix, health_collector) -> dict:
    data = _existing_build(...)  # 기존 로직
    data["server"] = health_collector.snapshot()
    return data


# /auth-mode (unprotected — auth middleware의 protected_paths에서 제외)
async def auth_mode_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"mode": auth_mode_value})


# /stream
async def stream_endpoint(request: Request) -> StreamingResponse:
    user = request.state.operator_user
    sub = event_broker.subscribe(operator_user=user)

    async def gen():
        # 초기 hydration
        snapshot = build_dashboard_data(...)
        yield f"data: {json.dumps({'type': 'data_snapshot', 'payload': snapshot})}\n\n"
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(sub.get(), timeout=30.0)
                    yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # SSE keepalive
        finally:
            event_broker.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream")


# StaticFiles mount + 라우트 등록
def register(app, *, dispatcher, instance_registry, bot_registry, comm_matrix,
             health_collector, event_broker, auth_mode_value):
    # ... 기존 라우트 ...
    static_dir = Path(__file__).with_name("dashboard_static")
    app.router.routes.append(Mount("/dashboard/static", app=StaticFiles(directory=static_dir)))
    app.router.routes.append(Route("/dashboard/auth-mode", auth_mode_endpoint, methods=["GET"]))
    app.router.routes.append(Route("/dashboard/stream", stream_endpoint, methods=["GET"]))
```

Server boot (`__main__.py`나 `server.py`)에서 health_collector·event_broker 인스턴스 생성·연결 + `app.add_middleware(DashboardAuthMiddleware, mode=mode, tokens=tokens, protected_paths=["/dashboard/data", "/dashboard/dispatch", "/dashboard/broadcast", "/dashboard/operator", "/dashboard/conversation", "/dashboard/instance", "/dashboard/schemas", "/dashboard/stream"])`. `/dashboard`(HTML shell)와 `/dashboard/static`, `/dashboard/auth-mode`는 unprotected. event_broker는 dispatcher event hook에 attach.

- [ ] **Step 5: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_routes.py tests/test_dashboard_static.py -v`
Expected: `test_data_includes_server_health`, `test_auth_mode_returns_current_mode`, `test_stream_endpoint_emits_initial_snapshot`, `test_static_route_served` pass. Other static tests (vendor·js 파일 존재 검증) FAIL — 다음 task에서 채워짐. **이 task에서는 "static route served"까지만 통과시키면 됨.**

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/dashboard_routes.py tests/test_dashboard_routes.py tests/test_dashboard_static.py
git commit -m "feat: dashboard /stream(SSE) /auth-mode /data(+health) + StaticFiles mount"
```

---

## Task 13: Frontend shell + vendored libraries + CSS

**Files:**
- Modify: `src/agent_agora/dashboard.html`
- Create: `src/agent_agora/dashboard_static/css/dashboard.css`
- Create: `src/agent_agora/dashboard_static/vendor/{tabulator.min.js,tabulator.min.css,jsoneditor.min.js,jsoneditor.min.css}`

- [ ] **Step 1: Vendor libraries**

Download Tabulator and JSONEditor minified bundles and place them under `src/agent_agora/dashboard_static/vendor/`.

```bash
# 정확한 URL은 각 라이브러리 npm/GitHub release에서 확인.
# Tabulator (≥5.5): https://unpkg.com/tabulator-tables@5.5/dist/{js/tabulator.min.js,css/tabulator.min.css}
# JSONEditor (≥10): https://unpkg.com/@json-editor/json-editor/dist/jsoneditor.js (min 빌드 사용)
# 4파일 다운로드 후 vendor/에 배치.
```

운영자 머신 인터넷 없는 경우 대비 vendored. 외부 URL을 plan 텍스트에 박지 말고 README/dashboard.md에 출처 명시.

- [ ] **Step 2: Replace dashboard.html with shell**

Overwrite `src/agent_agora/dashboard.html`:

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>AgentAgora — 팀 현황</title>
<link rel="stylesheet" href="/dashboard/static/vendor/tabulator.min.css">
<link rel="stylesheet" href="/dashboard/static/vendor/jsoneditor.min.css">
<link rel="stylesheet" href="/dashboard/static/css/dashboard.css">
</head>
<body>
<div id="login-modal" class="hidden">
  <div class="login-card">
    <h2>AgentAgora 대시보드</h2>
    <label>Username <input id="login-username" type="text" autofocus></label>
    <label id="login-token-label" class="hidden">Token <input id="login-token" type="password"></label>
    <button id="login-submit">접속</button>
  </div>
</div>
<header id="header" class="hidden">
  <span class="title">AgentAgora — <span id="who"></span></span>
  <span id="conn-indicator">●</span>
  <span id="health-summary"></span>
  <button id="logout">로그아웃</button>
</header>
<main id="main" class="hidden">
  <aside id="left-panel">
    <section id="inbox-panel"></section>
    <section id="health-detail"></section>
  </aside>
  <section id="center-panel">
    <div id="summary-cards"></div>
    <div id="instances-table"></div>
    <div id="conversations-table"></div>
    <div id="bots-table"></div>
    <div id="comm-matrix"></div>
  </section>
  <button id="open-dispatch" class="fab">+ 보내기</button>
</main>
<div id="dispatch-modal" class="modal hidden"></div>
<div id="drilldown-modal" class="modal hidden"></div>
<script src="/dashboard/static/vendor/tabulator.min.js"></script>
<script src="/dashboard/static/vendor/jsoneditor.min.js"></script>
<script src="/dashboard/static/js/api.js"></script>
<script src="/dashboard/static/js/stream.js"></script>
<script src="/dashboard/static/js/login.js"></script>
<script src="/dashboard/static/js/health.js"></script>
<script src="/dashboard/static/js/inbox.js"></script>
<script src="/dashboard/static/js/dispatch.js"></script>
<script src="/dashboard/static/js/drilldown.js"></script>
<script src="/dashboard/static/js/dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create dashboard.css**

Create `src/agent_agora/dashboard_static/css/dashboard.css`:

```css
/* 다크 테마. 기존 dashboard.html의 색을 유지하면서 다중 패널 레이아웃. */
* { box-sizing: border-box; }
body { font: 13px/1.5 system-ui, sans-serif; background:#1a1a2e; color:#e8e8e8; margin:0; padding:0; }
.hidden { display: none !important; }

#login-modal { position:fixed; inset:0; background:rgba(0,0,0,0.7); display:flex; align-items:center; justify-content:center; z-index:100; }
.login-card { background:#252542; padding:24px; border-radius:8px; min-width:300px; }
.login-card label { display:block; margin:12px 0; }
.login-card input { width:100%; padding:6px; background:#1a1a2e; border:1px solid #33334d; color:#e8e8e8; }
.login-card button { width:100%; padding:8px; margin-top:12px; background:#3d3d6b; color:#e8e8e8; border:none; border-radius:4px; cursor:pointer; }

#header { display:flex; align-items:center; gap:16px; padding:8px 16px; background:#252542; border-bottom:1px solid #33334d; }
#header .title { font-weight:600; flex:1; }
#conn-indicator { font-size:14px; }
#conn-indicator.connected { color:#7ed321; }
#conn-indicator.fallback { color:#f5a623; }
#health-summary { font-size:12px; color:#9aa; }
#logout { background:none; border:1px solid #33334d; color:#e8e8e8; padding:4px 10px; cursor:pointer; border-radius:4px; }

#main { display:grid; grid-template-columns:280px 1fr; gap:12px; padding:12px; }
#left-panel section { background:#252542; padding:12px; border-radius:6px; margin-bottom:12px; }
#summary-cards { display:flex; gap:12px; margin-bottom:12px; }
#summary-cards .card { background:#252542; padding:12px 18px; border-radius:6px; flex:1; }
#summary-cards .card b { font-size:22px; display:block; }

.fab { position:fixed; right:24px; bottom:24px; background:#3d3d6b; color:#e8e8e8; border:none; padding:12px 20px; border-radius:30px; cursor:pointer; box-shadow:0 4px 12px rgba(0,0,0,0.4); font-size:14px; }
.fab:hover { background:#4d4d80; }

.modal { position:fixed; inset:0; background:rgba(0,0,0,0.7); display:flex; align-items:center; justify-content:center; z-index:50; }
.modal .modal-card { background:#252542; padding:24px; border-radius:8px; max-width:90vw; max-height:90vh; overflow:auto; min-width:500px; }

table { border-collapse:collapse; width:100%; }
.tabulator { background:#252542; }
.tabulator .tabulator-header { background:#1a1a2e; color:#9aa; }

.message-card { padding:8px; border-bottom:1px solid #33334d; }
.message-card .sender { color:#bbf; font-weight:600; }
.message-card .timestamp { color:#9aa; font-size:11px; }
.message-card .payload { background:#1a1a2e; padding:6px; border-radius:4px; font-family:monospace; font-size:11px; white-space:pre-wrap; }
.message-card .reply-only { color:#f5a623; font-size:10px; }

.hot { color:#ff9; font-weight:700; }

/* comm-matrix SVG (기존 dashboard.html에서 그대로) */
#comm-matrix svg { background:#252542; border-radius:6px; }
.node { fill:#3d3d6b; stroke:#8888c0; }
.nodelabel { fill:#e8e8e8; font-size:11px; text-anchor:middle; }
.edge { stroke:#7a7ad0; fill:none; }
.edgelabel { fill:#bbf; font-size:10px; text-anchor:middle; }
```

- [ ] **Step 4: Verify static tests pass**

Run: `py -3.13 -m pytest tests/test_dashboard_static.py -v`
Expected: vendor·js·css 파일 존재 검증 통과(아직 일부 js 파일은 placeholder일 수 있음 — Task 14~17에서 채워짐). `test_vendor_libraries_present`·`test_dashboard_css_present` pass; `test_js_modules_present`는 다음 task에서 통과.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dashboard.html src/agent_agora/dashboard_static/
git commit -m "feat: dashboard shell HTML + vendored Tabulator·JSONEditor + 다크 테마 CSS"
```

---

## Task 14: js/api.js + js/stream.js

**Files:**
- Create: `src/agent_agora/dashboard_static/js/api.js`
- Create: `src/agent_agora/dashboard_static/js/stream.js`

- [ ] **Step 1: Create api.js**

Create `src/agent_agora/dashboard_static/js/api.js`:

```javascript
// fetch wrapper — 인증 헤더 자동 첨부. mode에 따라 헤더 결정.
window.agoraApi = (function() {
  function authHeaders() {
    const user = localStorage.getItem('operator_username') || '';
    const tok = localStorage.getItem('operator_token') || '';
    const h = {'X-Agora-Operator-User': user};
    if (tok) h['Authorization'] = 'Bearer ' + tok;
    return h;
  }

  async function get(path) {
    const r = await fetch(path, {headers: authHeaders(), cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  }

  async function post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: {...authHeaders(), 'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error('HTTP ' + r.status), {status: r.status, body: json});
    return json;
  }

  return {get, post, authHeaders};
})();
```

- [ ] **Step 2: Create stream.js**

Create `src/agent_agora/dashboard_static/js/stream.js`:

```javascript
// EventSource wrapper — SSE 연결 + 재연결 backoff + 폴링 fallback + indicator.
window.agoraStream = (function() {
  let eventSource = null;
  let pollHandle = null;
  let backoffMs = 5000;
  const POLL_INTERVAL = 3000;
  const onEvent = {}; // type → listener[]

  function setIndicator(state) {
    const el = document.getElementById('conn-indicator');
    if (!el) return;
    el.className = state; // 'connected' | 'fallback' | ''
    el.textContent = state === 'connected' ? '● SSE' : (state === 'fallback' ? '○ poll' : '… connect');
  }

  function fire(evt) {
    const handlers = onEvent[evt.type] || [];
    for (const h of handlers) try { h(evt); } catch(e) { console.error(e); }
  }

  function startPolling() {
    if (pollHandle) return;
    setIndicator('fallback');
    pollHandle = setInterval(async () => {
      try {
        const snap = await window.agoraApi.get('/dashboard/data');
        fire({type: 'data_snapshot', payload: snap});
      } catch (e) { /* indicator already shows fallback */ }
    }, POLL_INTERVAL);
  }

  function stopPolling() {
    if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
  }

  function connect() {
    setIndicator('');
    // EventSource는 헤더 첨부 못 함 (스펙 한계). 인증 쿼리파라미터 또는 cookie 폴백이 필요.
    // 본 spec 범위: trust 모드는 헤더 없이도 동작하도록 path-level query param fallback. token 모드는 cookie 또는 query.
    const user = encodeURIComponent(localStorage.getItem('operator_username') || '');
    const tok = encodeURIComponent(localStorage.getItem('operator_token') || '');
    const qs = `?u=${user}` + (tok ? `&t=${tok}` : '');
    eventSource = new EventSource('/dashboard/stream' + qs);

    eventSource.onopen = () => {
      backoffMs = 5000;
      stopPolling();
      setIndicator('connected');
    };
    eventSource.onmessage = (m) => {
      try {
        const evt = JSON.parse(m.data);
        fire(evt);
      } catch(e) { console.error('SSE parse', e); }
    };
    eventSource.onerror = () => {
      eventSource.close();
      eventSource = null;
      startPolling();
      // exponential backoff
      setTimeout(connect, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 60000);
    };
  }

  function on(type, handler) {
    (onEvent[type] = onEvent[type] || []).push(handler);
  }

  return {connect, on};
})();
```

**중요:** EventSource는 커스텀 헤더 첨부 못 함. 위 구현은 username/token을 query string으로 보냄. 서버는 인증 미들웨어가 stream 엔드포인트에 대해 query param fallback도 지원해야 함. 또는 cookie 인증 도입. **Task 12 구현 시 이 점을 반영해야 함** — 미들웨어에 query-param fallback 추가 (path가 `/dashboard/stream`이고 헤더 없으면 `u`·`t` query를 헤더처럼 처리). plan 단계에서 이 의존성을 명시하고 Task 12 보강.

- [ ] **Step 3: Verify file existence**

Run: `py -3.13 -m pytest tests/test_dashboard_static.py::test_js_modules_present -v`
Expected: 일부 PASS (api·stream 추가됨). 나머지 js 파일은 미생성 — 다음 task들에서 채워짐.

- [ ] **Step 4: Commit**

```bash
git add src/agent_agora/dashboard_static/js/api.js src/agent_agora/dashboard_static/js/stream.js
git commit -m "feat: dashboard api.js + stream.js (EventSource + 폴링 fallback)"
```

---

## Task 14b: 인증 미들웨어 query-param fallback (Task 12 보강)

**Files:**
- Modify: `src/agent_agora/dashboard_auth.py`
- Modify: `tests/test_dashboard_auth.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_dashboard_auth.py`:

```python
def test_trust_mode_query_param_fallback_for_sse():
    """EventSource는 헤더 첨부 못함 — stream 경로는 ?u=<user> query 허용."""
    client = TestClient(_make_app("trust"))
    # 헤더 없이 query param만으로
    r = client.get("/whoami?u=alice")
    # whoami는 query fallback path가 아니므로 401
    assert r.status_code == 401


def test_trust_mode_stream_path_allows_query():
    """미들웨어 빌드 시 query_param_paths로 지정한 path는 query fallback."""
    from agent_agora.dashboard_auth import DashboardAuthMiddleware
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
    from agent_agora.dashboard_auth import DashboardAuthMiddleware
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `py -3.13 -m pytest tests/test_dashboard_auth.py::test_trust_mode_stream_path_allows_query -v`
Expected: FAIL — `query_param_paths` 인자 미지원.

- [ ] **Step 3: Extend DashboardAuthMiddleware**

Modify `src/agent_agora/dashboard_auth.py`:

```python
class DashboardAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, mode: str, tokens: dict[str, str],
                 protected_paths: list[str],
                 query_param_paths: list[str] | None = None) -> None:
        super().__init__(app)
        self._mode = mode
        self._token_to_user = {v: k for k, v in tokens.items()}
        self._protected = tuple(protected_paths)
        self._query_param_paths = tuple(query_param_paths or [])

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
            # query fallback
            if allow_query:
                token = request.query_params.get("t")
                if token:
                    return self._token_to_user.get(token)
            return None

        # trust mode
        user = (request.headers.get("x-agora-operator-user") or "").strip()
        if user:
            return user
        if allow_query:
            user = (request.query_params.get("u") or "").strip()
            return user or None
        return None
```

Server boot configuration: `app.add_middleware(DashboardAuthMiddleware, ..., query_param_paths=["/dashboard/stream"])`.

- [ ] **Step 4: Run tests to verify pass**

Run: `py -3.13 -m pytest tests/test_dashboard_auth.py -v`
Expected: 11 PASS (8 기존 + 3 신규).

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dashboard_auth.py tests/test_dashboard_auth.py
git commit -m "feat: dashboard_auth query-param fallback (SSE EventSource 헤더 제약 우회)"
```

---

## Task 15: js/login.js + js/dashboard.js + js/health.js

**Files:**
- Create: `src/agent_agora/dashboard_static/js/login.js`
- Create: `src/agent_agora/dashboard_static/js/dashboard.js`
- Create: `src/agent_agora/dashboard_static/js/health.js`

- [ ] **Step 1: Create login.js**

Create `src/agent_agora/dashboard_static/js/login.js`:

```javascript
// mode-aware 로그인 모달. /dashboard/auth-mode 호출해 token 필드 노출 여부 결정.
window.agoraLogin = (function() {
  let onAuthenticated = null;

  async function init(callback) {
    onAuthenticated = callback;
    const user = localStorage.getItem('operator_username');
    const tok = localStorage.getItem('operator_token');

    // mode 확인
    const mode = await fetch('/dashboard/auth-mode').then(r => r.json()).then(j => j.mode).catch(() => 'trust');

    if (user && (mode === 'trust' || tok)) {
      // 이미 인증 정보 있음
      showApp(user);
      return;
    }
    showModal(mode);
  }

  function showModal(mode) {
    const modal = document.getElementById('login-modal');
    const tokLabel = document.getElementById('login-token-label');
    if (mode === 'token') tokLabel.classList.remove('hidden'); else tokLabel.classList.add('hidden');
    modal.classList.remove('hidden');

    document.getElementById('login-submit').onclick = () => submit(mode);
    document.getElementById('login-username').onkeydown = (e) => { if (e.key === 'Enter') submit(mode); };
    document.getElementById('login-token').onkeydown = (e) => { if (e.key === 'Enter') submit(mode); };
  }

  function submit(mode) {
    const user = document.getElementById('login-username').value.trim();
    const tok = document.getElementById('login-token').value.trim();
    if (!user) { alert('username 필수'); return; }
    if (mode === 'token' && !tok) { alert('token 필수'); return; }
    localStorage.setItem('operator_username', user);
    if (tok) localStorage.setItem('operator_token', tok);
    document.getElementById('login-modal').classList.add('hidden');
    showApp(user);
  }

  function showApp(user) {
    document.getElementById('header').classList.remove('hidden');
    document.getElementById('main').classList.remove('hidden');
    document.getElementById('who').textContent = 'operator:' + user;
    if (onAuthenticated) onAuthenticated(user);
  }

  function logout() {
    localStorage.removeItem('operator_username');
    localStorage.removeItem('operator_token');
    location.reload();
  }

  return {init, logout};
})();
```

- [ ] **Step 2: Create health.js**

Create `src/agent_agora/dashboard_static/js/health.js`:

```javascript
// 서버 헬스 카드 — 헤더 inline summary + left panel expand 카드.
window.agoraHealth = (function() {
  let lastSnap = null;
  let lastSyncMs = 0;

  function fmtDuration(secs) {
    if (secs == null) return '?';
    if (secs < 60) return secs + 's';
    if (secs < 3600) return Math.floor(secs/60) + 'm';
    if (secs < 86400) return Math.floor(secs/3600) + 'h' + Math.floor((secs%3600)/60) + 'm';
    return Math.floor(secs/86400) + 'd';
  }

  function fmtBytes(b) {
    if (b == null) return '?';
    if (b < 1024) return b + 'B';
    if (b < 1024*1024) return Math.round(b/1024) + 'KB';
    if (b < 1024*1024*1024) return Math.round(b/1024/1024) + 'MB';
    return Math.round(b/1024/1024/1024 * 10)/10 + 'GB';
  }

  function update(serverSnap) {
    lastSnap = serverSnap;
    lastSyncMs = Date.now();
    render();
  }

  function render() {
    if (!lastSnap) return;
    const drift = Math.floor((Date.now() - lastSyncMs) / 1000);
    const uptime = (lastSnap.uptime_seconds || 0) + drift;
    document.getElementById('health-summary').textContent =
      `uptime ${fmtDuration(uptime)} | db ${fmtBytes(lastSnap.db_size_bytes)}`;

    const detail = document.getElementById('health-detail');
    if (detail) {
      detail.innerHTML = `
        <h3>서버 헬스</h3>
        <div>uptime: ${fmtDuration(uptime)}</div>
        <div>db: ${fmtBytes(lastSnap.db_size_bytes)}</div>
        <div>write queue: ${lastSnap.write_queue_depth ?? '?'}</div>
        <div>sweeper: ${lastSnap.sweeper_runs_total ?? '?'}회</div>`;
    }
  }

  // 1초마다 client-side 보간(uptime drift)
  setInterval(render, 1000);

  return {update};
})();
```

- [ ] **Step 3: Create dashboard.js (main bootstrap)**

Create `src/agent_agora/dashboard_static/js/dashboard.js`:

```javascript
// 메인 hydration + 레이아웃 조립.
(async function() {
  document.getElementById('logout').onclick = () => window.agoraLogin.logout();

  await window.agoraLogin.init(async (user) => {
    // 인증 완료 → 초기 hydration + SSE 연결
    try {
      const snap = await window.agoraApi.get('/dashboard/data');
      renderSnapshot(snap);
    } catch (e) {
      console.error('초기 hydration 실패', e);
    }

    window.agoraStream.on('data_snapshot', (evt) => renderSnapshot(evt.payload));
    window.agoraStream.on('instance_registered', () => refresh());
    window.agoraStream.on('instance_unregistered', () => refresh());
    window.agoraStream.on('message_dispatched', () => refresh());
    window.agoraStream.on('operator_inbox_message', (evt) => window.agoraInbox.push(evt));
    window.agoraStream.connect();
  });

  function renderSnapshot(d) {
    renderSummary(d.summary);
    renderInstances(d.instances);
    renderConversations(d.conversations);
    renderBots(d.bots);
    renderCommMatrix(d.comm_matrix);
    if (d.server) window.agoraHealth.update(d.server);
  }

  function renderSummary(s) {
    document.getElementById('summary-cards').innerHTML =
      `<div class="card"><b>${s.instances}</b>인스턴스</div>` +
      `<div class="card"><b>${s.bots}</b>봇</div>` +
      `<div class="card"><b>${s.open_conversations}</b>열린 대화</div>` +
      `<div class="card"><b>${s.total_inbox_depth}</b>총 인박스</div>`;
  }

  function renderInstances(rows) {
    // Tabulator 인스턴스 (재사용 패턴 — 이미 만들어졌으면 setData)
    if (!window._instTab) {
      window._instTab = new Tabulator('#instances-table', {
        layout: 'fitColumns', height: 250,
        columns: [
          {title: 'ID', field: 'instance_id', headerFilter: true},
          {title: 'role', field: 'role', headerFilter: true},
          {title: '인박스', field: 'inbox_depth', formatter: hotIfPos},
          {title: 'in-flight', field: 'in_flight'},
          {title: 'last seen', field: 'last_seen_at'},
          {title: 'accepting', field: 'accepting',
           formatter: c => c.getValue() ? '예' : '아니오'},
        ],
        rowClick: (e, row) => window.agoraDrilldown.openInstanceInbox(row.getData().instance_id),
      });
    }
    window._instTab.replaceData(rows);
  }

  function hotIfPos(cell) {
    const v = cell.getValue();
    if (v > 0) cell.getElement().classList.add('hot');
    return v;
  }

  function renderConversations(rows) {
    if (!window._convTab) {
      window._convTab = new Tabulator('#conversations-table', {
        layout: 'fitColumns', height: 250,
        columns: [
          {title: 'conversation', field: 'conversation_id', headerFilter: true},
          {title: 'kind', field: 'kind'},
          {title: 'status', field: 'status', headerFilter: true},
          {title: '메시지', field: 'message_count'},
          {title: 'last message', field: 'last_message_at'},
        ],
        rowClick: (e, row) => window.agoraDrilldown.openConversation(row.getData().conversation_id),
      });
    }
    window._convTab.replaceData(rows);
  }

  function renderBots(rows) {
    if (!window._botTab) {
      window._botTab = new Tabulator('#bots-table', {
        layout: 'fitColumns', height: 150,
        columns: [
          {title: 'ID', field: 'instance_id'},
          {title: 'mode', field: 'bot_mode'},
          {title: '구독 스키마', field: 'subscribe_schemas',
           formatter: c => (c.getValue() || []).join(', ')},
        ],
      });
    }
    window._botTab.replaceData(rows);
  }

  function renderCommMatrix(cm) {
    // 기존 dashboard.html(prev) 의 renderGraph 함수 — 원형 layout SVG.
    const wrap = document.getElementById('comm-matrix');
    if (!cm.active) { wrap.innerHTML = '<p>비활성 — all-allow (모든 워커가 서로 dispatch 가능)</p>'; return; }
    const nodes = Object.keys(cm.matrix);
    if (nodes.length === 0) { wrap.innerHTML = '<p>(빈 매트릭스)</p>'; return; }
    const W = 520, H = 420, cx = W/2, cy = H/2, R = Math.min(cx, cy) - 60;
    const pos = {};
    nodes.forEach((n, i) => {
      const a = 2 * Math.PI * i / nodes.length - Math.PI / 2;
      pos[n] = {x: cx + R * Math.cos(a), y: cy + R * Math.sin(a)};
    });
    let edges = '';
    // matrix[to][from] = weight; edge from->to when weight>0, from!=to
    for (const to of nodes) {
      for (const from of Object.keys(cm.matrix[to] || {})) {
        const w = cm.matrix[to][from];
        if (w > 0 && from !== to && pos[from] && pos[to]) {
          const a = pos[from], b = pos[to];
          const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
          const ux = dx / len, uy = dy / len;
          const x1 = a.x + ux * 20, y1 = a.y + uy * 20;
          const x2 = b.x - ux * 22, y2 = b.y - uy * 22;
          const mx = (x1 + x2) / 2 - uy * 18, my = (y1 + y2) / 2 + ux * 18;
          edges += `<path class="edge" marker-end="url(#arr)" d="M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}"/>` +
                   `<text class="edgelabel" x="${mx}" y="${my}">${w}</text>`;
        }
      }
    }
    const circles = nodes.map(n =>
      `<circle class="node" cx="${pos[n].x}" cy="${pos[n].y}" r="18"/>` +
      `<text class="nodelabel" x="${pos[n].x}" y="${pos[n].y + 4}">${escape(n)}</text>`).join('');
    wrap.innerHTML =
      `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
      `<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
      `<path d="M0 0 L10 5 L0 10 z" fill="#7a7ad0"/></marker></defs>` +
      edges + circles + `</svg>`;
  }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  }

  async function refresh() {
    try {
      const snap = await window.agoraApi.get('/dashboard/data');
      renderSnapshot(snap);
    } catch (e) { /* indicator already shows fallback */ }
  }

  window._refresh = refresh;
})();
```

(comm-matrix SVG 코드는 기존 `dashboard.html`(과거 git 히스토리에서 가져옴)에 있던 `renderGraph` 함수 그대로 이식. Implementation 시 git show로 끌어와 인라인.)

- [ ] **Step 4: Verify file existence**

Run: `py -3.13 -m pytest tests/test_dashboard_static.py -v`
Expected: js/login·dashboard·health 추가됨, 나머지(dispatch/inbox/drilldown) 미생성.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dashboard_static/js/login.js src/agent_agora/dashboard_static/js/dashboard.js src/agent_agora/dashboard_static/js/health.js
git commit -m "feat: dashboard 로그인 모달 + 메인 hydration + 헬스 카드"
```

---

## Task 16: js/inbox.js (운영자 인박스 패널)

**Files:**
- Create: `src/agent_agora/dashboard_static/js/inbox.js`

- [ ] **Step 1: Create inbox.js**

```javascript
// 운영자 인박스 패널 — left panel.
window.agoraInbox = (function() {
  const el = () => document.getElementById('inbox-panel');
  let messages = [];

  async function refresh() {
    try {
      const d = await window.agoraApi.get('/dashboard/operator/inbox');
      messages = d.messages || [];
      render();
    } catch (e) { console.error('inbox refresh', e); }
  }

  function render() {
    const lis = messages.map(m => `
      <div class="message-card" data-id="${m.message_id}">
        <div><span class="sender">${escape(m.sender)}</span>
             <span class="timestamp">${escape(m.timestamp)}</span></div>
        <div class="schema">schema: ${escape(m.schema)}</div>
        <div class="payload">${escape(JSON.stringify(m.payload).slice(0,200))}</div>
        ${m.reply_only ? '<div class="reply-only">reply_only</div>' : ''}
        <button class="ack-btn" data-id="${m.message_id}">ack</button>
      </div>`).join('') || '<p>(메시지 없음)</p>';
    el().innerHTML = `<h3>운영자 인박스 (${messages.length})</h3>` + lis;
    el().querySelectorAll('.ack-btn').forEach(btn => {
      btn.onclick = (e) => ack([e.target.dataset.id]);
    });
    el().querySelectorAll('.message-card').forEach(card => {
      card.onclick = (e) => {
        if (e.target.classList.contains('ack-btn')) return;
        const id = card.dataset.id;
        const m = messages.find(x => x.message_id === id);
        if (m) window.agoraDrilldown.openMessage(m);
      };
    });
  }

  async function ack(ids) {
    try {
      await window.agoraApi.post('/dashboard/operator/inbox/ack', {message_ids: ids});
      refresh();
    } catch (e) { console.error('ack', e); }
  }

  // SSE에서 operator_inbox_message 이벤트 도착 시
  function push(evt) {
    refresh();  // 간단한 전체 refresh — 작은 패널이라 OK
  }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // 페이지 부팅 직후 1회 호출
  setTimeout(refresh, 200);

  return {refresh, push};
})();
```

- [ ] **Step 2: Commit**

```bash
git add src/agent_agora/dashboard_static/js/inbox.js
git commit -m "feat: dashboard 운영자 인박스 패널 (ack·SSE 푸시 반영)"
```

---

## Task 17: js/dispatch.js (dispatch 모달)

**Files:**
- Create: `src/agent_agora/dashboard_static/js/dispatch.js`

- [ ] **Step 1: Create dispatch.js**

```javascript
// dispatch 모달 — 단일 워커 / 브로드캐스트, schema 선택, payload (JSONEditor), reply_only.
window.agoraDispatch = (function() {
  const modal = () => document.getElementById('dispatch-modal');
  let editor = null;
  let schemas = [];
  let instances = [];

  async function open() {
    schemas = (await window.agoraApi.get('/dashboard/schemas').catch(() => ({schemas:[]}))).schemas || [];
    const snap = await window.agoraApi.get('/dashboard/data').catch(() => ({instances:[]}));
    instances = snap.instances || [];

    modal().innerHTML = `
      <div class="modal-card">
        <h2>메시지 보내기</h2>
        <div>
          <label><input type="radio" name="dmode" value="single" checked>단일 워커</label>
          <label><input type="radio" name="dmode" value="broadcast">브로드캐스트</label>
        </div>
        <div id="dispatch-target"></div>
        <div>
          <label>Schema
            <select id="dispatch-schema">${schemas.map(s => `<option value="${s.id}">${s.id}</option>`).join('')}</select>
          </label>
        </div>
        <div>
          <label>Payload</label>
          <div id="dispatch-payload"></div>
        </div>
        <div>
          <label><input type="checkbox" id="dispatch-reply-only">reply_only (다른 워커로 forward 금지)</label>
        </div>
        <div>
          <button id="dispatch-send">보내기</button>
          <button id="dispatch-cancel">취소</button>
        </div>
      </div>`;
    modal().classList.remove('hidden');

    setupTargetPicker();
    setupPayloadEditor();
    document.getElementsByName('dmode').forEach(r => r.onchange = setupTargetPicker);
    document.getElementById('dispatch-schema').onchange = setupPayloadEditor;
    document.getElementById('dispatch-send').onclick = send;
    document.getElementById('dispatch-cancel').onclick = close;
  }

  function setupTargetPicker() {
    const mode = document.querySelector('input[name="dmode"]:checked').value;
    const wrap = document.getElementById('dispatch-target');
    if (mode === 'single') {
      wrap.innerHTML = `<label>To <select id="dispatch-to">${
        instances.map(i => `<option value="${i.instance_id}">${i.instance_id} (${i.role})</option>`).join('')
      }</select></label>`;
    } else {
      wrap.innerHTML = `<label>대상 워커</label>
        <div id="dispatch-targets-list">${
          instances.map(i => `<label><input type="checkbox" value="${i.instance_id}" checked> ${i.instance_id} (${i.role})</label>`).join('<br>')
        }</div>`;
    }
  }

  function setupPayloadEditor() {
    const sid = document.getElementById('dispatch-schema').value;
    const schema = (schemas.find(s => s.id === sid) || {}).schema;
    const wrap = document.getElementById('dispatch-payload');
    wrap.innerHTML = '<div id="payload-edit"></div>';
    if (editor) try { editor.destroy(); } catch(e) {}
    if (schema && window.JSONEditor) {
      editor = new JSONEditor(document.getElementById('payload-edit'), {
        schema: schema, theme: 'html', disable_collapse: true, disable_edit_json: false,
      });
    } else {
      wrap.innerHTML = '<textarea id="payload-raw" rows="6" style="width:100%">{}</textarea>';
      editor = null;
    }
  }

  function getPayload() {
    if (editor) return editor.getValue();
    try { return JSON.parse(document.getElementById('payload-raw').value); }
    catch (e) { throw new Error('Payload JSON 파싱 실패'); }
  }

  async function send() {
    try {
      const mode = document.querySelector('input[name="dmode"]:checked').value;
      const schema = document.getElementById('dispatch-schema').value;
      const reply_only = document.getElementById('dispatch-reply-only').checked;
      const payload = getPayload();
      if (mode === 'single') {
        const to = document.getElementById('dispatch-to').value;
        await window.agoraApi.post('/dashboard/dispatch', {to, schema, payload, reply_only});
      } else {
        const targets = Array.from(document.querySelectorAll('#dispatch-targets-list input:checked')).map(c => c.value);
        if (!targets.length) { alert('최소 1개 대상 선택'); return; }
        await window.agoraApi.post('/dashboard/broadcast', {targets, schema, payload, reply_only});
      }
      close();
    } catch (e) { alert('전송 실패: ' + e.message); }
  }

  function close() {
    modal().classList.add('hidden');
    if (editor) try { editor.destroy(); } catch(e) {}
    editor = null;
  }

  document.getElementById('open-dispatch').onclick = open;
  return {open, close};
})();
```

- [ ] **Step 2: Commit**

```bash
git add src/agent_agora/dashboard_static/js/dispatch.js
git commit -m "feat: dashboard dispatch 모달 (단일/브로드캐스트·JSONEditor 페이로드·reply_only)"
```

---

## Task 18: js/drilldown.js (대화·인박스 드릴다운 모달)

**Files:**
- Create: `src/agent_agora/dashboard_static/js/drilldown.js`

- [ ] **Step 1: Create drilldown.js**

```javascript
// 드릴다운 모달 — 대화 thread / 인스턴스 인박스 / 개별 메시지.
window.agoraDrilldown = (function() {
  const modal = () => document.getElementById('drilldown-modal');

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function msgCard(m) {
    return `<div class="message-card">
      <div><span class="sender">${escape(m.sender)}</span>
           → <span>${escape(m.recipient)}</span>
           <span class="timestamp">${escape(m.timestamp)}</span></div>
      <div>schema: ${escape(m.schema)}</div>
      <pre class="payload">${escape(JSON.stringify(m.payload, null, 2))}</pre>
      ${m.reply_only ? '<div class="reply-only">reply_only</div>' : ''}
    </div>`;
  }

  async function openConversation(convId) {
    show('대화 ' + convId, '<p>불러오는 중…</p>');
    try {
      const d = await window.agoraApi.get('/dashboard/conversation/' + encodeURIComponent(convId));
      const html = (d.messages || []).map(msgCard).join('') || '<p>(빈 thread)</p>';
      show('대화 ' + convId, html);
    } catch (e) { show('대화 ' + convId, '<p>로드 실패: ' + escape(e.message) + '</p>'); }
  }

  async function openInstanceInbox(instId) {
    show(instId + ' 인박스', '<p>불러오는 중…</p>');
    try {
      const d = await window.agoraApi.get('/dashboard/instance/' + encodeURIComponent(instId) + '/inbox');
      const html = (d.messages || []).map(msgCard).join('') || '<p>(빈 인박스)</p>';
      show(instId + ' 인박스', html);
    } catch (e) { show(instId + ' 인박스', '<p>로드 실패: ' + escape(e.message) + '</p>'); }
  }

  function openMessage(m) { show('메시지', msgCard(m)); }

  function show(title, html) {
    modal().innerHTML = `<div class="modal-card">
      <h2>${escape(title)}</h2>
      <div>${html}</div>
      <button onclick="window.agoraDrilldown.close()">닫기</button>
    </div>`;
    modal().classList.remove('hidden');
  }

  function close() { modal().classList.add('hidden'); }

  return {openConversation, openInstanceInbox, openMessage, close};
})();
```

- [ ] **Step 2: Verify all js files exist**

Run: `py -3.13 -m pytest tests/test_dashboard_static.py -v`
Expected: 모든 PASS.

- [ ] **Step 3: Run full suite (regression)**

Run: `py -3.13 -m pytest tests/ -q`
Expected: 신규 테스트 다 통과, 기존 회귀 0.

- [ ] **Step 4: Commit**

```bash
git add src/agent_agora/dashboard_static/js/drilldown.js
git commit -m "feat: dashboard 드릴다운 모달 (대화 thread·인스턴스 인박스·개별 메시지)"
```

---

## Task 19: agora-protocol skill — reply_only 존중 규칙

**Files:**
- Modify: `plugin/cc-agora/skills/agora-protocol/SKILL.md`

- [ ] **Step 1: Read current skill**

Read `plugin/cc-agora/skills/agora-protocol/SKILL.md` to find the appropriate insertion point (likely in the "메시지 처리" 또는 "답신" 섹션).

- [ ] **Step 2: Add reply_only rule**

Append a clear paragraph (Korean) near the response section:

```markdown
## reply_only 규칙

받은 메시지의 `envelope.reply_only`가 `true`이면 — 운영자(`operator:<username>`) 또는 다른 워커가 "답변만 받고 forward는 하지 말라"고 명시한 것이다. 이 경우:

- 받은 메시지를 다른 워커에 forward 금지.
- 답신은 sender(`operator:<username>` 등)에게만 직접 dispatch.
- 작업이 다른 워커의 협력이 필요해 보여도, 운영자에게 "이 작업은 다른 워커 도움이 필요합니다 — 어떻게 진행할까요?" 같은 답신으로 결정을 위임한다.

`reply_only`가 `false`(기본)이면 평소대로 자유롭게 dispatch.
```

- [ ] **Step 3: Commit**

```bash
git add plugin/cc-agora/skills/agora-protocol/SKILL.md
git commit -m "docs: agora-protocol에 envelope.reply_only 존중 규칙 추가"
```

---

## Task 20: docs/dashboard.md 갱신

**Files:**
- Modify: `docs/dashboard.md`

- [ ] **Step 1: Update dashboard.md**

Update `docs/dashboard.md` to reflect:
- 새 엔드포인트(/dispatch·/broadcast·/operator/inbox·/conversation·/instance/inbox·/schemas·/stream·/auth-mode) 문서화.
- 인증 모드 설명 (`AGORA_DASHBOARD_AUTH_MODE` 환경변수, trust·token).
- 원격 설정 가이드: `--host 0.0.0.0` + `AGORA_DASHBOARD_AUTH_MODE=token` + `AGORA_DASHBOARD_TOKENS` + TLS.
- SSE 동작 설명, 폴링 fallback.
- 헬스 메트릭 필드.
- 다중 운영자(`operator:<username>`) 모델.
- 운영자별 inbox 가시성 정책 (read-all).

(전체 문서는 본 plan 텍스트에 옮기지 않음 — Task 실행 시 spec과 plan 내용을 참조해 작성. 기존 dashboard.md 구조를 유지하며 섹션 추가.)

- [ ] **Step 2: Commit**

```bash
git add docs/dashboard.md
git commit -m "docs: dashboard.md — 운영자 dispatch·드릴다운·SSE·인증·원격 설정 갱신"
```

---

## Task 21: 통합 스모크 (manual smoke + 전체 회귀)

**Files:**
- (이 task는 코드 변경 없음. 검증 전용.)

- [ ] **Step 1: 전체 자동 테스트**

Run: `py -3.13 -m pytest tests/ -q`
Expected: 모든 테스트 통과.

- [ ] **Step 2: 서버 기동 + manual smoke**

Run:
```bash
py -3.13 -m agent_agora --port 8420 --no-tls --no-timeout
```

브라우저로 `http://127.0.0.1:8420/dashboard` 접속. 다음을 확인:

1. 로그인 모달 표시 → username 입력 → 메인 대시보드 진입.
2. 헤더에 `operator:<username>` + `● SSE` indicator + uptime/db 헬스 inline.
3. 워커 1개 spawn(`cc-agora-ops:agora-spawn`)해 인스턴스 목록에 나타나는지 확인.
4. "+ 보내기" 버튼 → dispatch 모달 → 워커에 메시지 전송 → 토스트.
5. 인스턴스 행 클릭 → 인박스 드릴다운 모달에 방금 보낸 메시지 표시.
6. 워커가 답신 → 운영자 인박스 패널에 즉시(또는 1초 내) 나타나는지.
7. 대화 행 클릭 → thread 모달.
8. 다른 브라우저(또는 시크릿) → 다른 username으로 로그인 → 동일 워커에 dispatch → 두 운영자 모두 dashboard에서 가시.
9. 서버 종료 → indicator가 `○ poll`로 전환 후, 재기동 시 `● SSE` 복귀.

각 항목 PASS/FAIL 기록.

- [ ] **Step 3: token 모드 smoke**

```bash
AGORA_DASHBOARD_AUTH_MODE=token \
AGORA_DASHBOARD_TOKENS="alice:tok-A,bob:tok-B" \
py -3.13 -m agent_agora --port 8420 --no-tls --no-timeout
```

- 로그인 모달에 token 필드 노출 확인.
- 잘못된 token → 401 + 모달 재표시.
- 올바른 token + 다른 username(impersonation 시도) → token이 매핑하는 username으로 인증됨.

- [ ] **Step 4: 회귀 + 보고 + (선택) merge 준비**

Step 1·2·3의 결과를 task 리포트로 정리. fail 항목이 있으면 해당 task로 돌아가 수정. 모두 pass면 finishing-a-development-branch 스킬로 진행 (operator 결정).

---
