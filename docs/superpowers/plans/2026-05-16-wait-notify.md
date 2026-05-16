# agora.wait_notify 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora에 비파괴 long-poll 도구 `agora.wait_notify`를 추가한다 — 인스턴스 인박스가 비지 않을 때까지 블록했다 큐를 드레인하지 않고 신호만 반환한다.

**Architecture:** `Dispatcher`에 `wait_notify` 메서드를 추가한다 — 기존 `wait()`의 future 메커니즘(`_waiters`/`_wake`)을 재사용하되, 깨어난 뒤 큐를 드레인하는 대신 `{instance_id, pending, sources}` 스냅샷만 반환한다. 채널 어댑터(별도 plan)가 이 도구로 인박스 도착을 감지한다.

**Tech Stack:** Python 3.13, asyncio, pytest + pytest-asyncio. spec: `docs/superpowers/specs/2026-05-16-channel-adapter-design.md` §3.2.

**전제:**
- 이 plan은 채널 어댑터 plan(`2026-05-16-channel-adapter.md`)의 선행이다 — 어댑터가 `wait_notify`를 호출하므로 이 plan이 먼저 머지돼야 한다. 단독으로도 머지 가능(새 도구 추가일 뿐, 기존 동작 불변).
- 큰 변경이므로 master 직접 작업 금지 — 별도 브랜치/worktree에서 실행(실행 스킬이 처리).
- 테스트 인터프리터는 저장소 `.venv`(Python 3.13, `agent_agora` editable + pytest). 기본 `python`은 3.12라 `agent_agora`가 없다.

---

### Task 1: `Dispatcher.wait_notify()`

**Files:**
- Create: `tests/test_v4_wait_notify.py`
- Modify: `src/agent_agora/dispatcher.py` — `wait()` 메서드 바로 다음(`wait`는 `return results`로 끝남, `in_flight_count` 메서드 앞)에 `wait_notify` 추가

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_v4_wait_notify.py`:

```python
"""agora.wait_notify — 비파괴 long-poll 테스트."""
from __future__ import annotations

import asyncio

import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=500)
        yield registry, dispatcher


@pytest.mark.asyncio
async def test_returns_immediately_when_queue_nonempty(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=200)
    assert snap["instance_id"] == "Inst2"
    assert snap["pending"] == 1
    assert snap["sources"] == ["Inst1"]


@pytest.mark.asyncio
async def test_blocks_until_message_then_returns(setup):
    registry, dispatcher = setup
    task = asyncio.create_task(dispatcher.wait_notify("Inst2", timeout_ms=2000))
    await asyncio.sleep(0.05)            # let it block on the empty queue
    assert not task.done()
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await task
    assert snap["pending"] == 1
    assert snap["sources"] == ["Inst1"]


@pytest.mark.asyncio
async def test_timeout_returns_empty_snapshot(setup):
    registry, dispatcher = setup
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=50)
    assert snap == {"instance_id": "Inst2", "pending": 0, "sources": []}


@pytest.mark.asyncio
async def test_is_non_destructive(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=200)
    assert snap["pending"] == 1
    # 큐가 그대로 — 이어서 wait가 같은 메시지를 드레인한다
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    assert len(drained) == 1
    assert drained[0]["payload"]["x"] == 1


@pytest.mark.asyncio
async def test_touches_last_seen(setup):
    registry, dispatcher = setup
    assert registry.resolve_instance_id("Inst2").last_seen_at is None
    await dispatcher.wait_notify("Inst2", timeout_ms=50)
    assert registry.resolve_instance_id("Inst2").last_seen_at is not None


@pytest.mark.asyncio
async def test_distinct_sources_sorted(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst3", target="Inst2", payload=tany(x=1))
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=2))
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=3))
    snap = await dispatcher.wait_notify("Inst2", timeout_ms=200)
    assert snap["pending"] == 3
    assert snap["sources"] == ["Inst1", "Inst3"]   # distinct, sorted


@pytest.mark.asyncio
async def test_coexists_with_wait(setup):
    registry, dispatcher = setup
    wn = asyncio.create_task(dispatcher.wait_notify("Inst2", timeout_ms=2000))
    w = asyncio.create_task(dispatcher.wait("Inst2", timeout_ms=2000))
    await asyncio.sleep(0.05)
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    snap = await wn
    drained = await w
    # 둘 다 깨어났다(데드락 없음). wait가 메시지를 드레인한다.
    assert snap["instance_id"] == "Inst2"
    assert len(drained) == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_wait_notify.py -v`
Expected: 7건 모두 FAIL — `AttributeError: 'Dispatcher' object has no attribute 'wait_notify'`

- [ ] **Step 3: `wait_notify` 구현**

In `src/agent_agora/dispatcher.py`, `wait()` 메서드가 끝나는 줄(`return results`) 바로 다음에 추가:

```python
    async def wait_notify(
        self, instance_id: str, timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Non-destructive long-poll. Block until instance_id's queue is
        non-empty (or timeout), then return {instance_id, pending, sources}
        WITHOUT draining. Used by the channel adapter to detect inbound.
        Advisory like peek — instance_id need not be registered (an empty
        queue just blocks, absorbing the worker/adapter startup race)."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        effective = self._default_timeout_ms if timeout_ms is None else timeout_ms
        loop = asyncio.get_running_loop()

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            fut: asyncio.Future | None = None
            if not self._queues.get(instance_id):
                fut = loop.create_future()
                self._waiters[instance_id].append(fut)

        if fut is not None:
            try:
                if effective <= 0:
                    await fut
                else:
                    await asyncio.wait_for(fut, timeout=effective / 1000.0)
            except asyncio.TimeoutError:
                async with self._lock:
                    if fut in self._waiters.get(instance_id, []):
                        self._waiters[instance_id].remove(fut)

        self._touch_last_seen(instance_id)
        async with self._lock:
            queue = self._queues.get(instance_id, [])
            return {
                "instance_id": instance_id,
                "pending": len(queue),
                "sources": sorted({e.source for e in queue}),
            }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_wait_notify.py -v`
Expected: 7건 PASS

- [ ] **Step 5: 커밋**

```bash
git add tests/test_v4_wait_notify.py src/agent_agora/dispatcher.py
git commit -m "feat: Dispatcher.wait_notify — 비파괴 long-poll"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 2: `agora.wait_notify` 서버 도구

**Files:**
- Modify: `src/agent_agora/server.py` — `agora.wait` 도구(`agora_wait` 함수, `_WAIT_TOOL_NAME` 데코레이터) 정의 바로 다음에 `agora.wait_notify` 도구 추가
- Modify: `tests/test_v4_wait_notify.py` — 도구 등록 테스트 추가

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_v4_wait_notify.py` 끝에 추가:

```python
def test_wait_notify_tool_registered(agora_dir):
    """_build_app이 agora.wait_notify 도구를 등록한다."""
    from agent_agora.__main__ import _build_app
    mcp = _build_app(agora_dir=agora_dir, port=8499)
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "agora.wait_notify" in names
```

(`agora_dir` 픽스처는 `tests/conftest.py`가 제공하는 tmp `.agentagora` 디렉터리다.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_wait_notify.py::test_wait_notify_tool_registered -v`
Expected: FAIL — `assert 'agora.wait_notify' in {...}` (도구 미등록)

- [ ] **Step 3: 서버 도구 추가**

In `src/agent_agora/server.py`, `agora.wait` 도구를 정의하는 `agora_wait` 함수가 끝나는 곳(그 함수의 `return json.dumps(...)` 들 다음, `# --- MCP execution.taskSupport hint ---` 주석 앞) 에 추가:

```python
    @mcp.tool(name="agora.wait_notify")
    async def agora_wait_notify(instance_id: str, timeout_ms: int | None = None) -> str:
        """Non-destructive long-poll — block until instance_id has inbound,
        then return {instance_id, pending, sources} without draining the queue.
        For the agora-channel adapter. instance_id need not be registered."""
        try:
            result = await dispatcher.wait_notify(
                instance_id=instance_id, timeout_ms=timeout_ms)
            return json.dumps(result, ensure_ascii=False)
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})
```

(`json`, `DispatcherClosed`는 `server.py`가 이미 임포트하고 있다.)

- [ ] **Step 4: 테스트 통과 + 전체 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_wait_notify.py -v`
Expected: 8건 PASS

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS (기존 테스트 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_wait_notify.py
git commit -m "feat: agora.wait_notify 도구"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.2(`wait_notify` 시그니처·비파괴 스냅샷·`_waiters`/`_wake` 재사용·`last_seen` 갱신·미등록 instance_id 허용·advisory)는 Task 1이, 서버 도구 노출은 Task 2가 구현한다. §3.5의 `wait_notify` 테스트 6항목(즉시 반환 / 블록-후-반환 / timeout 빈 / 비파괴 / last_seen / wait 공존)은 Task 1의 7개 테스트가 커버(+ distinct sources 추가).
- **Placeholder** — 없음. 모든 코드·명령·기대 출력 구체적.
- **타입 일관성** — `wait_notify(instance_id: str, timeout_ms: int | None = None) -> dict[str, Any]`는 Task 1·2에서 동일. `Dispatcher`의 기존 멤버(`_closed`·`_default_timeout_ms`·`_lock`·`_queues`·`_waiters`·`_touch_last_seen`)와 `Envelope.source`는 기존 정의와 일치. 반환 dict 키 `instance_id`/`pending`/`sources`는 Task 1 구현과 테스트에서 일관.
