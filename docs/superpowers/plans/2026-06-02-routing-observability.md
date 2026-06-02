# 라우팅 Observability 구현 플랜 (Plan A2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** comm-matrix 사이클 진단(`cycles()`), 불완전 전송 가시화(`deliveries[]`), 그리고 4개 observability 도구(`agora.transcript`/`coverage`/`reply`/`cancel`)를 추가한다.

**Architecture:** 전부 기존 dispatcher 상태(`_in_flight`, `_deadlines`, conversation participants)와 SQLite(`messages`)를 읽기/조작하는 얇은 계층이다. 각 도구는 `dispatcher`에 메서드를 두고 `server.py`에서 `@mcp.tool`로 노출한다.

**Tech Stack:** Python 3.13, asyncio, SQLite, pytest. 선행: Plan A1(deadline) 머지 완료 가정 — `_deadlines` 색인을 `coverage`/`cancel`이 사용한다. 선행 spec: `docs/superpowers/specs/2026-06-02-routing-core-deadline-observability-design.md` §4 A-1·A-3·A-4~7.

---

## File Structure

- `src/agent_agora/comm_matrix.py` — `cycles()` 진단(순수, 거부 없음)
- `src/agent_agora/dispatcher.py` — `transcript`/`coverage`/`reply`/`cancel` 메서드, `_last_inbound` 추적, dispatch 반환 `deliveries[]`
- `src/agent_agora/persistence.py` — `fetch_transcript(conversation_id, since_ts)`
- `src/agent_agora/server.py` — 4개 `@mcp.tool` 등록
- `tests/test_comm_matrix.py`(확장), `tests/test_v4_observability.py`, `tests/test_v4_deliveries.py`

## 사전 참고 (현재 코드 사실)

- comm-matrix: `weight_of(from_, to)`(`comm_matrix.py:74`)가 엣지 weight, `snapshot()`(`:100`)이 `{to_pat: {from_pat: w}}`. 헤더는 정규식 패턴.
- dispatch 반환: `dispatcher.py:373-382` — `dispatched_to`(`[{instance_id, as}]`)·`skipped_full`. `cc_deliver`/`subscriber_bots`/`skipped_full`은 lock 블록 내 지역변수.
- flush: `dispatcher.py:647-721` — drain 후 `drained` envelope 리스트 보유. `_last_inbound` 갱신 지점.
- conversation 참가자: `_conv.get(conv_id)["participants"]` = `{iid: {role, delivered}}`. `_conv.conv_id_of(cmd_id)`로 cmd→conv.
- 메시지 조회: `persistence.fetch_messages_for(conversation_id=..., include_acked=True)`(`persistence.py:256`) — created_at ASC 정렬, target별 행. `since_ts` 미지원(신규 메서드로 추가).
- 도구 등록 패턴: `server.py:457` `agora.peek`처럼 session→instance resolve 후 dispatcher 메서드 위임.

---

### Task 1: `CommMatrix.cycles()` 진단

**Files:**
- Modify: `src/agent_agora/comm_matrix.py`
- Test: `tests/test_comm_matrix.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_comm_matrix.py 에 추가
from agent_agora.comm_matrix import CommMatrix

def test_cycles_acyclic_returns_empty():
    cm = CommMatrix()
    # impl→reviewer→improver 선형 (acyclic)
    cm.load_csv("to,impl,reviewer,improver\nimpl,0,0,0\nreviewer,1,0,0\nimprover,0,1,0")
    assert cm.cycles() == []

def test_cycles_detects_two_node_cycle():
    cm = CommMatrix()
    cm.load_csv("to,A,B\nA,0,1\nB,1,0")  # A<->B
    cycles = cm.cycles()
    assert any(set(c) == {"A", "B"} for c in cycles)

def test_cycles_detects_self_loop():
    cm = CommMatrix()
    cm.load_csv("to,A\nA,1")  # A->A
    assert any(c == ["A"] for c in cm.cycles())

def test_cycles_empty_when_inactive():
    cm = CommMatrix()
    assert cm.cycles() == []
```

CSV 형식 주의: 첫 셀은 헤더 라벨(`load_csv`는 헤더 N개 = 데이터 N행을 요구). 위 `"to,A,B"`에서 헤더는 `[to, A, B]`(3컬럼) → 데이터 3행 필요. **수정**: 모서리 라벨 없이 `"A,B\nA,0,1..."`는 shape mismatch. 실제 헤더 규약을 `test_comm_matrix.py` 기존 테스트에서 확인하고 그 형식을 그대로 따를 것(헤더 컬럼 수 == 데이터 행 수). 기존 테스트의 CSV 리터럴을 복사해 변형하라.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_comm_matrix.py -k cycles -v`
Expected: FAIL — `cycles` 없음

- [ ] **Step 3: 구현**

`comm_matrix.py`의 `snapshot` 뒤에 추가:

```python
    def cycles(self) -> list[list[str]]:
        """패턴 그래프(weight>0 엣지)의 사이클을 반환한다. 노드는 CSV 헤더 패턴.
        진단 전용 — 사이클은 정상 워크플로일 수 있으므로 거부·경고하지 않는다.
        2노드 이상 SCC와 자기루프를 모두 보고한다. 비활성이면 빈 리스트."""
        if not self.active:
            return []
        nodes = list(self._weights.keys())
        # adjacency: from_pat -> [to_pat ...] where weight>0
        adj: dict[str, list[str]] = {n: [] for n in nodes}
        self_loops: list[list[str]] = []
        for to_pat, row in self._weights.items():
            for from_pat, w in row.items():
                if w > 0 and from_pat in adj:
                    adj[from_pat].append(to_pat)
                    if from_pat == to_pat:
                        self_loops.append([from_pat])
        # Tarjan SCC
        index = {n: None for n in nodes}
        low = {n: 0 for n in nodes}
        on_stack = {n: False for n in nodes}
        stack: list[str] = []
        counter = [0]
        sccs: list[list[str]] = []

        def strongconnect(v: str) -> None:
            index[v] = counter[0]; low[v] = counter[0]; counter[0] += 1
            stack.append(v); on_stack[v] = True
            for w_ in adj[v]:
                if index[w_] is None:
                    strongconnect(w_); low[v] = min(low[v], low[w_])
                elif on_stack[w_]:
                    low[v] = min(low[v], index[w_])
            if low[v] == index[v]:
                comp: list[str] = []
                while True:
                    w_ = stack.pop(); on_stack[w_] = False; comp.append(w_)
                    if w_ == v:
                        break
                if len(comp) > 1:
                    sccs.append(comp)

        for n in nodes:
            if index[n] is None:
                strongconnect(n)
        return sccs + self_loops
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_comm_matrix.py -k cycles -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/comm_matrix.py tests/test_comm_matrix.py
git commit -m "feat(comm-matrix): cycles() 진단 메서드 (거부 없음)"
```

---

### Task 2: dispatch 반환 `deliveries[]` (TD2)

**Files:**
- Modify: `src/agent_agora/dispatcher.py` (`dispatch` 반환부)
- Test: `tests/test_v4_deliveries.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_v4_deliveries.py
import pytest
from tests.helpers import make_dispatcher, register  # 기존 셋업 관례 따를 것

@pytest.mark.asyncio
async def test_deliveries_marks_skipped_full():
    d, *_ = await make_dispatcher(max_inbox_depth=1)
    await register(d, "A"); await register(d, "B"); await register(d, "C")
    # C 인박스를 채워 cc 전달 실패 유도
    await d.dispatch(source="A", target="C", payload={"msgtype": "task", "text": "fill"})
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"}, cc=["C"])
    by = {e["target"]: e for e in r["deliveries"]}
    assert by["B"]["status"] == "delivered" and by["B"]["role"] == "primary"
    assert by["C"]["status"] == "skipped_full" and by["C"]["role"] == "cc"
    # 하위호환 필드 병존
    assert "dispatched_to" in r and "skipped_full" in r
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_deliveries.py -v`
Expected: FAIL — `KeyError: 'deliveries'`

- [ ] **Step 3: 구현**

`dispatcher.py:373-382` 반환 dict 직전에 `deliveries` 구성 추가:

```python
        deliveries: list[dict[str, str]] = []
        if target is not None:
            deliveries.append({"target": target, "role": "primary", "status": "delivered"})
        deliveries += [{"target": c, "role": "cc", "status": "delivered"} for c in cc_deliver]
        deliveries += [{"target": b, "role": "subscribed", "status": "delivered"}
                       for b in subscriber_bots if b != target]
        deliveries += [{"target": s, "role": "cc", "status": "skipped_full"} for s in skipped_full]
```

반환 dict에 `"deliveries": deliveries,` 추가(기존 `dispatched_to`·`skipped_full`은 유지).

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_deliveries.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_deliveries.py
git commit -m "feat(dispatch): deliveries[] per-target 전달 상태 (TD2)"
```

---

### Task 3: `agora.transcript`

**Files:**
- Modify: `src/agent_agora/persistence.py`, `src/agent_agora/dispatcher.py`, `src/agent_agora/server.py`
- Test: `tests/test_v4_observability.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_v4_observability.py
import pytest
from tests.helpers import make_dispatcher, register

@pytest.mark.asyncio
async def test_transcript_time_ordered_and_since_filter():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r1 = await d.dispatch(source="A", target="B", payload={"msgtype": "task", "text": "1"})
    conv = r1["conversation_id"]
    r2 = await d.dispatch(source="A", target="B", payload={"msgtype": "task", "text": "2"},
                          conversation_id=conv)
    t = d.transcript(conversation_id=conv)
    texts = [m["payload"]["text"] for m in t["messages"]]
    assert texts == ["1", "2"]
    # since_ts 필터 — r1 이후만
    t2 = d.transcript(conversation_id=conv, since_ts=r1["created_at"])
    assert all(m["created_at"] > r1["created_at"] for m in t2["messages"])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_observability.py::test_transcript_time_ordered_and_since_filter -v`
Expected: FAIL — `transcript` 없음

- [ ] **Step 3: 구현**

`persistence.py`의 `fetch_messages_for` 뒤에 추가:

```python
    def fetch_transcript(self, conversation_id: str, since_ts: str | None = None) -> list[dict]:
        """conversation의 논리 메시지를 시간순으로. cmd_id별 1행(primary 우선)으로 dedup."""
        params: list = [conversation_id]
        sql = ("SELECT command_id, source, target, payload, conversation_id, created_at, "
               "delivered_as, in_reply_to FROM messages WHERE conversation_id = ?")
        if since_ts is not None:
            sql += " AND created_at > ?"; params.append(since_ts)
        sql += " ORDER BY created_at ASC, command_id ASC"
        rows = self._conn.execute(sql, params).fetchall()
        seen: dict[str, dict] = {}
        for r in rows:
            cmd = r[0]
            if cmd in seen and r[6] != "primary":
                continue  # primary 행을 우선 보존
            try:
                payload_val = json.loads(r[3])
            except (TypeError, ValueError):
                payload_val = r[3]
            seen[cmd] = {
                "command_id": cmd, "source": r[1], "target": r[2], "payload": payload_val,
                "conversation_id": r[4], "created_at": r[5],
                "delivered_as": r[6], "in_reply_to": r[7],
            }
        return sorted(seen.values(), key=lambda m: (m["created_at"], m["command_id"]))
```

`dispatcher.py`의 `conversation_status`(`:819`) 근처에 추가:

```python
    def transcript(self, conversation_id: str, since_ts: str | None = None) -> dict:
        """conversation 메시지를 시간순 배열로. 영속(SQLite)이 정본 — 막 dispatch한
        메시지는 비동기 영속 지연으로 누락될 수 있어 as_of_ts 경계를 함께 반환."""
        msgs = self._persistence.fetch_transcript(conversation_id, since_ts)
        return {"conversation_id": conversation_id, "as_of_ts": _now_iso(), "messages": msgs}
```

`server.py`의 `agora.conversation_status`(`:466`) 뒤에 도구 추가:

```python
    @mcp.tool(name="agora.transcript")
    async def agora_transcript(conversation_id: str, since_ts: str | None = None) -> str:
        """Time-ordered envelope array for a conversation (SQLite is source of truth).
        since_ts: ISO timestamp — only messages created after it. Advisory (peek-grade)."""
        return json.dumps(dispatcher.transcript(conversation_id, since_ts), ensure_ascii=False)
```

주의: 테스트가 통과하려면 dispatch가 메시지를 영속해야 한다. `persist_dispatch_txn`은 `AsyncWriteQueue`를 통하므로, 테스트에서 write queue가 flush될 시간을 줘야 할 수 있다. 기존 영속 검증 테스트의 동기화 방식(예: `await write_queue.submit_transaction([])` 또는 헬퍼)을 그대로 따를 것. 동기화 훅이 없으면 `transcript` 테스트는 `fetch_transcript`를 직접 호출하는 단위 테스트로 보완.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_observability.py::test_transcript_time_ordered_and_since_filter -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/persistence.py src/agent_agora/dispatcher.py src/agent_agora/server.py tests/test_v4_observability.py
git commit -m "feat(observability): agora.transcript"
```

---

### Task 4: `agora.coverage`

**Files:**
- Modify: `src/agent_agora/dispatcher.py`, `src/agent_agora/server.py`
- Test: `tests/test_v4_observability.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.asyncio
async def test_coverage_responded_pending_expired():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"},
                         expect_result=True, deadline_ts="2000-01-01T00:00:00+00:00")
    cmd = r["command_id"]
    cov = d.coverage(cmd)
    assert cov["pending"] == ["B"] and cov["responded"] == []
    assert cov["expired"] is True and cov["deadline_ts"] == "2000-01-01T00:00:00+00:00"
    # B 회신 후
    await d.dispatch(source="B", target="A",
                     payload={"msgtype": "result", "text": "ok"}, in_reply_to=cmd)
    cov2 = d.coverage(cmd)
    assert "B" in cov2["responded"] and cov2["pending"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_observability.py::test_coverage_responded_pending_expired -v`
Expected: FAIL — `coverage` 없음

- [ ] **Step 3: 구현**

`dispatcher.py`의 `transcript` 근처에 추가(`_deadlines`는 Plan A1에서 도입됨):

```python
    def coverage(self, command_id: str) -> dict:
        """expect_result 명령의 응답 커버리지. pending=아직 미응답 target,
        responded=원래 기대했으나 응답 완료한 target, expired=deadline 초과 여부."""
        conv_id = self._conv.conv_id_of(command_id)
        if conv_id is None:
            conv_id = self._persistence.lookup_conversation_for(command_id)
        # pending: _in_flight에 남은 target
        pending: list[str] = []
        for _src, pmap in self._in_flight.items():
            tset = pmap.get(command_id)
            if tset:
                pending.extend(sorted(tset))
        deadline_ts = self._deadlines.get(command_id)
        # responded: conversation primary 참가자 중 source가 아니고 pending도 아닌 자
        responded: list[str] = []
        state = self._conv.get(conv_id) if conv_id else None
        src = self._conv.source_of(command_id) if hasattr(self._conv, "source_of") else None
        if state is not None:
            for iid, info in state["participants"].items():
                if info.get("role") == "primary" and iid != src and iid not in pending:
                    responded.append(iid)
        now = _now_iso()
        return {
            "command_id": command_id, "conversation_id": conv_id,
            "pending": pending, "responded": sorted(responded),
            "deadline_ts": deadline_ts,
            "expired": bool(deadline_ts and deadline_ts < now),
        }
```

`source_of` 헬퍼가 `ConversationStore`에 없으면, `record_command`가 채우는 `_message_source`(Explore 보고서 `conversation_store.py:24`)를 노출하는 접근자 `source_of(cmd_id)`를 `ConversationStore`에 추가:

```python
    def source_of(self, cmd_id: str) -> str | None:
        return self._message_source.get(cmd_id)
```

`server.py`에 도구 추가:

```python
    @mcp.tool(name="agora.coverage")
    async def agora_coverage(command_id: str) -> str:
        """Response coverage of an expect_result command: responded/pending/expired."""
        return json.dumps(dispatcher.coverage(command_id), ensure_ascii=False)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_observability.py::test_coverage_responded_pending_expired -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/conversation_store.py src/agent_agora/server.py tests/test_v4_observability.py
git commit -m "feat(observability): agora.coverage"
```

---

### Task 5: `agora.reply` + `_last_inbound` 추적

**Files:**
- Modify: `src/agent_agora/dispatcher.py` (`__init__`, `flush`, `reply`), `src/agent_agora/server.py`
- Test: `tests/test_v4_observability.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.asyncio
async def test_reply_autofills_from_last_inbound():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "q"}, expect_result=True)
    cmd = r["command_id"]; conv = r["conversation_id"]
    await d.flush(instance_id="B")  # B가 수신 → _last_inbound[B] 갱신
    rep = await d.reply(caller="B", payload={"msgtype": "result", "text": "a"})
    assert rep["conversation_id"] == conv
    # A 인박스에 회신 도착 + in_reply_to=cmd 로 in_flight 해제
    inbox = await d.flush(instance_id="A")
    got = [m for m in inbox if m["payload"].get("msgtype") == "result"]
    assert got and got[0]["in_reply_to"] == cmd
    assert d.in_flight_count("B") == 0

@pytest.mark.asyncio
async def test_reply_without_inbound_errors():
    d, *_ = await make_dispatcher()
    await register(d, "A")
    with pytest.raises(Exception):
        await d.reply(caller="A", payload={"msgtype": "result", "text": "x"})
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_observability.py -k reply -v`
Expected: FAIL — `reply` 없음

- [ ] **Step 3: 구현**

`dispatcher.py:84`(`_deadlines` 선언 근처)에 추가:

```python
        # instance_id -> 마지막 수신(drain)한 회신 대상 컨텍스트
        self._last_inbound: dict[str, dict[str, str]] = {}
```

`flush`(`dispatcher.py:700-707`의 results 구성 루프 근처, drained 정렬 후)에 추가 — 회신 대상이 될 최신 inbound를 기록:

```python
        # _last_inbound: 회신 컨텍스트 (primary 수신 중 created_at 최신)
        repliable = [e for e in drained if e.delivered_as == "primary"]
        if repliable:
            latest = max(repliable, key=lambda e: (e.created_at, e.id))
            self._last_inbound[instance_id] = {
                "cmd_id": latest.id, "source": latest.source,
                "conversation_id": latest.conversation_id,
            }
```

`dispatcher.py`에 메서드 추가:

```python
    async def reply(self, caller: str, payload: Any,
                    in_reply_to: str | None = None, target: str | None = None,
                    conversation_id: str | None = None) -> dict:
        """직전 수신 명령을 컨텍스트로 회신. 명시 인자가 자동충전을 덮어쓴다."""
        ctx = self._last_inbound.get(caller)
        if ctx is None and (in_reply_to is None or target is None):
            raise AgoraError("no_inbound_to_reply")
        eff_in_reply_to = in_reply_to or (ctx["cmd_id"] if ctx else None)
        eff_target = target or (ctx["source"] if ctx else None)
        eff_conv = conversation_id or (ctx["conversation_id"] if ctx else None)
        return await self.dispatch(
            source=caller, target=eff_target, payload=payload,
            in_reply_to=eff_in_reply_to, conversation_id=eff_conv,
        )
```

`AgoraError`는 이미 import됨(`dispatcher.py`). `no_inbound_to_reply` 코드 문자열은 `errors.py`에 메시지 매핑이 없어도 동작하나, 일관성 위해 `errors.py`의 코드 테이블에 한 줄 추가(있으면).

`server.py`에 도구 추가(session→instance resolve 패턴은 `agora.dispatch` 복사):

```python
    @mcp.tool(name="agora.reply")
    async def agora_reply(ctx: Context, payload: Any, in_reply_to: str | None = None,
                          target: str | None = None, conversation_id: str | None = None) -> str:
        """Reply to the most recently received command — auto-fills in_reply_to,
        target, conversation_id from your last drained inbound. Explicit args win."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        try:
            caller = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError as e:
            return _error_json(e)
        try:
            result = await dispatcher.reply(
                caller=caller, payload=payload, in_reply_to=in_reply_to,
                target=target, conversation_id=conversation_id)
            return json.dumps({"status": "ok", **result}, ensure_ascii=False)
        except (AgoraError, NotRegisteredError, ValueError) as e:
            return _error_json(e)
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_observability.py -k reply -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/server.py src/agent_agora/errors.py tests/test_v4_observability.py
git commit -m "feat(observability): agora.reply + _last_inbound 추적"
```

---

### Task 6: `agora.cancel`

**Files:**
- Modify: `src/agent_agora/dispatcher.py`, `src/agent_agora/server.py`
- Test: `tests/test_v4_observability.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.asyncio
async def test_cancel_recalls_unconsumed():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"}, expect_result=True)
    cmd = r["command_id"]
    res = await d.cancel(caller="A", command_id=cmd)
    assert res["cancelled"] == ["B"]
    # B 인박스가 비었다 (회수됨)
    inbox = await d.flush(instance_id="B")
    assert all(m["command_id"] != cmd for m in inbox)
    assert d.in_flight_count("B") == 0

@pytest.mark.asyncio
async def test_cancel_already_consumed_is_noop():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B",
                         payload={"msgtype": "task", "text": "x"}, expect_result=True)
    cmd = r["command_id"]
    await d.flush(instance_id="B")  # 이미 소비
    res = await d.cancel(caller="A", command_id=cmd)
    assert res["already_consumed"] == ["B"] and res["cancelled"] == []

@pytest.mark.asyncio
async def test_cancel_non_source_denied():
    d, *_ = await make_dispatcher()
    await register(d, "A"); await register(d, "B")
    r = await d.dispatch(source="A", target="B", payload={"msgtype": "task", "text": "x"},
                         expect_result=True)
    with pytest.raises(Exception):
        await d.cancel(caller="B", command_id=r["command_id"])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_v4_observability.py -k cancel -v`
Expected: FAIL — `cancel` 없음

- [ ] **Step 3: 구현**

`dispatcher.py`에 메서드 추가:

```python
    async def cancel(self, caller: str, command_id: str) -> dict:
        """발신자가 아직 소비되지 않은 in-flight 명령을 회수한다.
        caller가 원 source가 아니면 거부. 큐에서 envelope 제거 + in_flight/_deadlines 정리."""
        src = self._conv.source_of(command_id)
        if src is None:
            src = self._persistence.lookup_source_for(command_id)
        if src is None:
            raise AgoraError("unknown_command", detail=command_id)
        if src != caller:
            raise AgoraError("not_command_owner", detail=command_id)
        cancelled: list[str] = []
        already: list[str] = []
        async with self._lock:
            # in_flight에 남은 target은 후보. 큐에 envelope이 남아 있으면 회수, 없으면 already_consumed.
            pmap = self._in_flight.get(caller, {})
            targets = sorted(pmap.get(command_id, set()))
            for t in targets:
                q = self._queues.get(t, [])
                idx = next((i for i, e in enumerate(q) if e.id == command_id), None)
                if idx is not None:
                    q.pop(idx)
                    cancelled.append(t)
                else:
                    already.append(t)
            # in_flight/_deadlines 정리 (회수·소비 불문 — 회신 의무 종료)
            pmap.pop(command_id, None)
            self._deadlines.pop(command_id, None)
        # 회수된 메시지 drop 마킹 (best-effort)
        if cancelled:
            now = _now_iso()
            stmts = [("UPDATE messages SET drained_at=?, drop_reason='manual' "
                      "WHERE command_id=? AND target=?", (now, command_id, t))
                     for t in cancelled]
            try:
                await self._write_queue.submit_transaction(stmts)
            except Exception:
                pass
        return {"command_id": command_id, "cancelled": cancelled, "already_consumed": already}
```

`server.py`에 도구 추가(reply와 동일 resolve 패턴):

```python
    @mcp.tool(name="agora.cancel")
    async def agora_cancel(ctx: Context, command_id: str) -> str:
        """Recall an in-flight command you sent that hasn't been consumed yet.
        Already-consumed targets are reported, not recalled. Caller must be the sender."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        try:
            caller = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError as e:
            return _error_json(e)
        try:
            return json.dumps(await dispatcher.cancel(caller=caller, command_id=command_id),
                              ensure_ascii=False)
        except (AgoraError, NotRegisteredError, ValueError) as e:
            return _error_json(e)
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_v4_observability.py -k cancel -v`
Expected: PASS

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `python -m pytest tests/ -q`
Expected: 회귀 없음

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/server.py tests/test_v4_observability.py
git commit -m "feat(observability): agora.cancel"
```

---

## Self-Review 메모

- spec §4 A-1=Task1, A-3=Task2, A-4=Task3, A-5=Task4, A-6=Task5, A-7=Task6. 전부 커버.
- 타입 일관성: `coverage`/`cancel`이 `_deadlines`(Plan A1), `_conv.source_of`(Task4에서 추가)를 사용. Task4가 `source_of`를 도입하므로 Task6보다 먼저 머지돼야 함 — 순서 유지.
- `cancel`의 owner 검사는 `source_of`(in-memory) → `lookup_source_for`(SQLite 폴백). Task4의 `source_of` 의존.
- `_last_inbound`는 primary 수신만 회신 대상으로 — cc/subscribed는 회신 의무 없음(설계 일치).
- 잠재 리스크: dispatch 영속이 비동기라 transcript 테스트의 타이밍. Step3 주의문대로 기존 동기화 방식 따를 것.
