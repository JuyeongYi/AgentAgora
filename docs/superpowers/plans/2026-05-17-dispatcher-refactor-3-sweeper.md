# dispatcher 리팩터링 Plan 3 — `Sweeper` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4종 백그라운드 sweep을 `Dispatcher`에서 신규 `Sweeper`로 분리한다.

**Architecture:** 순수 리팩터링. `close_ttl_sweep`·`dead_session_sweep`·`dead_bot_sweep`·`message_gc_sweep`의 본문을 `Sweeper` 클래스로 옮긴다. `Dispatcher`가 `__init__`에서 `Sweeper`를 만들어 `self.sweeper`로 노출하고, `__main__.py`의 sweep 루프가 `dispatcher.sweeper.*`를 호출한다. 성공 기준 = 기존 329 테스트 통과.

**Tech Stack:** Python 3.13, pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 무시(pytest 정답).

**선행 의존:** Plan 1·Plan 2 머지 후 — sweep이 `ConversationStore`(`self._conv`)에 의존.

spec: `docs/superpowers/specs/2026-05-17-dispatcher-refactor-design.md` (§5).

---

### Task 1: `Sweeper` 클래스 생성

**Files:**
- Create: `src/agent_agora/sweeper.py`

- [ ] **Step 1: 기준선 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed.

- [ ] **Step 2: `sweeper.py` 생성**

`src/agent_agora/sweeper.py`를 생성한다. `dispatcher.py`의 현 `Dispatcher`에서 4개 sweep
메서드 본문을 **그대로** 옮긴다. 본문 내 참조를 다음과 같이 매핑한다(아래 생성자
속성명에 맞춰): `self._conv` → `self._conv`, `self._registry` → `self._instance_registry`,
`self._bot_registry`·`self._schema_registry`·`self._persistence` → 동명, `self._close_timeout_ms`·
`self._dead_session_timeout_ms`·`self._gc_retention_days` → 동명.

```python
"""Sweeper — periodic background sweeps, extracted from Dispatcher.

핫패스가 아니다 — __main__.py의 주기 루프가 호출한다. 알고리즘은 Dispatcher의
기존 sweep 본문 그대로다."""
from __future__ import annotations

import datetime

from agent_agora.bot_registry import BotRegistry
from agent_agora.conversation_store import ConversationStore
from agent_agora.persistence import Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.schemas import SchemaRegistry


class Sweeper:
    def __init__(
        self,
        conversation_store: ConversationStore,
        instance_registry: InstanceRegistry,
        bot_registry: BotRegistry,
        schema_registry: SchemaRegistry,
        persistence: Persistence,
        *,
        close_timeout_ms: int,
        dead_session_timeout_ms: int,
        gc_retention_days: int,
    ) -> None:
        self._conv = conversation_store
        self._instance_registry = instance_registry
        self._bot_registry = bot_registry
        self._schema_registry = schema_registry
        self._persistence = persistence
        self._close_timeout_ms = close_timeout_ms
        self._dead_session_timeout_ms = dead_session_timeout_ms
        self._gc_retention_days = gc_retention_days

    def close_ttl_sweep(self, now: datetime.datetime | None = None) -> list[str]: ...
    def dead_session_sweep(self, now: datetime.datetime | None = None) -> list[str]: ...
    def dead_bot_sweep(self, now: datetime.datetime | None = None) -> list[str]: ...
    def message_gc_sweep(self, now: datetime.datetime | None = None) -> int: ...
```

본문 이동 시 주의:
- `close_ttl_sweep` — Plan 2 적용 후 `dispatcher.py`의 `close_ttl_sweep`은 이미
  `self._conv.items()`로 conversation을 순회하고 `self._conv`를 통해 상태에 접근하는
  형태다(`ConversationStore.items()`는 Plan 2에서 이미 추가됨). 그 형태를 그대로 옮긴다.
- `message_gc_sweep` — 캐시 eviction은 Plan 2에서 `ConversationStore.evict`로 이동했다.
  이 sweep 본문은 `self._conv.evict(victim_ids)`를 호출하는 형태다.
- `dead_session_sweep`·`dead_bot_sweep` — `schema_registry.release_holder` 호출
  (schema-refcounting 기능에서 추가됨)을 그대로 보존한다.

- [ ] **Step 3: import 정합성 확인**

Run: `.venv\Scripts\python.exe -c "import agent_agora.sweeper; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/sweeper.py
git commit -m "refactor: Sweeper 클래스 신설 (4종 백그라운드 sweep)"
```

---

### Task 2: `Dispatcher`에서 sweep 제거 + `__main__.py` 재배선

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Modify: `src/agent_agora/__main__.py`
- Modify: `tests/test_v3_recovery.py` (및 sweep을 직접 호출하는 다른 테스트)

- [ ] **Step 1: `Dispatcher`가 `Sweeper`를 생성·노출**

`Dispatcher.__init__` 끝(모든 필드 설정 후)에 추가:

```python
        from agent_agora.sweeper import Sweeper
        self.sweeper = Sweeper(
            self._conv, registry, bot_registry, schema_registry, persistence,
            close_timeout_ms=close_timeout_ms,
            dead_session_timeout_ms=dead_session_timeout_ms,
            gc_retention_days=gc_retention_days,
        )
```

(`registry`·`bot_registry`·`schema_registry`·`persistence`·`close_timeout_ms`·
`dead_session_timeout_ms`·`gc_retention_days`는 `__init__`이 이미 받는 인자.)

- [ ] **Step 2: `Dispatcher`에서 4개 sweep 메서드 정의 삭제**

`dispatcher.py`에서 `close_ttl_sweep`·`dead_session_sweep`·`dead_bot_sweep`·
`message_gc_sweep` 메서드 정의를 삭제한다(본문이 Task 1에서 `Sweeper`로 이동).
delegator를 남기지 않는다 — 호출부를 직접 `dispatcher.sweeper.*`로 바꾼다.

- [ ] **Step 3: `__main__.py` sweep 루프 재배선**

`__main__.py`의 sweep 호출(현 229~231·246행)을 바꾼다:

```python
            dispatcher.sweeper.close_ttl_sweep()
            dispatcher.sweeper.dead_session_sweep()
            dispatcher.sweeper.dead_bot_sweep()
```

그리고 `message_gc_sweep` 호출:

```python
            dispatcher.sweeper.message_gc_sweep()
```

- [ ] **Step 4: sweep을 직접 호출하는 테스트 갱신**

`tests/`에서 `dispatcher.close_ttl_sweep()`·`.dead_session_sweep()`·`.dead_bot_sweep()`·
`.message_gc_sweep()`를 직접 호출하는 테스트(`test_v3_recovery.py` 등)를 찾아
`dispatcher.sweeper.<sweep>()`로 바꾼다. `git grep -nE '\.(close_ttl_sweep|dead_session_sweep|dead_bot_sweep|message_gc_sweep)\(' tests/`로 모든 호출처를 찾는다. 단언하는 *동작*은 그대로 — 호출 경로만 `.sweeper`를 거치게 한다.

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed — 동작 불변.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/__main__.py tests/
git commit -m "refactor: sweep을 Sweeper로 이관, __main__·테스트 재배선"
```

---

## 완료 기준

- `Sweeper`가 4종 sweep을 보유하고 `Dispatcher`는 `self.sweeper`로 노출한다.
- `Dispatcher`에 sweep 메서드 정의가 더 이상 없다.
- `__main__.py`·테스트의 sweep 호출이 `dispatcher.sweeper.*` 경로다.
- 전체 329 테스트 통과.
