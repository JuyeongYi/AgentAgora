# comm-matrix v2 — flush weight-aware 정렬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `flush`가 인박스를 엣지 weight(1차)·메시지 priority(2차)·created_at(3차) 순으로 정렬하게 하고, 기본 정렬을 `priority`로 바꾼다.

**Architecture:** `Dispatcher.flush`의 `sort="priority"` 분기에 `CommMatrix.weight_of`를 1차 키로 추가한다. weight는 flush 시점 조회 — envelope·DB 스키마 불변. `flush`의 `sort` 기본값과 `agora.flush` MCP 도구의 `sort` 기본값을 `"fifo"`→`"priority"`로 바꾼다.

**Tech Stack:** Python 3.13, pytest. spec: `docs/superpowers/specs/2026-05-17-comm-matrix-v2-priority-design.md`.

**선행 의존:** Plan 1(`2026-05-17-comm-matrix-v2-model.md`)이 먼저 머지돼야 한다 — `CommMatrix.weight_of`가 이 플랜의 전제다.

테스트는 `.venv\Scripts\python.exe -m pytest`로 실행한다.

---

### Task 1: flush weight-aware 정렬 + 기본값 변경

**Files:**
- Modify: `src/agent_agora/dispatcher.py:704-747` (`Dispatcher.flush` 시그니처 + 정렬 블록)
- Test: `tests/test_v4_comm_matrix.py` (신규 테스트 — `_make_dispatcher` 헬퍼 재사용)

- [ ] **Step 1: 실패하는 정렬 테스트 작성**

`tests/test_v4_comm_matrix.py` 끝에 추가. `_make_dispatcher`(Inst1·Coder1·Reviewer1·Tester1 등록 + registry/persistence/queue 반환)는 같은 파일에 이미 있다.

```python
_W_INST1 = "Inst1,Coder1,Reviewer1,Tester1\n0,1,5,1\n1,0,0,0\n1,0,0,0\n1,0,0,0"


@pytest.mark.asyncio
async def test_flush_priority_orders_by_edge_weight(tmp_path):
    """flush sort=priority — 큰 weight 엣지의 메시지가 먼저."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)  # Coder1->Inst1 weight 1, Reviewer1->Inst1 weight 5
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1", payload=tany(s="w1"))
        await d.dispatch(source="Reviewer1", target="Inst1", payload=tany(s="w5"))
        drained = await d.flush("Inst1", sort="priority")
        assert [c["payload"]["s"] for c in drained] == ["w5", "w1"]


@pytest.mark.asyncio
async def test_flush_edge_weight_beats_message_priority(tmp_path):
    """weight가 1차 키 — 큰 weight low가 작은 weight high보다 먼저."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1",
                         payload=tany(s="w1-high"), priority="high")
        await d.dispatch(source="Reviewer1", target="Inst1",
                         payload=tany(s="w5-low"), priority="low")
        drained = await d.flush("Inst1", sort="priority")
        assert [c["payload"]["s"] for c in drained] == ["w5-low", "w1-high"]


@pytest.mark.asyncio
async def test_flush_same_weight_orders_by_message_priority(tmp_path):
    """같은 weight 엣지 내에서는 메시지 priority가 2차 키."""
    cm = CommMatrix()
    # Coder1->Inst1, Reviewer1->Inst1 둘 다 weight 5
    cm.load_csv("Inst1,Coder1,Reviewer1,Tester1\n0,5,5,1\n1,0,0,0\n1,0,0,0\n1,0,0,0")
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1",
                         payload=tany(s="low"), priority="low")
        await d.dispatch(source="Reviewer1", target="Inst1",
                         payload=tany(s="high"), priority="high")
        drained = await d.flush("Inst1", sort="priority")
        assert [c["payload"]["s"] for c in drained] == ["high", "low"]


@pytest.mark.asyncio
async def test_flush_default_sort_is_priority(tmp_path):
    """flush() sort 미지정 기본값이 priority — weight 큰 메시지 먼저."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1", payload=tany(s="w1"))
        await d.dispatch(source="Reviewer1", target="Inst1", payload=tany(s="w5"))
        drained = await d.flush("Inst1")  # sort 미지정 → 기본 priority
        assert [c["payload"]["s"] for c in drained] == ["w5", "w1"]


@pytest.mark.asyncio
async def test_flush_fifo_ignores_weight(tmp_path):
    """sort=fifo escape hatch — weight 무시, created_at 순."""
    cm = CommMatrix()
    cm.load_csv(_W_INST1)
    registry, persistence, queue = await _make_dispatcher(tmp_path, cm)
    async with queue:
        d = Dispatcher(registry, persistence, queue,
                       schema_registry=make_schema_registry(),
                       bot_registry=BotRegistry(), comm_matrix=cm,
                       default_timeout_ms=200)
        await d.dispatch(source="Coder1", target="Inst1", payload=tany(s="first"))
        await d.dispatch(source="Reviewer1", target="Inst1", payload=tany(s="second"))
        drained = await d.flush("Inst1", sort="fifo")
        assert [c["payload"]["s"] for c in drained] == ["first", "second"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -k "flush_priority or flush_edge or flush_same or flush_default" -v`
Expected: FAIL — 현 `flush`는 weight를 정렬에 쓰지 않고 기본값이 `fifo`라 weight 순서가 나오지 않음.

- [ ] **Step 3: flush 시그니처 기본값 변경**

`src/agent_agora/dispatcher.py`의 `flush` 메서드 시그니처(현 707행 부근)에서 `sort` 기본값을 바꾼다:

```python
    async def flush(
        self,
        instance_id: str,
        from_sources: list[str] | None = None,
        sort: Literal["fifo", "priority"] = "priority",
        by_conversation: str | None = None,
    ) -> list[dict[str, Any]]:
```

- [ ] **Step 4: flush 정렬 블록을 weight-aware로 교체**

같은 메서드의 정렬 블록(현 743-747행)을 교체:

```python
        # sort — priority: 엣지 weight 1차, 메시지 priority 2차, created_at 3차
        if sort == "priority":
            drained.sort(key=lambda e: (
                -self._comm_matrix.weight_of(e.source, instance_id),
                _PRIORITY_RANK[e.priority],
                e.created_at,
                e.id,
            ))
        else:
            drained.sort(key=lambda e: (e.created_at, e.id))
```

`_PRIORITY_RANK`는 `dispatcher.py` 상단에서 이미 import돼 있다. `self._comm_matrix`도 `__init__`에서 이미 보관 중이다 — 추가 변경 불필요.

- [ ] **Step 5: 신규 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -k "flush" -v`
Expected: 5개 신규 테스트 전부 PASS.

- [ ] **Step 6: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

기본값이 `priority`로 바뀌었지만 비활성 매트릭스에서는 `weight_of`가 모두 `0`이라 정렬 키가 `(0, _PRIORITY_RANK[priority], created_at, id)`로 떨어진다 — 동일 priority 메시지들에 대해 created_at 순(=fifo와 동일). 따라서 비활성 매트릭스 + 균일 priority를 쓰는 기존 테스트는 영향이 없다. 만약 특정 테스트가 서로 다른 priority 메시지를 섞어 보내고 `flush()`를 sort 인자 없이 호출하며 FIFO 순서를 단정한다면, 그 테스트는 암묵적으로 fifo에 의존했던 것이다 — 해당 테스트 호출을 `sort="fifo"`로 명시하도록 고친다.

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_comm_matrix.py
git commit -m "feat: flush — 엣지 weight 우선 정렬, 기본값 priority"
```

---

### Task 2: `agora.flush` 도구 기본값 + 문서

`agora.flush` MCP 도구는 자체 `sort` 기본값(`"fifo"`)을 가지므로 Task 1의 dispatcher 기본값 변경만으로는 도구 호출자에게 반영되지 않는다. 도구 시그니처와 docstring을 맞춘다.

**Files:**
- Modify: `src/agent_agora/server.py:419-434` (`agora.flush` 도구 시그니처 + docstring)
- Test: `tests/test_v4_comm_matrix.py` (신규 도구 테스트 — `cm_app` fixture 재사용)

- [ ] **Step 1: 실패하는 도구 테스트 작성**

`tests/test_v4_comm_matrix.py` 끝에 추가. `cm_app` fixture(`(mcp, dispatcher, comm_matrix)` yield), `_tool`, `_FakeCtx`는 같은 파일에 이미 있다.

```python
@pytest.mark.asyncio
async def test_flush_tool_default_sort_is_priority(cm_app):
    """agora.flush 도구의 sort 기본값이 priority — weight 큰 메시지 먼저."""
    mcp, _, comm_matrix = cm_app
    comm_matrix.load_csv(
        "Inst1,Coder1,Reviewer1,Tester1\n0,1,5,1\n1,0,0,0\n1,0,0,0\n1,0,0,0")
    await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Coder1"), payload=tany(s="w1"), target="Inst1")
    await _tool(mcp, "agora.dispatch")(
        _FakeCtx("sess-Reviewer1"), payload=tany(s="w5"), target="Inst1")
    res = json.loads(await _tool(mcp, "agora.flush")(_FakeCtx("sess-Inst1")))
    assert [c["payload"]["s"] for c in res["commands"]] == ["w5", "w1"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py::test_flush_tool_default_sort_is_priority -v`
Expected: FAIL — 도구 기본값이 `fifo`라 `["w1", "w5"]`(created_at 순)이 나옴.

- [ ] **Step 3: 도구 시그니처 기본값 변경**

`src/agent_agora/server.py`의 `agora_flush` 시그니처(현 423행)에서 `sort` 기본값을 바꾼다:

```python
    @mcp.tool(name="agora.flush")
    async def agora_flush(
        ctx: Context,
        from_sources: list[str] | None = None,
        sort: Literal["fifo", "priority"] = "priority",
        by_conversation: str | None = None,
    ) -> str:
```

- [ ] **Step 4: 도구 docstring 갱신**

같은 도구의 docstring에서 `sort` 설명 문단(현 431-432행)을 교체:

```python
        Default sort='priority': the inbox is ordered by comm-matrix edge weight
        (descending), then message priority (high>normal>low), then created_at.
        sort='fifo' falls back to (created_at asc, command_id asc).
        from_sources / by_conversation: AND-combined filters; unmatched envelopes stay queued.
        The caller MUST be registered before calling flush.
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py::test_flush_tool_default_sort_is_priority -v`
Expected: PASS

- [ ] **Step 6: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_comm_matrix.py
git commit -m "feat: agora.flush 도구 기본 정렬 priority"
```

---

## 완료 기준

- `flush(sort="priority")`가 엣지 weight 내림차순 → 메시지 priority → created_at 순으로 정렬한다.
- 큰 weight 엣지의 `low` 메시지가 작은 weight 엣지의 `high` 메시지보다 먼저 온다.
- `flush`·`agora.flush` 도구의 `sort` 기본값이 `priority`다.
- `sort="fifo"`는 weight를 무시하는 escape hatch로 동작한다.
- 전체 테스트 스위트 통과.

## 비목표 (YAGNI)

- `_queues`를 heapq로 전환 (flush 전량 드레인이라 불필요).
- weight를 envelope·DB에 stamp (flush 시점 조회로 충분).
- broadcast fan-out 순서에 weight 반영.
