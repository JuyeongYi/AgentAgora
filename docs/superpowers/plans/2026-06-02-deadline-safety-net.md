# Deadline 안전망 구현 플랜 (Plan A1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `expect_result` 명령에 deadline을 강제해, 응답이 deadline 내 도착하지 않으면 발신자에게 `agora.error`(timeout)를 통지하고 `_in_flight`를 해제한다 — 교착·죽은 워커·느린 응답을 한 메커니즘으로 처리.

**Architecture:** dispatch 시 `expect_result=true`면 기본 deadline을 부여하고 `_deadlines[cmd_id]`에 색인한다. 주기 sweeper(`deadline_sweep`)가 만료된 명령을 찾아 `dispatcher.expire_overdue_deadlines()`(lock 안)로 timeout envelope를 발신자 큐에 주입하고 in_flight를 해제한다. 재시작 시 영속 메시지의 `deadline_ts`로 `_deadlines`를 복원한다.

**Tech Stack:** Python 3.13, asyncio, SQLite(WAL), pytest. 선행 spec: `docs/superpowers/specs/2026-06-02-routing-core-deadline-observability-design.md` §4 A-2.

---

## File Structure

- `src/agent_agora/dispatcher.py` — `_deadlines` 상태, dispatch/broadcast의 기본 deadline 부여, `expire_overdue_deadlines()`, `_emit_timeout()` 헬퍼, restore 보강
- `src/agent_agora/sweeper.py` — `deadline_sweep()` (dispatcher로 위임하는 thin async wrapper)
- `src/agent_agora/__main__.py` — 주기 루프에 `deadline_sweep` 합류
- `src/agent_agora/default_schemas.jsonl` — `agora.error` 예약 msgtype
- `tests/test_v4_deadline.py` — 신규 테스트

## 사전 참고 (현재 코드 사실)

- `Dispatcher.__init__`: `dispatcher.py:75-84`에 `_queues`, `_in_flight`, `_last_dispatch_to` 선언. `_default_timeout_ms`(기본 60000)는 `:70`.
- dispatch가 `_in_flight` 등록: `dispatcher.py:279-280` (`expect_result and target not None and target != source and target_kind != "bot"`).
- timeout envelope 주입 패턴: `dispatcher.py:770-779`의 system enqueue(`make_envelope(source="agora-system", ...)` → `_queues[target].append` → `_wake`).
- reply correlation(in_flight 해제) 기존 패턴: `dispatcher.py:322-330`.
- restore: `restore_from_persistence` (`dispatcher.py:865-890`) — `restore_inflight()` rows에 `deadline_ts` 포함(`persistence.py:138,148`).
- `_now_iso()`는 dispatcher 모듈 헬퍼(ISO8601 UTC). `make_envelope`는 `envelope.py:59`.

---

### Task 1: `expect_result` 기본 deadline 부여 + `_deadlines` 색인

**Files:**
- Modify: `src/agent_agora/dispatcher.py` (`__init__` 상태, `dispatch`, `broadcast`)
- Test: `tests/test_v4_deadline.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_v4_deadline.py
import datetime
import pytest
from tests.helpers import make_dispatcher, register  # 기존 테스트 헬퍼 관례를 따를 것

@pytest.mark.asyncio
async def test_expect_result_gets_default_deadline():
    d, *_ = await make_dispatcher(default_timeout_ms=60000)
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True)
    cmd = r["command_id"]
    # _deadlines에 색인되고, 약 60s 뒤 ISO 시각이다
    assert cmd in d._deadlines
    dl = datetime.datetime.fromisoformat(d._deadlines[cmd])
    created = datetime.datetime.fromisoformat(r["created_at"])
    assert 55 <= (dl - created).total_seconds() <= 65

@pytest.mark.asyncio
async def test_explicit_deadline_is_respected():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    explicit = "2030-01-01T00:00:00+00:00"
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True, deadline_ts=explicit)
    assert d._deadlines[r["command_id"]] == explicit

@pytest.mark.asyncio
async def test_no_deadline_without_expect_result():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"})
    assert r["command_id"] not in d._deadlines
```

(테스트 헬퍼 `make_dispatcher`/`register`가 없으면 기존 `tests/test_v4_*.py`의 셋업 패턴을 그대로 복사해 모듈 상단 fixture로 둘 것 — 새 픽스처를 발명하지 말 것.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_deadline.py -v`
Expected: FAIL — `AttributeError: 'Dispatcher' object has no attribute '_deadlines'`

- [ ] **Step 3: 구현**

`dispatcher.py:84` (`self._last_dispatch_to` 선언 직후)에 추가:

```python
        # cmd_id -> deadline_ts(ISO). expect_result 미응답 엣지의 만료 색인.
        self._deadlines: dict[str, str] = {}
```

`dispatcher.py:279-280`의 in_flight 등록 블록을 deadline 계산 포함으로 교체:

```python
            if expect_result and target is not None and target != source and target_kind != "bot":
                self._in_flight.setdefault(source, {}).setdefault(cmd_id, set()).add(target)
                eff_deadline = deadline_ts
                if eff_deadline is None:
                    eff_deadline = (
                        datetime.datetime.fromisoformat(now)
                        + datetime.timedelta(milliseconds=self._default_timeout_ms)
                    ).isoformat()
                self._deadlines[cmd_id] = eff_deadline
                primary_env = dataclasses.replace(primary_env, deadline_ts=eff_deadline)
                self._queues[target][-1] = primary_env
```

주의: `primary_env`는 `:274`에서 이미 만들어 큐 끝에 append돼 있다. frozen dataclass라 `dataclasses.replace`로 deadline을 채운 새 envelope으로 큐 마지막 항목을 교체한다. 모듈 상단에 `import dataclasses` 없으면 추가. `datetime`은 이미 import됨(`:699` 사용처 확인).

`broadcast`에도 동일 로직 적용 — `broadcast`가 per-target in_flight를 등록하는 지점(`dispatcher.py:461` 부근)에서 같은 패턴으로 `eff_deadline` 계산 + `_deadlines[cmd_id] = eff_deadline` + 해당 target envelope의 deadline 치환. broadcast는 cmd_id 하나에 다중 target이므로 `_deadlines[cmd_id]`는 1회만 계산해 공유한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_deadline.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_deadline.py
git commit -m "feat(deadline): expect_result에 기본 deadline 부여 + _deadlines 색인"
```

---

### Task 2: timeout envelope 주입 헬퍼 + in_flight/_deadlines 해제

**Files:**
- Modify: `src/agent_agora/dispatcher.py` (`_emit_timeout`, `expire_overdue_deadlines`)
- Test: `tests/test_v4_deadline.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.asyncio
async def test_expire_injects_timeout_and_clears_inflight():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    # 이미 만료된 deadline으로 dispatch
    past = "2000-01-01T00:00:00+00:00"
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True, deadline_ts=past)
    cmd = r["command_id"]
    expired = await d.expire_overdue_deadlines(now_iso=d._now_for_test())
    assert cmd in [e["command_id"] for e in expired]
    # 발신자 A 큐에 agora.error(timeout)
    inbox = await d.flush(instance_id="A")
    errs = [m for m in inbox if m["payload"].get("msgtype") == "agora.error"]
    assert errs and errs[0]["payload"]["error"] == "timeout"
    assert errs[0]["payload"]["command_id"] == cmd
    # in_flight·_deadlines 해제
    assert cmd not in d._deadlines
    assert d.in_flight_count("B") == 0

@pytest.mark.asyncio
async def test_expire_noop_when_reply_already_cleared_inflight():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    past = "2000-01-01T00:00:00+00:00"
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True, deadline_ts=past)
    cmd = r["command_id"]
    # B가 먼저 회신 → in_flight 해제
    await d.dispatch(source="B", target="A",
                     payload={"msgtype": "result", "text": "done"},
                     in_reply_to=cmd)
    expired = await d.expire_overdue_deadlines(now_iso=d._now_for_test())
    assert cmd not in [e["command_id"] for e in expired]
```

`d._now_for_test()`는 발명하지 말고, 테스트에서 직접 `datetime.datetime.now(datetime.timezone.utc).isoformat()`를 인자로 넘길 것. 위 두 줄을 그 호출로 치환:
`expired = await d.expire_overdue_deadlines(now_iso=datetime.datetime.now(datetime.timezone.utc).isoformat())`

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_deadline.py::test_expire_injects_timeout_and_clears_inflight -v`
Expected: FAIL — `expire_overdue_deadlines` 없음

- [ ] **Step 3: 구현**

`dispatcher.py`의 `in_flight_count`(`:781`) 근처에 추가:

```python
    def _emit_timeout(self, source: str, cmd_id: str, target: str, now: str) -> None:
        """발신자(source) 큐에 timeout 통지를 주입하고 깨운다. _lock 보유 상태에서 호출."""
        env = make_envelope(
            cmd_id=str(uuid.uuid4()), source="agora-system", target=source,
            payload={
                "msgtype": "agora.error", "error": "timeout",
                "command_id": cmd_id, "target": target, "ts": now,
            },
            created_at=now, conversation_id=(self._conv.conv_id_of(cmd_id) or str(uuid.uuid4())),
            expect_result=False, delivered_as="primary", dispatch_kind="direct",
            in_reply_to=cmd_id,
        )
        self._queues[source].append(env)
        self._wake(source)

    async def expire_overdue_deadlines(self, now_iso: str) -> list[dict]:
        """deadline 초과한 미응답 expect_result 엣지를 만료시킨다.
        각 (source, cmd_id, target)에 timeout 통지 후 in_flight/_deadlines 해제.
        만료된 항목 메타 리스트 반환."""
        expired: list[dict] = []
        async with self._lock:
            if self._closed:
                return expired
            # 만료 후보 cmd_id (스냅샷 — 순회 중 변형 회피)
            overdue = [cid for cid, dl in self._deadlines.items() if dl < now_iso]
            for cmd_id in overdue:
                # cmd_id를 보유한 source 찾기
                for source, pending_map in list(self._in_flight.items()):
                    targets = pending_map.get(cmd_id)
                    if not targets:
                        continue
                    for target in list(targets):
                        self._emit_timeout(source, cmd_id, target, now_iso)
                        targets.discard(target)
                        expired.append({"command_id": cmd_id, "source": source, "target": target})
                    if not targets:
                        pending_map.pop(cmd_id, None)
                # 해당 cmd_id가 어디서도 미응답이 아니면 색인 제거
                still = any(cmd_id in pm for pm in self._in_flight.values())
                if not still:
                    self._deadlines.pop(cmd_id, None)
        return expired
```

`uuid` import는 이미 있음(`dispatcher.py:223` 사용). 

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_deadline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_deadline.py
git commit -m "feat(deadline): expire_overdue_deadlines — timeout 통지 + in_flight 해제"
```

---

### Task 3: `deadline_sweep` + 주기 루프 합류

**Files:**
- Modify: `src/agent_agora/sweeper.py`, `src/agent_agora/__main__.py`
- Test: `tests/test_v4_deadline.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.asyncio
async def test_sweeper_deadline_sweep_delegates():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    past = "2000-01-01T00:00:00+00:00"
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True, deadline_ts=past)
    expired = await d.sweeper.deadline_sweep()
    assert r["command_id"] in [e["command_id"] for e in expired]
    assert d.in_flight_count("B") == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_deadline.py::test_sweeper_deadline_sweep_delegates -v`
Expected: FAIL — `Sweeper` has no `deadline_sweep`

- [ ] **Step 3: 구현**

`sweeper.py`의 `message_gc_sweep` 뒤에 추가:

```python
    async def deadline_sweep(self, now: datetime.datetime | None = None) -> list[dict]:
        """expect_result deadline 초과 명령을 만료시킨다. Dispatcher로 위임
        (in_flight/_deadlines 조작은 dispatcher._lock 안에서 일어나야 한다).
        dispatcher 미주입(테스트) 시 빈 리스트."""
        if self._dispatcher is None:
            return []
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        return await self._dispatcher.expire_overdue_deadlines(now_iso=now.isoformat())
```

`__main__.py`의 주기 sweep 루프(다른 `sweeper.*_sweep()` 호출이 모여 있는 곳)에 추가:

```python
            await dispatcher.sweeper.deadline_sweep()
```

(루프가 sync sweep만 호출하면 `await`를 쓸 수 있는 async 컨텍스트인지 확인 — 기존 루프가 `asyncio` 태스크이므로 await 가능. 다른 sweep은 sync라 그대로 두고 이 한 줄만 await.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_deadline.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/sweeper.py src/agent_agora/__main__.py tests/test_v4_deadline.py
git commit -m "feat(deadline): sweeper.deadline_sweep + 주기 루프 합류"
```

---

### Task 4: 재시작 `_deadlines` 복원 + `agora.error` 스키마 등록

**Files:**
- Modify: `src/agent_agora/dispatcher.py` (`restore_from_persistence`), `src/agent_agora/default_schemas.jsonl`
- Test: `tests/test_v4_deadline.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.asyncio
async def test_deadlines_restored_after_restart():
    d, persistence, write_queue, *_ = await make_dispatcher_persistent()  # 영속 DB 공유 헬퍼
    await register(d, "A"); await register(d, "B")
    past = "2000-01-01T00:00:00+00:00"
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True, deadline_ts=past)
    cmd = r["command_id"]
    # 새 dispatcher가 같은 DB에서 복원
    d2 = await rebuild_dispatcher(persistence, write_queue)
    d2.restore_from_persistence()
    assert d2._deadlines.get(cmd) == past
```

(영속 공유/재구성 헬퍼가 없으면 기존 재시작 복구 테스트 — `tests/`에서 `restore_from_persistence`를 검증하는 테스트를 찾아 동일 셋업을 재사용할 것. 없으면 본 테스트는 동일 DB 경로로 `Persistence`를 두 번 열어 구성.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_deadline.py::test_deadlines_restored_after_restart -v`
Expected: FAIL — `d2._deadlines`가 비어 있음

- [ ] **Step 3: 구현**

`dispatcher.py:865-882`의 `restore_from_persistence` 루프(envs 순회) 안, `self._queues[...].append(env)` 뒤에 추가:

```python
            if bool(row["expect_result"]) and row["deadline_ts"] and row["delivered_as"] == "primary":
                self._deadlines[row["command_id"]] = row["deadline_ts"]
```

`default_schemas.jsonl`에 한 줄 추가(시스템 통지의 문서화·일관성용 — 수신 검증엔 불필요하지만 dashboard/스키마 explorer에 노출):

```json
{"name": "agora.error", "kind": "conversation", "purpose": "시스템 통지(timeout 등). agora-system이 발신자에게 주입.", "body": {"type": "object", "required": ["msgtype", "error"], "properties": {"msgtype": {"type": "string", "const": "agora.error"}, "error": {"type": "string"}, "command_id": {"type": "string"}, "target": {"type": "string"}, "ts": {"type": "string"}}, "additionalProperties": true}}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_deadline.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `python -m pytest tests/ -q`
Expected: 기존 테스트 회귀 없음(deadline 부여로 일부 테스트가 envelope의 `deadline_ts`를 None으로 단정하면 갱신 필요 — 그럴 경우 해당 단정을 실제 동작에 맞게 수정).

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/default_schemas.jsonl tests/test_v4_deadline.py
git commit -m "feat(deadline): 재시작 _deadlines 복원 + agora.error 스키마 등록"
```

---

## Self-Review 메모

- spec §4 A-2a(기본 deadline)=Task1, A-2b(deadline_sweep)=Task3, A-2c(timeout 의미)=Task2, A-2d(_deadlines 색인·복원)=Task1+Task4. 전부 커버.
- 경쟁(reply vs sweep): Task2 `expire_overdue_deadlines`가 `_lock` 안에서 in_flight를 확인하므로, reply가 먼저 비웠으면 자연 no-op (test_expire_noop_when_reply_already_cleared_inflight).
- broadcast 다중 target 독립 만료: Task1에서 cmd_id 공유 deadline, Task2가 target별로 discard → 부분 만료 가능.
- 늦은 reply: in_flight에서 이미 빠졌으면 reply correlation 대상 없음(기존 `:322` 로직이 자연 no-op). 별도 처리 불필요.
