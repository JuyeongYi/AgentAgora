# BotRegistry dead-bot sweep 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** crash·kill로 죽은 봇을 서버가 TTL sweep으로 감지·정리해, 죽은 봇이 라우팅 대상에 영구히 남는 것을 막는다.

**Architecture:** `Dispatcher`에 `dead_bot_sweep()`를 추가한다 — 워커용 `dead_session_sweep`의 봇 버전. `BotRegistry`의 각 봇이 마지막으로 `agora.wait`를 호출한 시각(`last_seen_at`, 없으면 `registered_at`)이 `dead_session_timeout`을 넘으면 `unregister_session`으로 정리한다. 정리 시 구독 역인덱스도 detach되어 라우팅이 즉시 죽은 봇을 건너뛴다. 기존 60초 sweep 루프에 한 줄 배선한다.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio. spec: `docs/superpowers/specs/2026-05-16-bot-sdk-lifecycle-design.md` §3.2.

**전제:** spec §4 — 이 plan은 SDK plan(`2026-05-16-bot-sdk.md`)과 독립이며 순서 무관. 테스트 인터프리터는 저장소 `.venv`(Python 3.13, `agent_agora` editable + pytest 설치됨).

---

### Task 1: `Dispatcher.dead_bot_sweep()`

**Files:**
- Create: `tests/test_v4_bot_sweep.py`
- Modify: `src/agent_agora/dispatcher.py` — `dead_session_sweep` 메서드 바로 다음(약 994행, `message_gc_sweep` 앞)에 `dead_bot_sweep` 추가

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_v4_bot_sweep.py`:

```python
"""dead_bot_sweep — BotRegistry TTL 정리 테스트."""
from __future__ import annotations

import dataclasses
import datetime

import pytest

from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry

TIMEOUT_MS = 1_800_000  # 30분 — Dispatcher 기본 dead_session_timeout_ms


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        bot_registry = BotRegistry()
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=bot_registry,
            comm_matrix=CommMatrix(),
            default_timeout_ms=500,
            dead_session_timeout_ms=TIMEOUT_MS,
        )
        yield bot_registry, dispatcher


@pytest.mark.asyncio
async def test_stale_bot_is_swept_and_subscriptions_detached(setup):
    bot_registry, dispatcher = setup
    bot_registry.register(session_id="bs1", instance_id="bot_a", description="d",
                          bot_mode="handler", subscribe_schemas=["pytest_run"])
    reg_at = datetime.datetime.fromisoformat(
        bot_registry.resolve_instance_id("bot_a").registered_at)
    future = reg_at + datetime.timedelta(milliseconds=TIMEOUT_MS + 1000)
    swept = dispatcher.dead_bot_sweep(now=future)
    assert swept == ["bot_a"]
    assert bot_registry.is_bot("bot_a") is False
    assert bot_registry.subscribers_of("pytest_run") == set()


@pytest.mark.asyncio
async def test_healthy_bot_is_preserved(setup):
    bot_registry, dispatcher = setup
    bot_registry.register(session_id="bs1", instance_id="bot_a", description="d",
                          bot_mode="handler", subscribe_schemas=["pytest_run"])
    reg_at = datetime.datetime.fromisoformat(
        bot_registry.resolve_instance_id("bot_a").registered_at)
    swept = dispatcher.dead_bot_sweep(now=reg_at + datetime.timedelta(seconds=1))
    assert swept == []
    assert bot_registry.is_bot("bot_a") is True


@pytest.mark.asyncio
async def test_never_waited_bot_uses_registered_at_fallback(setup):
    bot_registry, dispatcher = setup
    info = bot_registry.register(session_id="bs1", instance_id="bot_a",
                                 description="d", bot_mode="handler",
                                 subscribe_schemas=["pytest_run"])
    assert info.last_seen_at is None  # wait 한 번도 안 함
    reg_at = datetime.datetime.fromisoformat(info.registered_at)
    future = reg_at + datetime.timedelta(milliseconds=TIMEOUT_MS + 1000)
    # last_seen_at=None이어도 crash 없이 registered_at으로 판정
    swept = dispatcher.dead_bot_sweep(now=future)
    assert swept == ["bot_a"]


@pytest.mark.asyncio
async def test_recent_last_seen_overrides_old_registered_at(setup):
    bot_registry, dispatcher = setup
    bot_registry.register(session_id="bs1", instance_id="bot_a", description="d",
                          bot_mode="handler", subscribe_schemas=["pytest_run"])
    base = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
    old = (base - datetime.timedelta(hours=2)).isoformat()       # registered_at
    fresh = (base - datetime.timedelta(minutes=1)).isoformat()   # last_seen_at
    info = bot_registry._by_instance["bot_a"]
    updated = dataclasses.replace(info, registered_at=old, last_seen_at=fresh)
    bot_registry._by_instance["bot_a"] = updated
    bot_registry._by_session[updated.session_id] = updated
    # registered_at(2시간 전)만 보면 스윕될 시점 — last_seen(1분 전)이 우선
    swept = dispatcher.dead_bot_sweep(now=base)
    assert swept == []
    assert bot_registry.is_bot("bot_a") is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_bot_sweep.py -v`
Expected: 4건 모두 FAIL — `AttributeError: 'Dispatcher' object has no attribute 'dead_bot_sweep'`

- [ ] **Step 3: `dead_bot_sweep` 구현**

In `src/agent_agora/dispatcher.py`, `dead_session_sweep` 메서드가 끝나는 줄(`return removed`) 바로 다음에 추가:

```python
    def dead_bot_sweep(self, now: datetime.datetime | None = None) -> list[str]:
        """Unregister bots whose last_seen_at (or registered_at, if the bot has
        never returned from a wait) exceeded dead_session_timeout. Detaches the
        bot's schema subscriptions so routing immediately stops targeting it.
        Returns swept bot instance_ids. Queued messages are left untouched —
        identical to dead_session_sweep for workers."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(milliseconds=self._dead_session_timeout_ms)
        removed: list[str] = []
        for bot in self._bot_registry.list_bots():
            marker = bot.last_seen_at or bot.registered_at
            if datetime.datetime.fromisoformat(marker) < cutoff:
                self._bot_registry.unregister_session(bot.session_id)
                removed.append(bot.instance_id)
        return removed
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_bot_sweep.py -v`
Expected: 4건 PASS

- [ ] **Step 5: 커밋**

```bash
git add tests/test_v4_bot_sweep.py src/agent_agora/dispatcher.py
git commit -m "feat: Dispatcher.dead_bot_sweep — BotRegistry TTL 정리"
```

---

### Task 2: 60초 sweep 루프에 배선

**Files:**
- Modify: `src/agent_agora/__main__.py` — `_sweep_loop_60s` 함수 (약 209-217행)

- [ ] **Step 1: `_sweep_loop_60s`에 `dead_bot_sweep` 호출 추가**

In `src/agent_agora/__main__.py`, `_sweep_loop_60s`를 다음으로 교체:

```python
async def _sweep_loop_60s(dispatcher) -> None:
    """60-second close TTL + dead-session + dead-bot sweeps."""
    while True:
        await asyncio.sleep(60)
        try:
            dispatcher.close_ttl_sweep()
            dispatcher.dead_session_sweep()
            dispatcher.dead_bot_sweep()
        except Exception as e:
            print(f"[agora] sweep error: {e}", file=sys.stderr)
```

- [ ] **Step 2: 전체 테스트 통과 확인**

소스 변경은 sweep 루프에 한 줄 추가뿐 — `dead_bot_sweep` 자체는 Task 1에서 검증됨. 회귀가 없는지 전체 스위트로 확인한다.

Run: `python -m pytest tests/ -q`
Expected: 전체 PASS (Task 1의 신규 4건 포함, 기존 테스트 회귀 없음)

- [ ] **Step 3: 커밋**

```bash
git add src/agent_agora/__main__.py
git commit -m "feat: 60초 sweep 루프에 dead_bot_sweep 배선"
```

---

## Self-Review

- **Spec 커버리지** — §3.2(`dead_bot_sweep`, `last_seen_at or registered_at` 폴백, 구독 detach, 임계값 `_dead_session_timeout_ms` 재사용, 큐 미정리)는 Task 1이, `__main__.py` 60초 루프 배선은 Task 2가 구현한다. §3.5의 sweep 테스트 4항목(stale 정리+detach / healthy 보존 / `last_seen_at is None` 폴백 / last_seen 우선)은 Task 1의 4개 테스트가 커버한다.
- **Placeholder** — 없음. 모든 코드·명령·기대 출력이 구체적이다.
- **타입 일관성** — `dead_bot_sweep(now=None) -> list[str]`는 `dead_session_sweep`과 동일 시그니처. `BotInfo.last_seen_at`/`registered_at`/`session_id`/`instance_id`, `BotRegistry.list_bots()`/`unregister_session()`/`subscribers_of()`/`is_bot()`는 모두 기존 정의와 일치.
