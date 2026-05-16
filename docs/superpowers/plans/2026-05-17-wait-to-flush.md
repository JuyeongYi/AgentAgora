# `agora.wait` → `agora.flush` 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 블로킹 destructive drain `agora.wait`를 제거하고 논블로킹 `agora.flush`로 대체한다. 워커는 채널 wake 후 `flush`로 1회 드레인하고, 봇은 `wait_notify`+`flush`로 수신한다. `agora.wait_notify`는 유지.

**Architecture:** `Dispatcher.wait()`(블로킹)를 논블로킹 `flush()`로 대체 — 호출 시점 큐를 즉시 드레인. `server.py`의 `agora.wait` 도구 → `agora.flush`(`timeout_ms` 없음), `taskSupport` 힌트 블록 제거. `AgoraBot.run()` 루프를 `wait_notify`+`flush`로. 채널 메시지·프리셋·문서의 `agora.wait` 언급을 `agora.flush`로.

**Tech Stack:** Python 3.13, pytest. spec: `docs/superpowers/specs/2026-05-17-channel-receive-finalize-design.md` §3.2–3.4.

**전제:**
- 이 plan은 `2026-05-17-restart-clean-start.md`와 독립.
- 별도 브랜치/worktree에서 실행. 테스트 인터프리터는 저장소 `.venv`(Python 3.13).
- **주의 — `agora.wait_notify`와 `dispatcher.wait_notify`는 건드리지 않는다.** 이름에 `wait`이 들어가지만 비파괴 long-poll이고 채널 인프라다. 본 plan은 destructive 블로킹 `agora.wait`/`dispatcher.wait`만 대상으로 한다.
- Task 1이 핵심이며 테스트 영향 범위가 넓다 — `agora.wait`/`dispatcher.wait`를 쓰는 모든 테스트가 대상이다.

---

### Task 1: `agora.wait` → `agora.flush` (서버 도구 + Dispatcher)

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Modify: `src/agent_agora/server.py`
- Modify: `tests/*` (`agora.wait` / `dispatcher.wait`를 쓰는 모든 테스트)

- [ ] **Step 1: 현황 파악**

Run (bash): `grep -rn "agora\.wait\b\|\.wait(" src/ tests/ | grep -v wait_notify`
`agora.wait` 도구 호출, `dispatcher.wait(...)` 호출 지점을 모두 파악한다. `wait_notify`는 제외.

- [ ] **Step 2: `Dispatcher.wait()` → 논블로킹 `flush()`**

`src/agent_agora/dispatcher.py`의 `async def wait(self, instance_id, timeout_ms=None, from_sources=..., sort=..., by_conversation=...)`(현 `dispatcher.py:704`)를 읽는다. 이를 `async def flush(...)`로 바꾼다:
- 메서드명 `wait` → `flush`.
- `timeout_ms` 매개변수와 **모든 블로킹/대기 로직 제거** — 호출 시점에 큐에 있는 것만 즉시 드레인해 반환한다(기존 메서드의 "큐가 비어있지 않을 때 즉시 드레인"하는 fast-path만 남기는 것과 같다).
- `from_sources`·`sort`·`by_conversation` 필터, 등록 확인, `last_seen`/heartbeat 갱신은 **유지**한다.
- 반환 형태(드레인된 commands 리스트)는 유지.

- [ ] **Step 3: `agora.wait` 도구 → `agora.flush`**

`src/agent_agora/server.py`:
- `@mcp.tool(name="agora.wait")` 도구(현 `server.py` ~432–484)를 `name="agora.flush"`로, 함수명도 `agora_flush`로 바꾼다.
- `timeout_ms` 매개변수와 `_header_int(ctx, "x-agora-wait-timeout-ms")` 해석 로직을 제거한다.
- `from_sources`·`sort`·`by_conversation` 매개변수는 유지. 본문에서 `dispatcher.wait(...)` → `dispatcher.flush(...)` (`timeout_ms` 인자 빼고).
- docstring을 논블로킹 드레인에 맞게 갱신("Wait for commands" → 즉시 드레인 설명).
- **`taskSupport` 힌트 제거** — `_WAIT_TOOL_NAME` 상수(현 `server.py:23`)와 `_list_tools_with_wait_execution` 블록(현 `server.py` ~498–511, `mcp.list_tools` 재정의 포함)을 통째로 삭제한다. 그로 인해 `ToolExecution` import가 미사용이 되면 그 import도 제거한다.

- [ ] **Step 4: 테스트 전환**

Step 1에서 찾은 테스트들을 고친다:
- `agora.wait` 도구 호출 → `agora.flush` (인자에서 `timeout_ms` 제거).
- `dispatcher.wait(...)` 호출 → `dispatcher.flush(...)` (`timeout_ms` 제거).
- **블로킹 의미에 의존하던 테스트** — `agora.wait`가 N ms 블로킹 후 빈 결과를 리턴하는 것을 검증하던 테스트는 논블로킹 `flush`엔 해당이 없다. 그런 테스트는 삭제하거나, "dispatch 후 flush가 즉시 그 메시지를 반환한다"는 논블로킹 단언으로 다시 쓴다. (대부분의 "dispatch 후 wait" 테스트는 dispatch가 큐에 동기적으로 넣으므로 `flush`로 그대로 통과한다.)
- `wait_notify` 테스트는 건드리지 않는다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS.

Run (bash): `grep -rn "agora\.wait\b\|dispatcher\.wait(\|\.wait(" src/ tests/ | grep -v wait_notify || echo "(clean)"`
Expected: `(clean)` — destructive `wait` 잔존 없음(`wait_notify` 제외).

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/server.py tests/
git commit -m "feat: agora.wait → agora.flush — 블로킹 제거, 논블로킹 드레인"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 2: `AgoraBot` SDK — `wait_notify` + `flush` 루프

**Files:**
- Modify: `src/agent_agora/bot.py`
- Modify: `tests/*` (bot SDK 테스트)

- [ ] **Step 1: `run()` 루프 교체**

`src/agent_agora/bot.py`의 `run()` 메서드(현 `bot.py:134-145`)를 다음으로 교체한다:

```python
    async def run(self) -> None:
        """수신 루프. wait_notify로 도착을 기다리고(event-driven — 구독 스키마
        메시지가 라우팅되면 즉시 리턴), flush로 인박스를 드레인한다.
        메시지 없이 heartbeat 주기로 wait_notify가 리턴해도 이어지는 flush가
        last_seen을 갱신해 dead-bot sweep용 heartbeat를 유지한다."""
        print(f"[{self.INSTANCE_ID}] 수신 루프 시작 "
              f"(mode={self.BOT_MODE}, subscribe={self.SUBSCRIBE_SCHEMAS}, "
              f"heartbeat={self.WAIT_TIMEOUT_MS}ms).", flush=True)
        while True:
            await self.session.call_tool(
                "agora.wait_notify",
                {"instance_id": self.INSTANCE_ID,
                 "timeout_ms": self.WAIT_TIMEOUT_MS})
            res = _result_json(await self.session.call_tool("agora.flush", {}))
            for cmd in res.get("commands", []):
                await self._dispatch(cmd)
```

`WAIT_TIMEOUT_MS` 클래스 속성은 그대로 둔다(이제 `wait_notify`의 heartbeat 주기로 쓰임 — docstring/주석이 "bounded wait 주기"라 하면 "wait_notify heartbeat 주기"로 갱신).

- [ ] **Step 2: bot SDK 테스트 갱신**

bot SDK 테스트(`tests/`에서 `AgoraBot`/`bot.py` 테스트 — 실행자가 grep으로 위치 확인)에서, `run()` 루프가 `agora.wait`를 부른다고 가정하던 부분을 `agora.wait_notify` + `agora.flush`로 갱신한다. 봇의 `handle()` 인터페이스·`_dispatch`·`emit`은 불변이므로 그쪽 테스트는 영향 없다.

- [ ] **Step 3: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS.

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/bot.py tests/
git commit -m "feat: AgoraBot — wait_notify + flush 수신 루프 (블로킹 wait 제거)"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 3: 채널 어댑터 메시지 갱신

**Files:**
- Modify: `src/agent_agora/channel_adapter.py`
- Modify: `tests/test_channel_adapter.py`

- [ ] **Step 1: 채널 메시지의 `agora.wait` → `agora.flush`**

`src/agent_agora/channel_adapter.py`에서 `CHANNEL_INSTRUCTIONS`와 `format_channel_notification`의 `content`에 있는 `agora.wait(timeout_ms=0)` 표현을 `agora.flush`로 바꾼다. 두 문자열 모두 "call agora.flush to drain ..." 식으로 — 논블로킹 드레인 의미는 그대로(이미 "drain everything currently queued / non-blocking" 문구가 있음), 도구명만 `agora.flush`로.

- [ ] **Step 2: 테스트 갱신**

`tests/test_channel_adapter.py`의 `test_format_channel_notification`에서 `assert "agora.wait(timeout_ms=0)" in content`를 `assert "agora.flush" in content`로 바꾼다.

- [ ] **Step 3: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_channel_adapter.py -v`
Expected: 전체 PASS.

- [ ] **Step 4: 커밋**

```bash
git add src/agent_agora/channel_adapter.py tests/test_channel_adapter.py
git commit -m "feat: 채널 알림 메시지 agora.wait → agora.flush"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 4: 프리셋·문서·예제 갱신

**Files:**
- Modify: `plugin/cc-agora/templates/presets/*.md`
- Modify: `docs/channel-mode.md`, `docs/usage-guide.md`, `README.md`
- Modify: `examples/` (해당 시)

- [ ] **Step 1: 잔존 `agora.wait` 파악**

Run (bash): `grep -rln "agora\.wait\b" plugin/ docs/ README.md examples/ | grep -v wait_notify`

- [ ] **Step 2: `agora.wait` → `agora.flush` 치환**

매칭된 파일들에서 destructive `agora.wait` 도구 언급을 `agora.flush`로 바꾼다:
- `plugin/cc-agora/templates/presets/*.md` — `## 메시지 수신` 절 등.
- `docs/channel-mode.md`·`docs/usage-guide.md`·`README.md` — 도구 레퍼런스·동작 설명. `agora.flush`는 논블로킹 드레인 도구임을 정확히 서술(긴 블로킹 wait는 없어졌다는 점).
- `examples/` — 예제 코드/문서에 `agora.wait` 호출이 있으면 `agora.flush`로(인자에서 `timeout_ms` 제거).
- **`agora.wait_notify` 언급은 그대로 둔다.**

- [ ] **Step 3: 확인**

Run (bash): `grep -rn "agora\.wait\b" plugin/ docs/ README.md examples/ | grep -v wait_notify || echo "(clean)"`
Expected: `(clean)` (단 `docs/superpowers/specs/`·`plans/`의 과거 문서는 결정 트레일이라 제외 — 위 grep 경로에 포함 안 됨).

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS (문서·프리셋 변경 — 회귀 없음).

- [ ] **Step 4: 커밋**

```bash
git add plugin/ docs/ README.md examples/
git commit -m "docs: 프리셋·문서·예제 agora.wait → agora.flush"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.2(`agora.wait` 제거·`agora.flush` 신설·`taskSupport` 제거)는 Task 1, §3.3(`AgoraBot` `wait_notify`+`flush`·heartbeat 보존)은 Task 2, §3.4(채널 메시지)는 Task 3, (프리셋·문서·예제)는 Task 4.
- **Placeholder** — Task 2의 `run()` 교체 코드는 완전체. Task 1·4는 영향 범위가 grep 의존이라 변경 지점·방향을 구체적으로 지정하고 실행자가 grep 결과에 맞춰 적용한다(파일·테스트가 많아 plan에 전수 박으면 깨지기 쉬움).
- **타입 일관성** — `Dispatcher.flush`(Task 1)·`agora.flush` 도구(Task 1)·`AgoraBot.run`의 `agora.flush` 호출(Task 2)·채널 메시지의 `agora.flush` 문구(Task 3)·문서의 `agora.flush`(Task 4)가 모두 같은 도구명. `agora.wait_notify`/`dispatcher.wait_notify`는 전 Task에서 불변.
- **task 의존** — Task 1이 `agora.flush`를 만들고 나야 Task 2의 봇 루프가 그걸 호출할 수 있다. subagent-driven 실행 시 Task 1→2→3→4 순서.
