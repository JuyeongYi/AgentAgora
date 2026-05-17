# 스키마 라이프사이클 ref-counting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스키마를 등록·구독한 인스턴스·봇이 전부 사라지면 그 스키마를 자동 해제하는 reference counting을 신설한다.

**Architecture:** `SchemaRegistry`에 holder 집합(`_refs`)과 permanent 표시(`_permanent`)를 추가한다. 등록자(`register`의 `registered_by`)와 구독자(`acquire_ref`)가 ref를 보유하고, holder가 사라질 때(`release_holder`) 마지막 ref가 빠지면 스키마를 제거한다. 빌트인(jsonl 로드, `registered_by=None`)은 permanent. 같은 이름 다른 body 충돌은 `Dispatcher.system_notify`로 등록 시도자에게 통지한다. 단일 플랜 — 6개 태스크를 순서대로.

**Tech Stack:** Python 3.13, pytest, jsonschema. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 진단은 무시(pytest 정답).

spec: `docs/superpowers/specs/2026-05-17-schema-lifecycle-refcounting-design.md`.

**용어:** spec의 "holder"는 `SchemaRegistry.register`의 기존 `registered_by` 매개변수다 — 신규 매개변수를 만들지 않고 이를 ref holder로 쓴다.

---

### Task 1: `SchemaRegistry` ref-counting API

**Files:**
- Modify: `src/agent_agora/schemas.py`
- Test: `tests/test_schema_refcounting.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_schema_refcounting.py` 생성:

```python
"""SchemaRegistry reference-counting (schema lifecycle spec)."""
from __future__ import annotations

import pytest

from agent_agora.errors import AgoraError
from agent_agora.schemas import SchemaRegistry

_BODY = {"type": "object", "properties": {"msgtype": {"const": "s"}}}
_BODY2 = {"type": "object", "properties": {"msgtype": {"const": "s"}, "x": {"type": "string"}}}


def _reg(r: SchemaRegistry, name="s", body=None, holder=None):
    return r.register(name, body or _BODY, kind="bot-task", purpose="p",
                      registered_by=holder)


def test_register_with_holder_creates_refset():
    r = SchemaRegistry()
    _reg(r, holder="A")
    assert r.get("s") is not None
    assert r.refs_of("s") == {"A"}


def test_second_same_body_register_adds_holder():
    r = SchemaRegistry()
    _reg(r, holder="A")
    _reg(r, holder="B")
    assert r.refs_of("s") == {"A", "B"}


def test_acquire_ref_adds_subscriber():
    r = SchemaRegistry()
    _reg(r, holder="A")
    r.acquire_ref("s", "C")
    assert r.refs_of("s") == {"A", "C"}


def test_release_holder_keeps_schema_while_refs_remain():
    r = SchemaRegistry()
    _reg(r, holder="A")
    r.acquire_ref("s", "B")
    assert r.release_holder("A") == []
    assert r.get("s") is not None
    assert r.refs_of("s") == {"B"}


def test_release_last_holder_unregisters_schema():
    r = SchemaRegistry()
    _reg(r, holder="A")
    released = r.release_holder("A")
    assert released == ["s"]
    assert r.get("s") is None
    assert r.validator("s") is None


def test_holder_none_is_permanent_and_never_released():
    r = SchemaRegistry()
    _reg(r, holder=None)  # builtin-style
    assert r.release_holder("anything") == []
    assert r.get("s") is not None
    # acquire_ref / register on a permanent schema is a no-op
    r.acquire_ref("s", "X")
    assert r.refs_of("s") == set()


def test_different_body_same_name_raises_immutable():
    r = SchemaRegistry()
    _reg(r, holder="A")
    with pytest.raises(AgoraError) as ei:
        _reg(r, body=_BODY2, holder="B")
    assert ei.value.code == "schema_immutable"
    assert r.get("s").body == _BODY


def test_release_holder_returns_only_emptied_schemas():
    r = SchemaRegistry()
    _reg(r, name="s1", holder="A")
    _reg(r, name="s2", holder="A")
    r.acquire_ref("s2", "B")
    released = r.release_holder("A")
    assert released == ["s1"]  # s2 still held by B
    assert r.get("s1") is None and r.get("s2") is not None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_schema_refcounting.py -q`
Expected: FAIL — `refs_of`/`acquire_ref`/`release_holder` 미정의.

- [ ] **Step 3: SchemaRegistry에 ref-counting 추가**

`src/agent_agora/schemas.py`의 `SchemaRegistry`를 수정한다.

`__init__`에 상태 추가:

```python
    def __init__(self) -> None:
        self._entries: dict[str, SchemaEntry] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        self._refs: dict[str, set[str]] = {}      # name -> holder ids (ref-counted)
        self._permanent: set[str] = set()         # 해제 불가 스키마 이름
        self._lock = threading.Lock()
```

`register`의 `with self._lock:` 블록을 교체 — 같은 body idempotent 시 holder를 refset에 추가, 신규 등록 시 permanent/refset 분기:

```python
        with self._lock:
            existing = self._entries.get(name)
            if existing is not None:
                if existing.body != body:
                    raise AgoraError("schema_immutable", name=name)
                # same body — idempotent. ref-counted 스키마면 holder 추가.
                if registered_by is not None and name not in self._permanent:
                    self._refs.setdefault(name, set()).add(registered_by)
                return existing
            validator = Draft202012Validator(body)
            entry = SchemaEntry(
                name=name, body=body, kind=kind, purpose=purpose,
                registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                registered_by=registered_by,
            )
            self._entries[name] = entry
            self._validators[name] = validator
            if registered_by is None:
                self._permanent.add(name)
            else:
                self._refs[name] = {registered_by}
            return entry
```

클래스에 신규 메서드 3개 추가 (`list_all` 다음 적당한 위치):

```python
    def refs_of(self, name: str) -> set[str]:
        """name의 현재 ref holder 집합 (조회용). permanent/미존재면 빈 집합."""
        with self._lock:
            return set(self._refs.get(name, set()))

    def acquire_ref(self, name: str, holder: str) -> None:
        """구독자 ref 획득. name이 미존재거나 permanent면 no-op."""
        with self._lock:
            if name not in self._entries or name in self._permanent:
                return
            self._refs.setdefault(name, set()).add(holder)

    def release_holder(self, holder: str) -> list[str]:
        """holder의 모든 ref를 해제한다. refset이 빈 non-permanent 스키마를
        등록 해제하고, 해제된 스키마 이름 리스트를 반환한다."""
        released: list[str] = []
        with self._lock:
            for name in list(self._refs.keys()):
                refs = self._refs[name]
                refs.discard(holder)
                if not refs:
                    self._entries.pop(name, None)
                    self._validators.pop(name, None)
                    self._refs.pop(name, None)
                    released.append(name)
        return released
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_schema_refcounting.py -q`
Expected: 8개 PASS.

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS — 기존 `register` 호출처는 모두 `registered_by` 미지정(None) 또는 지정 그대로라 동작 불변.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/schemas.py tests/test_schema_refcounting.py
git commit -m "feat: SchemaRegistry ref-counting (refs·permanent·release_holder)"
```

---

### Task 2: `schema_conflict` 시스템 스키마 + 런타임 스키마 복원 중단

`schema_conflict`는 시스템 스키마다 — 사용자 편집 대상인 `schemas.jsonl`에 두지 않고 코드 상수로 두어 startup에서 프로그래밍으로 등록한다(단일 진실 소스). 동시에 startup의 `restore_schemas()` 호출을 제거한다(spec §3 재시작 동작).

**Files:**
- Modify: `src/agent_agora/schemas.py`
- Modify: `src/agent_agora/__main__.py`
- Test: `tests/test_schema_refcounting.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_schema_refcounting.py`에 추가:

```python
from agent_agora.schemas import SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY


def test_schema_conflict_constant_has_msgtype_property():
    props = SCHEMA_CONFLICT_BODY.get("properties", {})
    assert "msgtype" in props
    assert SCHEMA_CONFLICT_NAME == "schema_conflict"


def test_schema_conflict_registers_as_permanent():
    r = SchemaRegistry()
    r.register(SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY,
               kind="conversation", purpose="schema name conflict notice")
    assert r.get(SCHEMA_CONFLICT_NAME) is not None
    assert r.release_holder("anyone") == []  # permanent
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_schema_refcounting.py -k schema_conflict -q`
Expected: FAIL — `SCHEMA_CONFLICT_NAME` 미정의.

- [ ] **Step 3: schemas.py에 상수 추가**

`src/agent_agora/schemas.py`의 `BUNDLED_DEFAULT_SCHEMAS` 정의 앞에 추가:

```python
SCHEMA_CONFLICT_NAME = "schema_conflict"
SCHEMA_CONFLICT_BODY: dict[str, Any] = {
    "type": "object",
    "required": ["msgtype", "schema_name", "reason", "ts"],
    "properties": {
        "msgtype": {"type": "string", "const": "schema_conflict"},
        "schema_name": {"type": "string"},
        "reason": {"type": "string"},
        "attempted_by": {"type": "string"},
        "ts": {"type": "string", "format": "date-time"},
    },
    "additionalProperties": False,
}
```

- [ ] **Step 4: __main__.py — restore_schemas 제거 + schema_conflict 등록**

`src/agent_agora/__main__.py`의 스키마 로드 블록(현 88~106행)을 교체한다. `restore_schemas()` 루프를 삭제하고, jsonl 로드 후 `schema_conflict`를 permanent로 등록한다:

```python
    # Schema 로드: (1) .agentagora/schemas.jsonl 빌트인 로드, (2) schema_conflict 시스템 스키마.
    # 런타임 등록 스키마는 복원하지 않는다 — ref-counting 하에서 holder가 죽어 고아 ref가
    # 되므로(spec §3 재시작 동작). 봇·워커는 재접속 시 스스로 재등록한다.
    from agent_agora.schemas import SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY
    schema_registry = SchemaRegistry()
    schemas_file = ensure_schemas_file(agora_dir / "schemas.jsonl")
    try:
        load_schemas_into(schema_registry, schemas_file)
    except Exception as e:  # noqa: BLE001
        print(f"[agora] WARNING: {schemas_file} 로드 중 일부 schema 충돌: {e}", file=sys.stderr)
    # schema_conflict — 시스템 스키마, permanent (registered_by 미지정)
    schema_registry.register(
        SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY,
        kind="conversation", purpose="스키마 이름 충돌 통지")
    # 빌트인 schema를 SQLite에도 영속 (idempotent, audit용)
    for entry in schema_registry.list_all():
        persistence.save_schema(entry.name, entry.body, kind=entry.kind,
                                purpose=entry.purpose, registered_by=entry.registered_by)
```

기존 `for row in persistence.restore_schemas():` 루프 전체를 삭제한다. `persistence.restore_schemas` 메서드 자체는 남겨둔다(사용처만 제거 — 다른 곳에서 안 쓰면 dead지만 audit 조회용으로 보존).

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_schema_refcounting.py -q`
Expected: 10개 PASS.

- [ ] **Step 6: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS. `restore_schemas` 동작에 의존하던 테스트가 있으면(서버 재시작 후 스키마 잔존을 단정) 실패한다 — 그 테스트는 런타임 스키마가 재시작 후 사라지는 새 동작에 맞춰 갱신한다. 빌트인 6종은 jsonl에서 매번 로드되므로 영향 없다.

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/schemas.py src/agent_agora/__main__.py tests/test_schema_refcounting.py
git commit -m "feat: schema_conflict 시스템 스키마 + 런타임 스키마 복원 중단"
```

---

### Task 3: `Dispatcher.system_notify`

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_dispatcher.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_v3_dispatcher.py`에 추가 (파일 상단에 `setup` fixture·`tany` 이미 존재):

```python
@pytest.mark.asyncio
async def test_system_notify_enqueues_and_wakes(setup):
    _, _, dispatcher = setup
    await dispatcher.system_notify("Inst3", {
        "msgtype": "schema_conflict", "schema_name": "s",
        "reason": "different body", "ts": "2026-05-17T00:00:00+00:00"})
    drained = await dispatcher.flush("Inst3")
    assert len(drained) == 1
    assert drained[0]["payload"]["msgtype"] == "schema_conflict"
    assert drained[0]["source"] == "agora-system"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_dispatcher.py::test_system_notify_enqueues_and_wakes -q`
Expected: FAIL — `system_notify` 미정의.

- [ ] **Step 3: system_notify 구현**

`src/agent_agora/dispatcher.py`의 `Dispatcher` 클래스에 메서드 추가 (`wait_notify` 다음 적당한 위치):

```python
    async def system_notify(self, target: str, payload: dict[str, Any]) -> None:
        """시스템 발신 알림을 target 인박스에 넣고 깨운다. comm-matrix·conversation·
        in_flight 머신을 우회한다 — schema 충돌 통지 등 운영 이벤트용. 영속화 안 함."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        now = _now_iso()
        env = make_envelope(
            cmd_id=str(uuid.uuid4()), source="agora-system", target=target,
            payload=payload, created_at=now, conversation_id=str(uuid.uuid4()),
            expect_result=False, delivered_as="primary", dispatch_kind="direct",
        )
        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            self._queues[target].append(env)
            self._wake(target)
```

`make_envelope`·`uuid`·`_now_iso`는 `dispatcher.py`에 이미 import/정의돼 있다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_dispatcher.py::test_system_notify_enqueues_and_wakes -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat: Dispatcher.system_notify — 시스템 발신 인박스 알림"
```

---

### Task 4: `agora.register_schema` 와이어링 — holder + 충돌 통지

**Files:**
- Modify: `src/agent_agora/server.py` (`agora.register_schema` 핸들러, 현 70~84행)
- Test: `tests/test_v4_schema_enforcement.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_v4_schema_enforcement.py`에 추가. 파일 기존 패턴(서버 앱 fixture·`_tool`·`_FakeCtx`)을 따른다 — 없으면 `tests/test_v4_comm_matrix.py`의 `cm_app`/`_tool`/`_FakeCtx` 패턴을 참고해 동일 구조의 fixture를 만든다. 핵심 단언:

```python
@pytest.mark.asyncio
async def test_register_schema_holds_ref_for_caller(schema_app):
    """register_schema는 호출자 instance_id를 holder로 ref를 잡는다."""
    mcp, dispatcher, schema_registry = schema_app
    body = {"type": "object", "properties": {"msgtype": {"const": "custom_a"}}}
    r = json.loads(await _tool(mcp, "agora.register_schema")(
        _FakeCtx("sess-Inst1"), name="custom_a", body=body,
        kind="bot-task", purpose="p"))
    assert r["status"] == "ok"
    assert schema_registry.refs_of("custom_a") == {"Inst1"}


@pytest.mark.asyncio
async def test_register_schema_conflict_dispatches_notice(schema_app):
    """같은 이름 다른 body → schema_immutable 동기 에러 + schema_conflict 통지."""
    mcp, dispatcher, schema_registry = schema_app
    b1 = {"type": "object", "properties": {"msgtype": {"const": "custom_b"}}}
    b2 = {"type": "object", "properties": {"msgtype": {"const": "custom_b"},
                                           "x": {"type": "string"}}}
    await _tool(mcp, "agora.register_schema")(
        _FakeCtx("sess-Inst1"), name="custom_b", body=b1, kind="bot-task", purpose="p")
    r = json.loads(await _tool(mcp, "agora.register_schema")(
        _FakeCtx("sess-Inst2"), name="custom_b", body=b2, kind="bot-task", purpose="p"))
    assert "error" in r and "schema_immutable" in r["error"]
    drained = await dispatcher.flush("Inst2")
    assert any(d["payload"]["msgtype"] == "schema_conflict" for d in drained)
```

`schema_app` fixture는 `Inst1`·`Inst2`를 instance_registry에 등록한 상태로 `(mcp, dispatcher, schema_registry)`를 yield한다 — `cm_app` fixture 구조를 복제하되 `comm_matrix` 대신 `schema_registry`를 노출한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_schema_enforcement.py -k "register_schema_holds_ref or register_schema_conflict" -q`
Expected: FAIL — 현 `register_schema`는 `ctx`를 안 받고 holder도 안 잡으며 충돌 통지도 안 한다.

- [ ] **Step 3: register_schema 핸들러 재작성**

`src/agent_agora/server.py`의 `agora_register_schema`를 교체한다:

```python
    @mcp.tool(name="agora.register_schema")
    async def agora_register_schema(
        ctx: Context,
        name: str,
        body: dict,
        kind: Literal["conversation", "bot-task"],
        purpose: str,
    ) -> str:
        """Register a schema. Immutable — 동일 이름 다른 body는 거부.
        body에 msgtype property 필수 (결정 20). 호출자가 ref holder가 된다."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        # 호출자 instance_id 해석 — 워커/봇 모두 허용, 미등록이면 session_id를 holder로.
        try:
            holder = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError:
            try:
                holder = bot_registry.resolve_session(session_id).instance_id
            except NotRegisteredError:
                holder = session_id
        try:
            schema_registry.register(name, body, kind=kind, purpose=purpose,
                                     registered_by=holder)
            persistence.save_schema(name, body, kind=kind, purpose=purpose,
                                    registered_by=holder)
        except AgoraError as e:
            if e.code == "schema_immutable":
                await dispatcher.system_notify(holder, {
                    "msgtype": "schema_conflict", "schema_name": name,
                    "reason": str(e), "attempted_by": holder,
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "ok", "name": name, "kind": kind})
```

server.py 파일 상단 import에 `import datetime`이 있는지 확인하고 없으면 추가한다(현재 server.py는 `time`은 import하지만 `datetime`은 import하지 않을 수 있다). `NotRegisteredError`는 server.py가 이미 import한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_schema_enforcement.py -k "register_schema" -q`
Expected: PASS

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS. `register_schema`에 `ctx` 인자가 추가됐으므로, 이 도구를 호출하는 기존 테스트가 있으면 `_FakeCtx(...)`를 첫 인자로 넘기도록 갱신한다.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_schema_enforcement.py
git commit -m "feat: register_schema — holder ref + 충돌 system_notify"
```

---

### Task 5: `agora.register_bot` · `agora.unregister` 와이어링

**Files:**
- Modify: `src/agent_agora/server.py` (`agora.register_bot` 70~201행 부근, `agora.unregister` 203~211행 부근)
- Test: `tests/test_v4_bots.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_v4_bots.py`에 추가 (파일의 기존 봇 등록 fixture·헬퍼를 따른다):

```python
@pytest.mark.asyncio
async def test_bot_inline_schema_holds_ref(bot_app):
    """register_bot 인라인 schemas= → 봇이 holder ref 보유."""
    mcp, dispatcher, schema_registry = bot_app
    body = {"type": "object", "properties": {"msgtype": {"const": "echo_task"}}}
    await _tool(mcp, "agora.register_bot")(
        _FakeCtx("sess-bot1"), instance_id="bot1", description="d",
        bot_mode="handler", subscribe_schemas=["echo_task"],
        schemas={"echo_task": {"kind": "bot-task", "purpose": "p", "body": body}})
    assert "bot1" in schema_registry.refs_of("echo_task")


@pytest.mark.asyncio
async def test_unregister_releases_schema_ref(bot_app):
    """봇 unregister → 그 봇이 마지막 holder면 스키마 해제."""
    mcp, dispatcher, schema_registry = bot_app
    body = {"type": "object", "properties": {"msgtype": {"const": "echo2"}}}
    await _tool(mcp, "agora.register_bot")(
        _FakeCtx("sess-bot1"), instance_id="bot1", description="d",
        bot_mode="handler", subscribe_schemas=["echo2"],
        schemas={"echo2": {"kind": "bot-task", "purpose": "p", "body": body}})
    assert schema_registry.get("echo2") is not None
    await _tool(mcp, "agora.unregister")(_FakeCtx("sess-bot1"))
    assert schema_registry.get("echo2") is None
```

`bot_app` fixture는 `(mcp, dispatcher, schema_registry)`를 yield — Task 4의 `schema_app`과 동일 구조면 재사용한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_bots.py -k "inline_schema_holds_ref or unregister_releases" -q`
Expected: FAIL.

- [ ] **Step 3: register_bot 핸들러 수정**

`src/agent_agora/server.py`의 `agora_register_bot`에서:

(a) 봇 재등록 시 옛 ref 해제 — `session_id` 해석 직후, 검증 블록 진입 전에 추가:

```python
        # 봇 재등록이면 옛 스키마 ref를 먼저 해제 (새 inline/subscribe로 재획득).
        try:
            prior = bot_registry.resolve_instance_id(instance_id)
            schema_registry.release_holder(prior.instance_id)
        except NotRegisteredError:
            pass
```

(b) 인라인 schemas 등록에 `registered_by` 전달 — 현재 `register(..., registered_by=instance_id)`는 이미 그렇게 돼 있다(server.py 기존 코드 확인). 그대로 둔다.

(c) 인라인 schemas 사전 검증 루프의 충돌을 통지한다. `AgoraError`는 충돌 스키마
이름을 속성으로 보존하지 않으므로(`code`만 노출), `except`에서 잡지 말고 **충돌을
감지한 지점**에서 통지한다. 현 사전 검증 루프(server.py ~161~167행)를 다음으로 교체:

```python
            # (1) inline schemas 사전 검증 — diff preflight (§3.3, §9.6)
            for name, defn in schemas.items():
                if defn.get("kind") != "bot-task":
                    raise AgoraError("schema_kind_not_bot_task", name=name)
                existing = schema_registry.get(name)
                if existing is not None and existing.body != defn.get("body"):
                    await dispatcher.system_notify(instance_id, {
                        "msgtype": "schema_conflict", "schema_name": name,
                        "reason": f"schema '{name}' already registered with a different body",
                        "attempted_by": instance_id,
                        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                    raise AgoraError("schema_immutable", name=name)
```

통지를 `raise` 직전에 수행하므로 동기 에러 응답과 인박스 통지가 모두 발생한다.
(`import datetime`은 Task 4 Step 3에서 이미 server.py에 추가돼 있다.)

(d) 구독 schema에 ref 획득 — `bot_registry.register(...)` 호출 직후 추가:

```python
            for s in info.subscribe_schemas:
                schema_registry.acquire_ref(s, instance_id)
```

- [ ] **Step 4: unregister 핸들러 수정**

`agora_unregister`에 `release_holder`를 추가한다:

```python
    @mcp.tool(name="agora.unregister")
    async def agora_unregister(ctx: Context) -> str:
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        # 해제 전에 holder id를 잡아 스키마 ref를 해제한다.
        for reg in (instance_registry, bot_registry):
            try:
                holder = reg.resolve_session(session_id).instance_id
                schema_registry.release_holder(holder)
            except NotRegisteredError:
                pass
        instance_registry.unregister_session(session_id)
        bot_registry.unregister_session(session_id)
        return json.dumps({"status": "ok"})
```

- [ ] **Step 5: 테스트 통과 + 전체 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_bots.py -q`
Expected: PASS
Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_bots.py
git commit -m "feat: register_bot·unregister — 스키마 ref 획득·해제 와이어링"
```

---

### Task 6: dead sweep 와이어링

스윕으로 제거되는 워커·봇의 스키마 ref를 해제한다.

**Files:**
- Modify: `src/agent_agora/dispatcher.py` (`dead_session_sweep`, `dead_bot_sweep`)
- Test: `tests/test_v3_recovery.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_v3_recovery.py`에 추가. 죽은 봇 스윕 후 그 봇만 등록한 스키마가 해제되는지 검증한다. 파일의 기존 dispatcher 셋업 패턴을 따르되, 핵심:

```python
@pytest.mark.asyncio
async def test_dead_bot_sweep_releases_schema_refs(tmp_path):
    """dead_bot_sweep — 스윕된 봇이 마지막 holder인 스키마가 해제된다."""
    import datetime
    from agent_agora.schemas import SchemaRegistry
    from agent_agora.bot_registry import BotRegistry
    from agent_agora.registry import InstanceRegistry
    from agent_agora.persistence import Persistence, AsyncWriteQueue
    from agent_agora.comm_matrix import CommMatrix
    from agent_agora.dispatcher import Dispatcher

    schema_registry = SchemaRegistry()
    body = {"type": "object", "properties": {"msgtype": {"const": "x"}}}
    schema_registry.register("x", body, kind="bot-task", purpose="p",
                             registered_by="bot1")
    bot_registry = BotRegistry()
    bot_registry.register("sess-bot1", "bot1", "d", "handler",
                          subscribe_schemas=("x",))
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        d = Dispatcher(InstanceRegistry(), persistence, queue,
                       schema_registry=schema_registry, bot_registry=bot_registry,
                       comm_matrix=CommMatrix(),
                       dead_session_timeout_ms=0)
        # registered_at이 즉시 cutoff 이전이 되도록 timeout 0
        removed = d.dead_bot_sweep()
        assert "bot1" in removed
        assert schema_registry.get("x") is None
```

`dead_session_timeout_ms=0`이면 모든 봇이 즉시 sweep 대상이 된다(`registered_at < now`).

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_recovery.py::test_dead_bot_sweep_releases_schema_refs -q`
Expected: FAIL — sweep이 스키마 ref를 해제하지 않아 `get("x")`가 여전히 non-None.

- [ ] **Step 3: 스윕에 release_holder 추가**

`src/agent_agora/dispatcher.py`의 `dead_session_sweep`과 `dead_bot_sweep`에서, `removed` 리스트를 반환하기 직전에 각 제거 id의 스키마 ref를 해제한다.

`dead_session_sweep` — `return removed` 직전:

```python
        for iid in removed:
            self._schema_registry.release_holder(iid)
        return removed
```

`dead_bot_sweep` — `return removed` 직전에 동일하게:

```python
        for iid in removed:
            self._schema_registry.release_holder(iid)
        return removed
```

`Dispatcher`는 `self._schema_registry`를 `__init__`에서 이미 보유한다.

- [ ] **Step 4: 테스트 통과 + 전체 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v3_recovery.py -q`
Expected: PASS
Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_recovery.py
git commit -m "feat: dead sweep — 스윕된 워커·봇의 스키마 ref 해제"
```

---

## 완료 기준

- `SchemaRegistry`가 `refs_of`·`acquire_ref`·`release_holder`를 갖고, 마지막 ref 해제 시 스키마를 등록 해제한다.
- 빌트인·`schema_conflict`는 permanent — 절대 해제 안 됨.
- 같은 이름 다른 body 충돌 시 등록 시도자 인박스에 `schema_conflict` 통지가 도착한다.
- `register_bot`(inline+subscribe)·`register_schema`·`unregister`·dead sweep이 ref를 정확히 획득·해제한다.
- 재시작 시 런타임 스키마를 복원하지 않는다(`restore_schemas()` 호출 제거).
- 전체 테스트 스위트 통과.
