# dispatcher 리팩터링 Plan 4 — `DispatchPersistence` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dispatch 영속 트랜잭션 빌드와 재시작 SQL을 `Dispatcher`에서 신규 `DispatchPersistence`로 분리한다.

**Architecture:** 순수 리팩터링. `_persist_dispatch_txn`의 SQL stmt 빌드·제출을 `DispatchPersistence`로 옮긴다. 재시작 경로(`restore_from_persistence`·`drop_inflight_on_restart`)의 inline SQL UPDATE도 `DispatchPersistence` 메서드로 옮기되, in-memory 상태 적재는 `Dispatcher`에 thin 메서드로 남는다. 성공 기준 = 기존 329 테스트 통과.

**Tech Stack:** Python 3.13, pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 무시(pytest 정답).

**선행 의존:** Plan 2 머지 후(`restore_from_persistence`가 `self._conv`를 씀). Plan 1·3과는 독립.

spec: `docs/superpowers/specs/2026-05-17-dispatcher-refactor-design.md` (§6).

---

### Task 1: `DispatchPersistence` 클래스 생성

**Files:**
- Create: `src/agent_agora/dispatch_persistence.py`

- [ ] **Step 1: 기준선 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed.

- [ ] **Step 2: `dispatch_persistence.py` 생성**

`src/agent_agora/dispatch_persistence.py`를 생성한다. `DispatchPersistence`는 `persistence`·
`write_queue`를 보유하고 dispatch 영속 트랜잭션과 재시작 SQL을 담당한다.

```python
"""DispatchPersistence — dispatch persistence transactions + restart SQL,
extracted from Dispatcher. SQL/영속 I/O만 담당하고 in-memory 상태는 만지지 않는다."""
from __future__ import annotations

from agent_agora.persistence import AsyncWriteQueue, Persistence


class DispatchPersistence:
    def __init__(self, persistence: Persistence, write_queue: AsyncWriteQueue) -> None:
        self._persistence = persistence
        self._write_queue = write_queue

    async def persist_dispatch_txn(self, ...) -> None: ...
    def mark_orphan_closed_inflight(self, now: str) -> None: ...
    def drop_inflight(self, now: str) -> None: ...
```

**`persist_dispatch_txn`** — `dispatcher.py`의 현 `_persist_dispatch_txn` 본문을 **그대로**
옮긴다. 시그니처도 그대로(`state`·`conv_id`·`is_new_conv`·`env`·`cc_envs`·`skipped_full`·
`payload_bytes`·`priority_rank`·`is_broadcast=False`). 본문의 `self._write_queue`는
`DispatchPersistence`의 동명 속성이라 변경 불필요. `json`을 쓰면 파일 상단에 `import json`.

**`mark_orphan_closed_inflight(now)`** — `dispatcher.py`의 현 `restore_from_persistence`
안에 있는, `messages` 테이블에서 닫힌 conversation의 undrained 메시지를
`drop_reason='server_restart'`로 마킹하는 `self._persistence.conn.execute(...)` UPDATE
블록을 그대로 옮긴다(`now` 인자를 받아 그 SQL을 실행).

**`drop_inflight(now)`** — `dispatcher.py`의 현 `drop_inflight_on_restart` 안의
`self._persistence.conn.execute(...)` UPDATE(모든 undrained 메시지를
`drop_reason='server_restart'`로 마킹)를 그대로 옮긴다.

- [ ] **Step 3: import 정합성 확인**

Run: `.venv\Scripts\python.exe -c "import agent_agora.dispatch_persistence; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/dispatch_persistence.py
git commit -m "refactor: DispatchPersistence 클래스 신설 (dispatch 영속·재시작 SQL)"
```

---

### Task 2: `Dispatcher`가 `DispatchPersistence`에 위임

**Files:**
- Modify: `src/agent_agora/dispatcher.py`

- [ ] **Step 1: `Dispatcher.__init__`에 `DispatchPersistence` 생성**

`Dispatcher.__init__`에 추가:

```python
        from agent_agora.dispatch_persistence import DispatchPersistence
        self._dispatch_persistence = DispatchPersistence(persistence, write_queue)
```

(`persistence`·`write_queue`는 `__init__`이 이미 받는 인자.)

- [ ] **Step 2: `Dispatcher._persist_dispatch_txn` 정의 삭제 + 호출부 위임**

`dispatcher.py`에서 `_persist_dispatch_txn` 메서드 정의를 삭제한다. `dispatch`·
`broadcast`·`bot_emit`에서 `await self._persist_dispatch_txn(...)`를 호출하던 곳을
`await self._dispatch_persistence.persist_dispatch_txn(...)`로 바꾼다 — 인자는 동일.

- [ ] **Step 3: `restore_from_persistence`·`drop_inflight_on_restart`의 SQL 위임**

`dispatcher.py`의 `restore_from_persistence`에서, 닫힌 conversation의 undrained 메시지를
마킹하던 inline `self._persistence.conn.execute(...)` UPDATE를
`self._dispatch_persistence.mark_orphan_closed_inflight(now)` 호출로 바꾼다. 나머지
(`restore_inflight()` 읽기, envelope를 `_queues`에 싣기, `self._conv.set_conv_of(...)`,
`_in_flight` 복원)는 `Dispatcher`에 그대로 남긴다 — in-memory 적재는 Dispatcher 책임.

`drop_inflight_on_restart`에서 inline UPDATE를 `self._dispatch_persistence.drop_inflight(now)`
호출로 바꾼다. 메서드 자체는 `Dispatcher`에 thin하게 남는다(`now` 계산 후 위임) —
`__main__.py` 호출부 무변경.

- [ ] **Step 4: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed — 동작 불변. 특히 재시작 복원/clean-start 테스트(`test_v3_recovery.py`·`test_main.py`)가 그대로 통과해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py
git commit -m "refactor: Dispatcher가 DispatchPersistence에 영속·재시작 SQL 위임"
```

---

## 완료 기준

- `DispatchPersistence`가 `persist_dispatch_txn`·`mark_orphan_closed_inflight`·`drop_inflight`를 보유한다.
- `Dispatcher`에 `_persist_dispatch_txn` 정의가 더 이상 없고, 핫패스가 위임한다.
- `restore_from_persistence`·`drop_inflight_on_restart`는 `Dispatcher`에 thin 메서드로 남아 `__main__.py` 무변경.
- 전체 329 테스트 통과.
