# dispatcher 리팩터링 Plan 2 — `ConversationStore` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** conversation 상태와 라이프사이클 로직을 `Dispatcher`에서 신규 `ConversationStore`로 분리한다.

**Architecture:** 순수 리팩터링. `Dispatcher`가 `ConversationStore` 인스턴스 하나(`self._conv`)를 보유한다. conversation dict 3종(`_conversations`·`_conversation_of`·`_message_source`)과 라이프사이클 헬퍼가 `ConversationStore`로 이동하고, `Dispatcher` 핫패스는 `self._conv.*`로 위임한다. `ConversationStore`는 자체 락이 없다 — `Dispatcher`가 `_lock`을 잡은 상태로 변형 메서드를 호출(현행 락 규율 보존). 성공 기준 = 기존 329 테스트 변경 없이 통과.

**Tech Stack:** Python 3.13, pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 무시(pytest 정답).

**선행 의존:** Plan 1 머지 후.

spec: `docs/superpowers/specs/2026-05-17-dispatcher-refactor-design.md` (§4).

---

### Task 1: `ConversationStore` 클래스 생성

**Files:**
- Create: `src/agent_agora/conversation_store.py`
- Modify: `src/agent_agora/dispatcher.py` (Task 2에서)

- [ ] **Step 1: 기준선 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed.

- [ ] **Step 2: `conversation_store.py` 생성**

`src/agent_agora/conversation_store.py`를 생성한다. `ConversationStore`는 conversation
상태 3 dict와 라이프사이클 로직을 담는다. `dispatcher.py`의 현 `Dispatcher`에서 다음
메서드 본문을 **그대로** 옮긴다(`self._conversations`/`_conversation_of` 참조는
`ConversationStore`의 동명 인스턴스 속성이 되므로 본문 변경 불필요; `self._persistence`는
`self._persistence`로 유지 — store가 persistence를 생성자 인자로 받음):

이동 대상 `Dispatcher` 메서드 → `ConversationStore` 메서드:
- `_new_conversation_state(kind)` → `new_state(kind)`
- `_add_participant(state, instance_id, role, delivered=True)` → `add_participant(...)` (동일 시그니처)
- `_maybe_close(conv_id, state)` → `maybe_close(conv_id, state)`
- `_resolve_conversation_id(conversation_id, in_reply_to)` → `resolve_conversation_id(...)`
- `conversation_status(conv_id)` → `status(conv_id)`
- `conversations_list(participant, status, limit)` → `list_conversations(participant, status, limit)`

클래스 골격:

```python
"""ConversationStore — conversation lifecycle state, extracted from Dispatcher.

자체 락 없음 — 변형 메서드는 호출자(Dispatcher)가 _lock을 잡은 상태에서 호출한다.
읽기 메서드(status·list_conversations·conv_id_of·source_of·get)는 락 없이 호출 가능
(기존 conversation_status/conversations_list 동작 보존)."""
from __future__ import annotations

import uuid
from typing import Any

from agent_agora.persistence import Persistence


class ConversationStore:
    def __init__(self, persistence: Persistence) -> None:
        self._persistence = persistence
        self._conversations: dict[str, dict[str, Any]] = {}
        self._conversation_of: dict[str, str] = {}   # cmd_id -> conv_id
        self._message_source: dict[str, str] = {}    # cmd_id -> source

    # --- 라이프사이클 (Dispatcher의 _new_conversation_state 등에서 본문 이동) ---
    def new_state(self, kind: str) -> dict[str, Any]: ...
    def add_participant(self, state: dict, instance_id: str, role: str,
                        delivered: bool = True) -> bool: ...
    def maybe_close(self, conv_id: str, state: dict) -> bool: ...
    def resolve_conversation_id(self, conversation_id: str | None,
                                in_reply_to: str | None) -> tuple[str, bool, bool]: ...

    # --- dict 접근자 ---
    def get(self, conv_id: str) -> dict[str, Any] | None:
        return self._conversations.get(conv_id)

    def put(self, conv_id: str, state: dict[str, Any]) -> None:
        self._conversations[conv_id] = state

    def has(self, conv_id: str) -> bool:
        return conv_id in self._conversations

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        """conversation (conv_id, state) 쌍 전체 — sweep 순회용 (읽기, 락 불필요)."""
        return list(self._conversations.items())

    def conv_id_of(self, cmd_id: str) -> str | None:
        return self._conversation_of.get(cmd_id)

    def source_of(self, cmd_id: str) -> str | None:
        return self._message_source.get(cmd_id)

    def record_command(self, cmd_id: str, conv_id: str, source: str) -> None:
        self._conversation_of[cmd_id] = conv_id
        self._message_source[cmd_id] = source

    def set_conv_of(self, cmd_id: str, conv_id: str) -> None:
        """복원 경로용 — conv_id만 기록(source 없이)."""
        self._conversation_of[cmd_id] = conv_id

    def evict(self, conv_ids: list[str]) -> None:
        """GC — 닫힌 conversation과 그에 매인 cmd 캐시를 비운다."""
        victim = set(conv_ids)
        for cid in conv_ids:
            self._conversations.pop(cid, None)
        stale = [c for c, v in self._conversation_of.items() if v in victim]
        for c in stale:
            self._conversation_of.pop(c, None)
            self._message_source.pop(c, None)

    # --- 읽기 (Dispatcher의 conversation_status / conversations_list 본문 이동) ---
    def status(self, conv_id: str) -> dict[str, Any]: ...
    def list_conversations(self, participant: str | None = None,
                           status: str | None = None, limit: int = 100) -> list[dict]: ...
```

`new_state`·`add_participant`·`maybe_close`·`resolve_conversation_id`·`status`·
`list_conversations`의 본문은 `dispatcher.py`의 현 `_new_conversation_state`·
`_add_participant`·`_maybe_close`·`_resolve_conversation_id`·`conversation_status`·
`conversations_list`에서 그대로 가져온다 — 알고리즘·문자열 한 글자도 바꾸지 않는다.
`resolve_conversation_id` 본문의 `self._persistence.lookup_conversation_for` 호출은
그대로 동작한다(store가 `_persistence`를 보유).

`message_gc_sweep`의 캐시 eviction 로직(현 `dispatcher.py`에서 `_conversations`·
`_conversation_of`·`_message_source`를 비우는 부분)은 `evict`로 들어갔다 — Plan 3의
`Sweeper`가 `evict`를 호출한다.

- [ ] **Step 3: import 정합성 확인**

Run: `.venv\Scripts\python.exe -c "import agent_agora.conversation_store; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/conversation_store.py
git commit -m "refactor: ConversationStore 클래스 신설 (conversation 상태·라이프사이클)"
```

---

### Task 2: `Dispatcher`가 `ConversationStore`에 위임

**Files:**
- Modify: `src/agent_agora/dispatcher.py`

- [ ] **Step 1: `Dispatcher.__init__`에 store 생성**

`Dispatcher.__init__`에서 `self._conversations = {}`·`self._conversation_of = {}`·
`self._message_source = {}` 세 줄을 삭제하고 대신:

```python
        from agent_agora.conversation_store import ConversationStore
        self._conv = ConversationStore(persistence)
```

(`persistence`는 `__init__`이 이미 받는 인자.)

- [ ] **Step 2: `Dispatcher`에서 이동한 6개 메서드 정의 삭제**

`dispatcher.py`에서 `_new_conversation_state`·`_add_participant`·`_maybe_close`·
`_resolve_conversation_id`·`conversation_status`·`conversations_list`의 **정의를
삭제**한다(본문이 Task 1에서 `ConversationStore`로 이동했다).

- [ ] **Step 3: 핫패스 호출부를 `self._conv.*`로 위임**

`dispatcher.py`에서 conversation 상태(`_conversations`·`_conversation_of`·
`_message_source`)에 접근하는 **모든** 메서드를 `self._conv`를 통하도록 바꾼다 —
`dispatch`·`broadcast`·`bot_emit`·`close_thread`·`restore_from_persistence`·
`drop_inflight_on_restart`·`message_gc_sweep`, 그리고 아직 `dispatcher.py`에 남아 있는
`close_ttl_sweep`(Plan 3에서 이동 예정 — 그 전까지 동작해야 함). `git grep -nE '_conversations|_conversation_of|_message_source' src/agent_agora/dispatcher.py`로 모든 잔존 참조를 찾아 0건이 될 때까지 치환한다. 기계적 치환:

| 현 코드 | 변경 후 |
|---|---|
| `self._new_conversation_state(kind)` | `self._conv.new_state(kind)` |
| `self._add_participant(state, ...)` | `self._conv.add_participant(state, ...)` |
| `self._maybe_close(conv_id, state)` | `self._conv.maybe_close(conv_id, state)` |
| `self._resolve_conversation_id(c, r)` | `self._conv.resolve_conversation_id(c, r)` |
| `self._conversations.get(conv_id)` / `self._conversations[conv_id]` (읽기) | `self._conv.get(conv_id)` |
| `self._conversations[conv_id] = state` | `self._conv.put(conv_id, state)` |
| `conv_id in self._conversations` / `conv_id not in self._conversations` | `self._conv.has(conv_id)` / `not self._conv.has(conv_id)` |
| `self._conversations.items()` (sweep 순회) | `self._conv.items()` |
| `self._conversation_of[cmd_id] = conv_id` + `self._message_source[cmd_id] = source` (함께 설정되는 곳) | `self._conv.record_command(cmd_id, conv_id, source)` |
| `self._conversation_of[cmd_id] = conv_id` (복원 경로, source 없이) | `self._conv.set_conv_of(cmd_id, conv_id)` |
| `self._conversation_of.get(x)` | `self._conv.conv_id_of(x)` |
| `self._message_source.get(x)` | `self._conv.source_of(x)` |

핵심: 이 치환은 `_lock`을 잡은 핫패스 블록 안에서 일어나며, `ConversationStore`는
자체 락이 없으므로 락 의미가 보존된다. `dispatch`의 `state` 지역변수는 여전히 가변
dict이고 직접 변형해도 된다(`self._conv.get`이 같은 dict를 돌려줌).

- [ ] **Step 4: `conversation_status`·`conversations_list` thin delegator 추가**

`server.py`가 `dispatcher.conversation_status(...)`·`dispatcher.conversations_list(...)`를
호출하므로(server.py:419·428), `Dispatcher`에 1줄 delegator를 남긴다:

```python
    def conversation_status(self, conv_id: str) -> dict:
        return self._conv.status(conv_id)

    def conversations_list(self, participant: str | None = None,
                           status: str | None = None, limit: int = 100) -> list[dict]:
        return self._conv.list_conversations(participant, status, limit)
```

- [ ] **Step 5: `message_gc_sweep`의 캐시 eviction을 `evict`로**

`dispatcher.py`의 `message_gc_sweep`에서 `_conversations`·`_conversation_of`·
`_message_source`를 직접 비우던 부분을 `self._conv.evict(victim_ids)` 호출로 바꾼다
(eviction 로직은 Task 1에서 `ConversationStore.evict`로 이미 이동).

- [ ] **Step 6: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed — 동작 불변.

만약 어떤 테스트가 `dispatcher._conversations`·`dispatcher._conversation_of` 내부
속성을 직접 들여다보면(화이트박스 테스트), 그 테스트를 `dispatcher._conv._conversations`
등으로 갱신한다 — 단언하는 *값*은 그대로.

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/dispatcher.py
git commit -m "refactor: Dispatcher가 ConversationStore에 conversation 상태 위임"
```

---

## 완료 기준

- `ConversationStore`가 conversation 3 dict와 라이프사이클·읽기 메서드를 보유한다.
- `Dispatcher`는 `self._conv`로 위임하고, conversation dict·헬퍼 정의가 더 이상 없다.
- `conversation_status`·`conversations_list`는 `Dispatcher`에 1줄 delegator로 남아 `server.py` 무변경.
- 락은 여전히 `Dispatcher._lock` 하나. 전체 329 테스트 통과.
