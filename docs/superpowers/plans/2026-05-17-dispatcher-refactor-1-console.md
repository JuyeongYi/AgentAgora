# dispatcher 리팩터링 Plan 1 — `dispatch_console.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `dispatcher.py`의 순수 콘솔 로그/색상 헬퍼를 신규 `dispatch_console.py`로 분리한다.

**Architecture:** 순수 리팩터링 — 공유 상태가 없는 모듈 레벨 함수·상수 5개(`_fmt_payload`·`_color_for`·`_colored`·`_COLOR_PALETTE`·`_RESET`)를 새 모듈로 옮기고 `dispatcher.py`가 import한다. 외부 동작·콘솔 출력 한 글자도 안 바뀐다. 성공 기준 = 기존 329 테스트 변경 없이 통과.

**Tech Stack:** Python 3.13, pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 진단은 무시(pytest 정답).

spec: `docs/superpowers/specs/2026-05-17-dispatcher-refactor-design.md` (§3).

---

### Task 1: `dispatch_console.py` 추출

**Files:**
- Create: `src/agent_agora/dispatch_console.py`
- Modify: `src/agent_agora/dispatcher.py`

- [ ] **Step 1: 기준선 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed. (리팩터링 전 기준선.)

- [ ] **Step 2: `dispatch_console.py` 생성**

`src/agent_agora/dispatcher.py`에서 다음 5개 심볼의 **현재 정의를 그대로** 옮긴다 — `_COLOR_PALETTE`, `_RESET`, `_fmt_payload`, `_color_for`, `_colored`. `src/agent_agora/dispatch_console.py`를 생성하고, dispatcher.py에 있는 그 정의들을 글자 그대로 복사한다. 파일 상단 import는 그 정의들이 쓰는 것만 — `_fmt_payload`는 `json`, `_color_for`는 `hashlib`, `_fmt_payload` 시그니처는 `Any`:

```python
"""Console log/color helpers for the dispatcher — pure, no shared state."""
from __future__ import annotations

import hashlib
import json
from typing import Any

# (아래 5개는 dispatcher.py의 현재 정의를 그대로 옮긴 것 — 본문 변경 금지)
# _COLOR_PALETTE = (...)
# _RESET = "..."
# def _fmt_payload(payload: Any) -> str: ...
# def _color_for(instance_id: str) -> str: ...
# def _colored(instance_id: str) -> str: ...
```

dispatcher.py의 실제 정의 본문을 그대로 붙여넣는다 — 색상 코드·`indent=2`·`md5` 로직 등 한 글자도 바꾸지 않는다.

- [ ] **Step 3: `dispatcher.py`에서 원본 제거 + import 추가**

`dispatcher.py`에서 옮긴 5개 심볼의 정의를 삭제하고, 대신 import한다:

```python
from agent_agora.dispatch_console import _colored, _fmt_payload
```

(`_color_for`·`_COLOR_PALETTE`·`_RESET`는 `dispatcher.py`에서 직접 참조되지 않고 `_colored` 내부에서만 쓰이면 import 불필요 — `dispatcher.py` 안의 사용처를 grep으로 확인해 실제로 참조되는 심볼만 import한다.)

`dispatcher.py`에 더 이상 쓰이지 않게 된 import(`hashlib`이 다른 곳에서 안 쓰이면)를 제거한다. `json`은 `_persist_dispatch_txn` 등에서 계속 쓰이므로 남긴다 — grep으로 확인.

- [ ] **Step 4: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 329 passed — 동작 불변.

- [ ] **Step 5: import 정합성 확인**

Run: `.venv\Scripts\python.exe -c "import agent_agora.dispatcher; import agent_agora.dispatch_console; print('import ok')"`
Expected: `import ok` — 순환 import·미해결 참조 없음.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/dispatch_console.py src/agent_agora/dispatcher.py
git commit -m "refactor: dispatcher 콘솔 로그 헬퍼를 dispatch_console.py로 분리"
```

---

## 완료 기준

- `dispatch_console.py`에 5개 로그/색상 심볼이 있고 `dispatcher.py`가 import한다.
- `dispatcher.py`에 그 정의가 더 이상 없다.
- 전체 329 테스트 통과, 콘솔 출력 불변.
