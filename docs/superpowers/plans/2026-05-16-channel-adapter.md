# agora-channel 어댑터 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** per-worker stdio MCP 서버 `agora-channel` 어댑터를 만든다 — 브로커의 `agora.wait_notify`로 워커 인박스 도착을 감지하고, `claude/channel` 알림으로 워커 Claude Code의 턴을 깨운다.

**Architecture:** 어댑터는 이중 역할이다 — Claude Code 쪽으로는 stdio MCP *서버*(`experimental['claude/channel']` capability 선언), 브로커 쪽으로는 HTTP MCP *클라이언트*. 백그라운드 감시 루프가 `wait_notify`를 돌며, 인박스가 0→N으로 전이하면 `notifications/claude/channel`을 emit한다(edge-triggered). 워커는 그 알림을 받고 깨어나 자기 HTTP `agora` 연결로 `agora.wait` 드레인한다.

**Tech Stack:** Python 3.13, `mcp` 라이브러리(서버·클라이언트 양쪽), asyncio, pytest. spec: `docs/superpowers/specs/2026-05-16-channel-adapter-design.md` §3.3·§3.4.

**전제:**
- 선행 plan `2026-05-16-wait-notify.md`가 먼저 머지돼야 한다 — 어댑터가 `agora.wait_notify`를 호출한다.
- 큰 변경이므로 master 직접 작업 금지 — 별도 브랜치/worktree에서 실행.
- 테스트 인터프리터는 저장소 `.venv`(Python 3.13). 기본 `python`은 3.12라 `agent_agora`가 없다.
- `claude/channel` 프로토콜 레퍼런스: https://code.claude.com/docs/en/channels-reference — capability 키 `experimental['claude/channel']`, 알림 메서드 `notifications/claude/channel`, params `{content: str, meta: dict[str,str]}`, stdio 전송 전용.

---

### Task 1: 스파이크 — Python `mcp` SDK 채널 서버 패턴 확인 (커밋 없음)

spec 리스크 #1. `claude/channel` 레퍼런스 예제는 전부 JS SDK다. Python `mcp` SDK로 (a) `experimental['claude/channel']` capability 선언, (b) `notifications/claude/channel` 임의 알림 emit이 가능한지 — 정확한 호출 경로를 확정한다. **이 task는 조사다 — 코드 커밋 없음. 산출물은 확인된 패턴을 보고에 기록하는 것.**

**Files:** 없음(스크래치 실험만). 실험 파일은 임시 위치(`%TEMP%` 등)에 두고 커밋하지 않는다.

- [ ] **Step 1: SDK 표면 조사**

다음을 `.venv` 인터프리터로 introspect한다:
- `mcp.server.lowlevel.Server` 생성자 인자 — `instructions` 인자가 있는지.
- `Server.create_initialization_options(notification_options=None, experimental_capabilities=...)` — `experimental_capabilities`에 `{"claude/channel": {}}`를 넘겼을 때 반환된 `InitializationOptions`의 `.capabilities.experimental`에 그대로 실리는지.
- `InitializationOptions` 필드에 `instructions`가 있는지(시스템 프롬프트용).
- `mcp.types`의 제네릭 `Notification` 모델과 `ServerSession.send_notification` 시그니처.

Run 예:
```
.venv\Scripts\python.exe -c "import inspect; from mcp.server.lowlevel import Server; print(inspect.signature(Server.__init__)); s=Server('x'); o=s.create_initialization_options(experimental_capabilities={'claude/channel':{}}); print(o.capabilities.experimental); print('instructions' in type(o).model_fields)"
```

- [ ] **Step 2: 최소 채널 서버 — capability 노출 확인**

임시 디렉터리에 최소 stdio MCP 서버 스크립트를 작성한다 — `experimental['claude/channel']` capability를 선언하고 stdio로 뜨는 서버. JSON-RPC `initialize` 요청을 stdin으로 흘려(혹은 `mcp` 클라이언트로 in-memory 연결) `initialize` 응답의 `capabilities.experimental`에 `claude/channel`이 실려 나오는지 확인한다.

- [ ] **Step 3: 임의 알림 emit 경로 확정**

`notifications/claude/channel` 알림을 emit하는 정확한 호출을 확정한다. 우선순위:
1. `ServerSession.send_notification`에 제네릭 `Notification`(method=`"notifications/claude/channel"`, params=`{content, meta}`)을 넘겨 동작하는지.
2. 안 되면 — write stream에 `JSONRPCNotification`을 직접 써서 emit(MCP는 결국 JSON-RPC라 raw notification 발화는 기계적으로 보장됨 — fallback).
서버 외부(요청 컨텍스트 밖)에서 알림을 보내려면 활성 `ServerSession` 핸들이 필요하다 — 그 핸들을 어떻게 잡는지도 확정한다(`Server.run`이 세션을 내부 관리하면, 어댑터는 `ServerSession`을 직접 생성해 핸들을 보유하는 저수준 경로를 쓴다).

- [ ] **Step 4: 확인된 패턴 보고**

다음을 보고에 명시한다 — Task 4가 이걸 그대로 쓴다:
- 서버 생성 + `claude/channel` capability + `instructions` 설정 코드.
- 활성 세션 핸들을 보유하는 방법.
- `notifications/claude/channel` 알림을 emit하는 정확한 호출(1번 경로 또는 2번 fallback 중 무엇인지).
- 막히면 status BLOCKED로 보고 — 컨트롤러가 판단(예: 어댑터를 Node로 전환).

---

### Task 2: 어댑터 — 인자 파싱 + 알림 포매팅

**Files:**
- Create: `src/agent_agora/channel_adapter.py`
- Create: `tests/test_channel_adapter.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_channel_adapter.py`:

```python
"""agora-channel 어댑터 단위 테스트."""
from __future__ import annotations

import pytest

from agent_agora.channel_adapter import parse_args, format_channel_notification


def test_parse_args_requires_instance_id():
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_defaults():
    ns = parse_args(["--instance-id", "InstA"])
    assert ns.instance_id == "InstA"
    assert ns.broker == "http://127.0.0.1:8420/mcp"
    assert ns.wait_timeout_ms == 30000


def test_parse_args_overrides():
    ns = parse_args(["--instance-id", "InstA",
                     "--broker", "http://h:9/mcp", "--wait-timeout-ms", "5000"])
    assert ns.broker == "http://h:9/mcp"
    assert ns.wait_timeout_ms == 5000


def test_format_channel_notification():
    content, meta = format_channel_notification("InstA", 3, ["PM", "Coder1"])
    assert "3건" in content
    assert "PM, Coder1" in content
    assert "agora.wait" in content
    assert meta == {"instance_id": "InstA", "pending": "3", "sources": "PM,Coder1"}


def test_format_channel_notification_no_sources():
    content, meta = format_channel_notification("InstA", 1, [])
    assert "(unknown)" in content
    assert meta["sources"] == ""
    assert meta["pending"] == "1"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.channel_adapter'`

- [ ] **Step 3: 모듈 + 두 함수 작성**

Create `src/agent_agora/channel_adapter.py`:

```python
"""agora-channel 어댑터 — per-worker stdio MCP 채널 서버.

워커 Claude Code가 자식으로 spawn하는 stdio MCP 서버. 브로커의
agora.wait_notify로 워커 인박스 도착을 감지하고, claude/channel 알림으로
워커 턴을 깨운다. 자세한 설계는
docs/superpowers/specs/2026-05-16-channel-adapter-design.md.

실행: python -m agent_agora.channel_adapter --instance-id <id> --broker <url>
"""
from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-agora-channel",
        description="AgentAgora claude/channel 어댑터 — 워커 인박스 도착을 push 알림으로 전환",
    )
    parser.add_argument("--instance-id", required=True,
                        help="감시할 워커 instance_id")
    parser.add_argument("--broker", default="http://127.0.0.1:8420/mcp",
                        help="AgentAgora 브로커 MCP URL")
    parser.add_argument("--wait-timeout-ms", type=int, default=30000,
                        help="wait_notify 주기(ms) — heartbeat 겸 timeout")
    return parser.parse_args(argv)


def format_channel_notification(
    instance_id: str, pending: int, sources: list[str],
) -> tuple[str, dict[str, str]]:
    """claude/channel 알림의 (content, meta)를 만든다.

    content는 <channel> 태그 본문, meta의 각 키는 태그 속성이 된다.
    meta 키는 식별자만(letters/digits/underscore), 값은 문자열이어야 한다."""
    src = ", ".join(sources) if sources else "(unknown)"
    content = (f"AgentAgora 인박스에 {pending}건 도착 (from: {src}). "
               f"agora.wait로 메시지를 수신해 처리하라.")
    meta = {
        "instance_id": instance_id,
        "pending": str(pending),
        "sources": ",".join(sources),
    }
    return content, meta
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py -v`
Expected: 5건 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/channel_adapter.py tests/test_channel_adapter.py
git commit -m "feat: channel_adapter — arg 파싱 + 알림 포매팅"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 3: 어댑터 — `watch_loop` edge-triggered 감시

**Files:**
- Modify: `src/agent_agora/channel_adapter.py` — `watch_loop` 추가
- Modify: `tests/test_channel_adapter.py` — `watch_loop` 테스트 추가

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_channel_adapter.py`의 import 줄을 교체:
```python
# 변경 전
from agent_agora.channel_adapter import parse_args, format_channel_notification
# 변경 후
from agent_agora.channel_adapter import (
    parse_args, format_channel_notification, watch_loop)
```
그리고 파일 끝에 추가:

```python
import asyncio


class _Stop(BaseException):
    """watch_loop 무한 루프를 테스트에서 탈출시키는 센티넬."""


@pytest.mark.asyncio
async def test_watch_loop_emits_once_per_rising_edge():
    """pending 0->N 전이에만 emit — N 유지 중에는 재발화하지 않는다."""
    emits: list = []
    wait_calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        wait_calls[0] += 1
        if wait_calls[0] == 1:
            return {"instance_id": iid, "pending": 2, "sources": ["PM"]}
        raise _Stop()                       # 2번째 wait_notify → 루프 종료

    peek_seq = [2, 2, 0]                     # 워커가 세 번째 peek에 드레인
    async def fake_peek(iid):
        return peek_seq.pop(0)

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0)
    assert len(emits) == 1                   # rising edge 1회만
    assert emits[0][1]["pending"] == "2"


@pytest.mark.asyncio
async def test_watch_loop_skips_emit_on_timeout():
    """pending 0(timeout heartbeat)이면 emit하지 않는다."""
    emits: list = []
    calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        calls[0] += 1
        if calls[0] == 1:
            return {"instance_id": iid, "pending": 0, "sources": []}
        raise _Stop()

    async def fake_peek(iid):
        return 0

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0)
    assert emits == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py -k watch_loop -v`
Expected: FAIL — `ImportError: cannot import name 'watch_loop'`

- [ ] **Step 3: `watch_loop` 구현**

In `src/agent_agora/channel_adapter.py`, `import argparse` 줄을 `import argparse`\n`import asyncio`로 바꾸고, `format_channel_notification` 함수 다음에 추가:

```python
async def watch_loop(
    instance_id: str,
    wait_notify,
    peek_pending,
    emit,
    *,
    wait_timeout_ms: int = 30000,
    drain_poll_s: float = 2.0,
) -> None:
    """edge-triggered 감시 루프.

    wait_notify(instance_id, timeout_ms) -> dict{pending, sources} 로 인박스
    도착을 블로킹 감지하고, pending이 0->N으로 올라설 때만 emit(content, meta)
    한다. emit 후에는 peek_pending(instance_id) -> int 가 0을 반환할 때까지
    폴링하다 wait_notify로 복귀한다 — 워커가 드레인하기 전 중복 알림 방지."""
    while True:
        signal = await wait_notify(instance_id, wait_timeout_ms)
        pending = signal.get("pending", 0)
        if pending <= 0:
            continue                          # timeout heartbeat — emit 안 함
        content, meta = format_channel_notification(
            instance_id, pending, signal.get("sources", []))
        await emit(content, meta)
        # 워커가 큐를 드레인할 때까지 재발화 보류 (edge-triggered)
        while await peek_pending(instance_id) > 0:
            await asyncio.sleep(drain_poll_s)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py -v`
Expected: 7건 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/channel_adapter.py tests/test_channel_adapter.py
git commit -m "feat: channel_adapter watch_loop — edge-triggered 감시"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 4: 어댑터 — `main()` 전송 통합 (stdio 채널 서버 + 브로커 클라이언트)

`watch_loop`를 실제 전송에 연결한다 — 브로커 HTTP 클라이언트(`wait_notify`/`peek` 호출)와 stdio 채널 서버(`claude/channel` capability + 알림 emit)를 동시에 띄운다.

**Task 1 스파이크 결과를 사용한다** — 채널 서버 생성·capability 선언·`instructions` 설정·알림 emit의 정확한 `mcp` SDK 호출은 Task 1에서 확정된 패턴을 그대로 쓴다.

**Files:**
- Modify: `src/agent_agora/channel_adapter.py` — `main()` + 브로커/채널 글루

- [ ] **Step 1: 브로커 클라이언트 글루 작성**

브로커에 HTTP MCP 클라이언트(`mcp` 라이브러리의 `streamable_http_client` + `ClientSession`)로 연결한다. 등록하지 않는다(`wait_notify`·`peek`는 등록 불요 — spec §3.3). 두 콜러블을 만든다:
- `wait_notify(instance_id, timeout_ms) -> dict` — 브로커 `agora.wait_notify` 도구를 호출, 응답 JSON을 dict로 파싱(`examples/echo_bot/echo_bot.py`의 `_result_json` 패턴 참고).
- `peek_pending(instance_id) -> int` — 브로커 `agora.peek` 도구를 `targets=[instance_id]` 로 호출, 응답에서 그 인스턴스의 `queue_depth`를 꺼낸다.
브로커 연결 실패 시 backoff 후 재연결(크래시 금지).

- [ ] **Step 2: stdio 채널 서버 + emit 글루 작성 (Task 1 패턴 사용)**

Task 1에서 확정한 패턴으로 stdio MCP 서버를 구성한다:
- `experimental['claude/channel']` capability 선언.
- `instructions` 설정 — 문자열: `"AgentAgora 인박스 알림이 <channel source=\"agora-channel\"> 태그로 도착하면, agora.wait 도구로 메시지를 수신해 처리하라. 답신은 agora.dispatch를 쓴다."`
- one-way — `tools` capability 없음.
- `emit(content, meta)` 콜러블 — 활성 세션 핸들로 `notifications/claude/channel`(params `{content, meta}`)을 보낸다(Task 1 확정 경로).

- [ ] **Step 3: `main()` — 동시 실행**

`main()`을 작성한다:
- `parse_args` → `instance_id`, `broker`, `wait_timeout_ms`.
- 브로커 클라이언트 연결 + stdio 채널 서버 기동을 asyncio로 동시에.
- `watch_loop(instance_id, wait_notify, peek_pending, emit, wait_timeout_ms=args.wait_timeout_ms)`를 백그라운드 태스크로.
- stdio 서버는 Claude Code의 JSON-RPC(`initialize` 등)를 처리하며 살아 있는다.
- 파일 끝에 `if __name__ == "__main__": asyncio.run(main())`.
- `KeyboardInterrupt`/stdin EOF(부모 Claude Code 종료) 시 깔끔히 종료.

- [ ] **Step 4: 라이브 검증 — 어댑터가 브로커에 붙어 감시 루프가 도는지**

별도 터미널에서 브로커를 띄운다:
```
.venv\Scripts\python.exe -m agent_agora --port 8420 --no-tls --no-timeout
```
어댑터를 직접 실행(Claude Code 없이, stdin은 빈 채로):
```
.venv\Scripts\python.exe -m agent_agora.channel_adapter --instance-id smoke --broker http://127.0.0.1:8420/mcp --wait-timeout-ms 3000
```
Expected: 어댑터가 브로커에 연결되고, `wait_notify` 루프가 3초 주기로 돌며 크래시하지 않는다(인박스가 비어 timeout heartbeat 반복). 에러·예외 트레이스가 없어야 한다. 확인 후 Ctrl+C로 종료.

(실제 Claude Code가 어댑터를 spawn하고 `claude/channel` push로 워커가 깨는 end-to-end는 Task 5의 수동 smoke test로 검증한다 — 자동 테스트 범위 밖.)

- [ ] **Step 5: 전체 테스트 회귀 확인 + 커밋**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS

```bash
git add src/agent_agora/channel_adapter.py
git commit -m "feat: channel_adapter main — stdio 채널 서버 + 브로커 감시 통합"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 5: 채널 모드 워커 배선 가이드

**Files:**
- Create: `docs/channel-mode.md`
- Modify: `README.md` — 문서 표 + 채널 모드 한 줄 언급

- [ ] **Step 1: `docs/channel-mode.md` 작성**

채널 모드 워커 구성 가이드. 다음을 포함한다:
- **개요** — 폴링 모드(Stop hook + `agora.wait`)와 채널 모드(어댑터 push)의 차이, 공존(워커는 둘 중 하나).
- **사전 조건** — `claude/channel`은 research preview. `channelsEnabled` 정책 true(개인 Pro/Max·Console API는 기본 true). Claude Code v2.1.80+.
- **`.mcp.json`** — MCP 서버 둘:
  - `agora` (HTTP, 기존) — `X-Agora-*` 헤더 자동 등록, 워커가 `agora.wait`/`agora.dispatch` 호출.
  - `agora-channel` (stdio) — `command`로 agent_agora가 설치된 python, `args`로 `["-m", "agent_agora.channel_adapter", "--instance-id", "<id>", "--broker", "http://127.0.0.1:8420/mcp"]`.
  - Windows JSON 경로는 forward slash (프로젝트 규약).
- **`settings.local.json`** — wait Stop hook **제거**(채널 push가 재무장 루프를 대체). 폴링 모드 템플릿(`plugin/cc-agora/templates/settings.local.json.template`)의 Stop hook을 넣지 않는다.
- **기동** — `claude --dangerously-load-development-channels server:agora-channel`. 자작 어댑터는 공식 allowlist에 없어 이 플래그가 필요(`--channels`는 allowlist 플러그인 전용). 로드 전 확인 프롬프트가 한 번 뜬다.
- **동작 흐름** — `<channel source="agora-channel">` 도착 → 워커 턴 깨어남 → `agora.wait` 드레인 → 처리 → `agora.dispatch` 답신 → idle.
- **수동 smoke test** — 서버 + 채널 모드 워커 1 + 송신 워커 1을 띄워, 송신 워커가 `agora.dispatch`로 메시지를 보내면 채널 모드 워커가 폴링 없이 깨어나 처리하는지 확인하는 절차.
- **한계** — research preview 게이팅, `claude/channel` 알림은 무확인(채널 미로드/정책 차단 시 조용히 드롭 → 폴링 모드로 fallback).

- [ ] **Step 2: `README.md` 갱신**

- "문서" 표에 행 추가: `| 채널 모드 | docs/channel-mode.md | claude/channel push로 워커를 깨우는 모드 (폴링 대안) |`
- 적절한 곳(운영 패턴 또는 디자인 개요)에 한 줄: 워커는 기본 `agora.wait` 폴링으로 메시지를 받지만, Claude Code `claude/channel`을 쓰는 채널 모드(`docs/channel-mode.md`)로 push 수신할 수도 있다.

- [ ] **Step 3: 링크 확인 + 커밋**

Run: `.venv\Scripts\python.exe -c "import pathlib; assert pathlib.Path('docs/channel-mode.md').exists(); print('docs OK')"`
Expected: `docs OK`

```bash
git add docs/channel-mode.md README.md
git commit -m "docs: 채널 모드 워커 배선 가이드"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.3(어댑터 — capability 선언·`instructions`·one-way·edge-triggered emit·복원력)은 Task 1(스파이크)·2(포매팅)·3(`watch_loop`)·4(전송 통합)가, §3.4(워커 배선)는 Task 5가 구현한다. §3.5 어댑터 테스트(edge-triggered 발화·드레인 감지·notification 조립)는 Task 2·3의 단위 테스트가, 실제 채널 push end-to-end는 Task 5의 수동 smoke test가 커버한다. spec §5 리스크 #1(Python SDK 커스텀 notification)은 Task 1 스파이크가 정면으로 다룬다.
- **Placeholder** — Task 2·3의 코드·테스트는 완전체. Task 1은 스파이크라 본질적으로 조사(코드 산출물 아님 — 확인된 패턴 보고). Task 4는 전송 통합 — Task 1 스파이크가 확정하는 SDK 호출에 의존하므로, 의도적으로 "Task 1 패턴 사용"으로 구조만 지정하고 정확한 호출은 스파이크 결과를 따른다. 이는 placeholder가 아니라 명시된 task 간 의존이다.
- **타입 일관성** — `parse_args(argv) -> Namespace`(`.instance_id`/`.broker`/`.wait_timeout_ms`), `format_channel_notification(instance_id, pending, sources) -> (content, meta)`, `watch_loop(instance_id, wait_notify, peek_pending, emit, *, wait_timeout_ms, drain_poll_s)`는 Task 2·3 정의와 테스트·Task 4 호출에서 일관. `wait_notify` 콜러블의 반환 dict 키(`pending`/`sources`)는 선행 plan `2026-05-16-wait-notify.md`의 `agora.wait_notify` 반환 형태와 일치.
- **task 간 의존** — Task 4는 Task 1(스파이크 패턴)·2·3에 의존. Task 1이 BLOCKED면(Python으로 채널 서버 불가) Task 4 이후가 막히므로, 컨트롤러는 Task 1 결과를 먼저 확인하고 진행한다.
