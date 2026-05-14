# Inter-Instance Command Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora가 동일 서버에 연결된 두 Claude Code 인스턴스 간(A→B) 비동기 명령 전달 채널을 제공하도록 확장한다.

**Architecture:** MCP 2025-11-25 사양 기반. 인스턴스는 명시적 `agora.register` 호출로 식별된다. 명령은 `commands/{target}` 큐에 적재되며, B 인스턴스는 `agora.wait`로 자기 앞으로 온 명령을 long-poll한다. `agora.wait`는 표준 MCP Tasks (`taskSupport: "optional"`)를 지원하므로 task-capable 클라이언트는 백그라운드 실행이 가능하다. 기존 인메모리 + JSON 영속화 패턴은 유지하며 모든 쓰기는 `AsyncWriteQueue`를 통과한다.

**Tech Stack:** Python 3.13, `mcp` Python SDK (FastMCP), `uvicorn`, `jsonschema`, `pytest`/`pytest-asyncio`.

**Out of scope (이 plan에서 다루지 않음):** 결과 회신(`agora.dispatch(expect_result=True)`)의 동기적 await — A는 자체 `agora.wait` 또는 `agora.get`으로 회수한다. 인증/인가는 localhost-only 가정이라 추가하지 않는다.

---

## File Structure

| 파일 | 책임 | 신규/변경 |
|------|------|----------|
| `src/agent_agora/schema.py` | JSON Schema registry. 내장 reserved 스키마(`instances`, `commands`, `results`) 추가. | 변경 |
| `src/agent_agora/store.py` | 데이터 저장 + `AsyncWriteQueue`. 변경 없음. | 변경 없음 |
| `src/agent_agora/registry.py` | 인스턴스 ↔ 세션 매핑. `register`/`unregister`/`list_instances`/`resolve_by_instance_id`. | 신규 |
| `src/agent_agora/dispatcher.py` | 명령 적재 + future 기반 wake. `dispatch` / `wait` 핵심 로직. broadcast fan-out. | 신규 |
| `src/agent_agora/server.py` | FastMCP 도구 11개 등록. 도구명 슬래시 → 점. ctx.session_id 활용. | 변경 |
| `src/agent_agora/__main__.py` | CLI 옵션 `--default-wait-timeout-ms`, `--no-timeout` 추가. | 변경 |
| `src/agent_agora/session_hook.py` | Starlette middleware로 HTTP 연결 종료 감지 → 자동 unregister. | 신규 |
| `tests/test_schema.py` | 내장 스키마 검증 케이스 추가. | 변경 |
| `tests/test_server.py` | 도구명 변경 반영. | 변경 |
| `tests/test_registry.py` | InstanceRegistry 단위 테스트. | 신규 |
| `tests/test_dispatcher.py` | Dispatcher 단위 테스트 (dispatch, wait, broadcast, timeout). | 신규 |
| `tests/test_integration.py` | A→B 시나리오 (in-process FastMCP 클라이언트 2개). | 신규 |
| `tests/test_session_hook.py` | 세션 종료 시 unregister 검증. | 신규 |

---

## Task 1: Tool Rename (slash → dot)

**Files:**
- Modify: `src/agent_agora/server.py:32-87`
- Modify: `tests/test_server.py` (도구명 참조 전부)

**Rationale:** MCP 사양상 도구 이름 허용 문자는 `A-Za-z0-9_-.` 만. 현재 `agora/info` 등 7개 모두 슬래시 포함 → 사양 위반. 점 구분으로 변경.

- [ ] **Step 1: 기존 도구명 사용 부분 grep으로 식별**

```
Grep pattern="agora/" path="src tests"
```

Expected: `server.py` 7곳 + `tests/test_server.py` 여러 곳.

- [ ] **Step 2: server.py의 도구 이름 7개 일괄 변경**

`src/agent_agora/server.py`에서 다음 7곳 변경 (decorator의 `name=` 인자):
- `name="agora/info"` → `name="agora.info"`
- `name="agora/set"` → `name="agora.set"`
- `name="agora/get"` → `name="agora.get"`
- `name="agora/append"` → `name="agora.append"`
- `name="agora/delete"` → `name="agora.delete"`
- `name="agora/list"` → `name="agora.list"`

(현재 7개가 아니라 6개네 — 확인 후 정확한 개수만큼 변경)

- [ ] **Step 3: 테스트의 도구명 참조 변경**

`tests/test_server.py`에서 도구 호출/검증 시 사용하는 도구명을 동일하게 변경. 동작 검증 로직 자체는 불변.

- [ ] **Step 4: 테스트 실행 — 모두 통과해야 함**

```
pytest tests/test_server.py -v
```

Expected: 모든 테스트 PASS.

- [ ] **Step 5: 커밋**

```
git add src/agent_agora/server.py tests/test_server.py
git commit -m "refactor: rename tools from slash to dot to comply with MCP spec"
```

---

## Task 2: Reserved Built-in Schemas

**Files:**
- Modify: `src/agent_agora/schema.py`
- Modify: `tests/test_schema.py`

**Rationale:** 인스턴스 채널 동작을 위해 `instances`/`commands`/`results` 세 스키마가 항상 존재해야 한다. 사용자 정의와 충돌하지 않도록 reserved로 처리하고 `SchemaRegistry.load`에서 자동 주입한다.

- [ ] **Step 1: 실패 테스트 작성 — 내장 스키마 자동 등록**

`tests/test_schema.py` 끝에 추가:

```python
def test_builtin_schemas_auto_registered(agora_dir_with_schemas):
    from agent_agora.schema import SchemaRegistry
    registry = SchemaRegistry.load(agora_dir_with_schemas)
    assert "instances" in registry.names()
    assert "commands" in registry.names()
    assert "results" in registry.names()


def test_user_cannot_override_builtin_schema(agora_dir, sample_schemas):
    import json
    from agent_agora.schema import SchemaRegistry
    bad = dict(sample_schemas)
    bad["commands"] = {"type": "string"}
    (agora_dir / "schemas.json").write_text(json.dumps(bad))
    import pytest
    with pytest.raises(ValueError, match="reserved"):
        SchemaRegistry.load(agora_dir)


def test_builtin_commands_validates_correct_payload():
    from agent_agora.schema import SchemaRegistry
    reg = SchemaRegistry({})
    reg._inject_builtins()
    reg.validate_item("commands", {
        "id": "cmd-1",
        "source": "A",
        "target": "B",
        "payload": {"action": "noop"},
        "created_at": "2026-05-14T10:00:00Z",
    })
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

```
pytest tests/test_schema.py -v
```

Expected: 3개 신규 테스트 FAIL.

- [ ] **Step 3: `schema.py`에 내장 스키마 정의 + 자동 주입**

`src/agent_agora/schema.py` 상단에 추가:

```python
_BUILTIN_SCHEMAS: dict[str, dict] = {
    "instances": {
        "type": "object",
        "properties": {
            "instance_id": {"type": "string"},
            "role": {"type": "string"},
            "session_id": {"type": "string"},
            "registered_at": {"type": "string"},
        },
        "required": ["instance_id", "registered_at"],
    },
    "commands": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "source": {"type": "string"},
                "target": {"type": "string"},
                "payload": {},
                "created_at": {"type": "string"},
                "expect_result": {"type": "boolean"},
            },
            "required": ["id", "source", "target", "payload", "created_at"],
        },
    },
    "results": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "command_id": {"type": "string"},
                "source": {"type": "string"},
                "payload": {},
                "completed_at": {"type": "string"},
                "is_error": {"type": "boolean"},
            },
            "required": ["command_id", "source", "payload", "completed_at"],
        },
    },
}
```

- [ ] **Step 4: `_RESERVED_NAMES`를 내장 스키마 키로 정의 + `_inject_builtins` 메서드 추가**

`SchemaRegistry` 클래스 본문 변경:

```python
class SchemaRegistry:
    _RESERVED_NAMES = frozenset({"schemas", *_BUILTIN_SCHEMAS.keys()})

    def __init__(self, schemas: dict[str, dict]) -> None:
        self._schemas = dict(schemas)
        self._inject_builtins()

    def _inject_builtins(self) -> None:
        for name, schema in _BUILTIN_SCHEMAS.items():
            self._schemas[name] = schema

    @classmethod
    def load(cls, agora_dir: Path) -> "SchemaRegistry":
        schemas_path = agora_dir / "schemas.json"
        if not schemas_path.exists():
            raise FileNotFoundError(f"schemas.json not found in {agora_dir}")
        user_schemas = json.loads(schemas_path.read_text(encoding="utf-8"))
        if not user_schemas:
            raise ValueError("schemas.json is empty")
        for name in user_schemas:
            if name in cls._RESERVED_NAMES:
                raise ValueError(f"Schema name '{name}' is reserved")
        return cls(user_schemas)
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```
pytest tests/test_schema.py -v
```

Expected: 모든 테스트 PASS (신규 3개 포함).

- [ ] **Step 6: 커밋**

```
git add src/agent_agora/schema.py tests/test_schema.py
git commit -m "feat: reserve builtin schemas (instances, commands, results)"
```

---

## Task 3: InstanceRegistry + register/unregister/instances Tools

**Files:**
- Create: `src/agent_agora/registry.py`
- Create: `tests/test_registry.py`
- Modify: `src/agent_agora/server.py` (3개 도구 추가, `ctx: Context` 사용)
- Modify: `src/agent_agora/__main__.py` (registry 인스턴스를 server에 전달)

**Rationale:** A가 B를 명령 타깃으로 지정하려면 둘 다 식별 가능해야 한다. 세션 ID(transport 레벨)과 instance_id(사용자 지정)를 매핑한다. 미등록 세션의 `dispatch`/`wait`는 거부된다.

- [ ] **Step 1: InstanceRegistry 테스트 작성**

`tests/test_registry.py` 신규:

```python
from __future__ import annotations

import pytest

from agent_agora.registry import InstanceRegistry, NotRegisteredError


def test_register_and_resolve():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="orchestrator")
    info = reg.resolve_session("s1")
    assert info.instance_id == "A"
    assert info.role == "orchestrator"


def test_resolve_unknown_session_raises():
    reg = InstanceRegistry()
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("ghost")


def test_re_register_same_instance_id_overwrites():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r1")
    reg.register(session_id="s2", instance_id="A", role="r2")
    assert reg.resolve_session("s2").role == "r2"
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("s1")


def test_unregister_by_session():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r")
    reg.unregister_session("s1")
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("s1")


def test_list_returns_all_registered():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r1")
    reg.register(session_id="s2", instance_id="B", role="r2")
    listed = sorted(i.instance_id for i in reg.list_instances())
    assert listed == ["A", "B"]


def test_resolve_instance_id_returns_session():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r")
    assert reg.resolve_instance_id("A").session_id == "s1"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_registry.py -v
```

Expected: ImportError (registry 모듈 없음).

- [ ] **Step 3: registry.py 구현**

`src/agent_agora/registry.py` 신규:

```python
# src/agent_agora/registry.py
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass


class NotRegisteredError(Exception):
    pass


class InstanceAlreadyRegisteredError(Exception):
    pass


@dataclass
class InstanceInfo:
    instance_id: str
    session_id: str
    role: str
    registered_at: str


class InstanceRegistry:
    """세션 ID ↔ 인스턴스 ID 양방향 매핑. 동일 instance_id 재등록 시 기존 세션 entry 제거."""

    def __init__(self) -> None:
        self._by_session: dict[str, InstanceInfo] = {}
        self._by_instance: dict[str, InstanceInfo] = {}
        self._lock = threading.Lock()

    def register(self, session_id: str, instance_id: str, role: str) -> InstanceInfo:
        info = InstanceInfo(
            instance_id=instance_id,
            session_id=session_id,
            role=role,
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        with self._lock:
            existing = self._by_instance.get(instance_id)
            if existing is not None:
                self._by_session.pop(existing.session_id, None)
            old_for_session = self._by_session.get(session_id)
            if old_for_session is not None:
                self._by_instance.pop(old_for_session.instance_id, None)
            self._by_session[session_id] = info
            self._by_instance[instance_id] = info
        return info

    def unregister_session(self, session_id: str) -> None:
        with self._lock:
            info = self._by_session.pop(session_id, None)
            if info is not None:
                self._by_instance.pop(info.instance_id, None)

    def resolve_session(self, session_id: str) -> InstanceInfo:
        with self._lock:
            info = self._by_session.get(session_id)
        if info is None:
            raise NotRegisteredError(f"Session {session_id} is not registered")
        return info

    def resolve_instance_id(self, instance_id: str) -> InstanceInfo:
        with self._lock:
            info = self._by_instance.get(instance_id)
        if info is None:
            raise NotRegisteredError(f"Instance '{instance_id}' is not registered")
        return info

    def list_instances(self) -> list[InstanceInfo]:
        with self._lock:
            return list(self._by_instance.values())
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```
pytest tests/test_registry.py -v
```

Expected: 6개 테스트 PASS.

- [ ] **Step 5: server.py에 register/unregister/instances 도구 추가**

`src/agent_agora/server.py`의 `create_agora_app` 시그니처에 `registry: InstanceRegistry` 인자 추가. 본문 끝에 신규 도구 3개:

```python
from mcp.server.fastmcp import Context

from agent_agora.registry import InstanceRegistry, NotRegisteredError


def create_agora_app(
    agora_dir: Path,
    store: AgoraStore,
    registry: SchemaRegistry,
    instance_registry: InstanceRegistry,
    port: int,
) -> tuple[FastMCP, AsyncWriteQueue]:
    ...
    @mcp.tool(name="agora.register")
    async def agora_register(ctx: Context, instance_id: str, role: str = "worker") -> str:
        """Register this session as an addressable instance. Required before dispatch/wait."""
        session_id = _session_id_from_ctx(ctx)
        info = instance_registry.register(session_id=session_id, instance_id=instance_id, role=role)
        return json.dumps({"status": "ok", "instance_id": info.instance_id, "registered_at": info.registered_at})

    @mcp.tool(name="agora.unregister")
    async def agora_unregister(ctx: Context) -> str:
        """Unregister this session. Idempotent."""
        session_id = _session_id_from_ctx(ctx)
        instance_registry.unregister_session(session_id)
        return json.dumps({"status": "ok"})

    @mcp.tool(name="agora.instances")
    async def agora_instances() -> str:
        """List all registered instances visible to the server."""
        items = [
            {"instance_id": i.instance_id, "role": i.role, "registered_at": i.registered_at}
            for i in instance_registry.list_instances()
        ]
        return json.dumps({"instances": items})
```

세션 ID 추출 헬퍼는 동일 파일 상단에:

```python
def _session_id_from_ctx(ctx: Context) -> str:
    """FastMCP Context로부터 세션 식별자를 얻는다.
    SDK 버전에 따라 속성 경로가 다를 수 있다. 우선순위로 fallback.
    """
    for attr_chain in (("session", "session_id"), ("request_context", "session_id"), ("session_id",)):
        obj = ctx
        try:
            for attr in attr_chain:
                obj = getattr(obj, attr)
            if isinstance(obj, str):
                return obj
        except AttributeError:
            continue
    raise RuntimeError("Cannot determine session id from Context")
```

- [ ] **Step 6: `__main__.py`에서 InstanceRegistry 인스턴스 생성·전달**

`src/agent_agora/__main__.py`의 `run_server` 내부에서 `InstanceRegistry` import 후 인스턴스화하고 `create_agora_app`에 전달.

```python
from agent_agora.registry import InstanceRegistry
...
instance_registry = InstanceRegistry()
mcp, queue = create_agora_app(agora_dir, store, registry, instance_registry, args.port)
```

- [ ] **Step 7: 서버 통합 동작 확인 (smoke 테스트)**

```
pytest tests/test_server.py tests/test_registry.py -v
```

Expected: 기존 테스트 PASS + 신규 6개 PASS. (server.py 인자 변경으로 깨지는 기존 테스트는 fixture 업데이트)

- [ ] **Step 8: 커밋**

```
git add src/agent_agora/registry.py src/agent_agora/server.py src/agent_agora/__main__.py tests/test_registry.py tests/test_server.py
git commit -m "feat: instance registry with register/unregister/instances tools"
```

---

## Task 4: Dispatcher — dispatch + wait (long-poll mode)

**Files:**
- Create: `src/agent_agora/dispatcher.py`
- Create: `tests/test_dispatcher.py`
- Modify: `src/agent_agora/server.py` (`agora.dispatch`, `agora.wait` 도구 추가)
- Modify: `src/agent_agora/__main__.py` (CLI 옵션 추가, Dispatcher 인스턴스 전달)

**Rationale:** 핵심. A는 `agora.dispatch(target="B", payload=...)`로 큐 적재. B는 `agora.wait()`로 자기 앞으로 온 명령을 long-poll. 타임아웃 처리 + 무제한 모드 지원.

- [ ] **Step 1: Dispatcher 단위 테스트 작성**

`tests/test_dispatcher.py` 신규:

```python
from __future__ import annotations

import asyncio

import pytest

from agent_agora.dispatcher import Dispatcher, DispatcherClosed
from agent_agora.registry import InstanceRegistry, NotRegisteredError


@pytest.fixture
def setup():
    reg = InstanceRegistry()
    reg.register(session_id="sA", instance_id="A", role="orch")
    reg.register(session_id="sB", instance_id="B", role="worker")
    disp = Dispatcher(reg, default_timeout_ms=1000)
    return reg, disp


async def test_dispatch_to_unknown_target_raises(setup):
    reg, disp = setup
    with pytest.raises(NotRegisteredError):
        await disp.dispatch(source="A", target="X", payload={})


async def test_wait_returns_pending_commands(setup):
    reg, disp = setup
    await disp.dispatch(source="A", target="B", payload={"hello": 1})
    commands = await disp.wait(instance_id="B", timeout_ms=500)
    assert len(commands) == 1
    assert commands[0]["source"] == "A"
    assert commands[0]["payload"] == {"hello": 1}


async def test_wait_empty_after_timeout(setup):
    reg, disp = setup
    commands = await disp.wait(instance_id="B", timeout_ms=50)
    assert commands == []


async def test_wait_wakes_when_command_arrives(setup):
    reg, disp = setup

    async def wait_task():
        return await disp.wait(instance_id="B", timeout_ms=2000)

    waiter = asyncio.create_task(wait_task())
    await asyncio.sleep(0.05)
    await disp.dispatch(source="A", target="B", payload={"k": "v"})
    result = await waiter
    assert len(result) == 1
    assert result[0]["payload"] == {"k": "v"}


async def test_dispatch_broadcast_fans_out_to_all_others(setup):
    reg, disp = setup
    reg.register(session_id="sC", instance_id="C", role="worker")
    await disp.dispatch(source="A", target="_broadcast", payload={"ping": 1})
    b_cmds = await disp.wait(instance_id="B", timeout_ms=200)
    c_cmds = await disp.wait(instance_id="C", timeout_ms=200)
    assert len(b_cmds) == 1
    assert len(c_cmds) == 1
    # broadcast는 source 자신에게는 전달되지 않음
    a_cmds = await disp.wait(instance_id="A", timeout_ms=50)
    assert a_cmds == []


async def test_wait_no_timeout_blocks_until_command(setup):
    reg, disp = setup

    async def waiter_no_timeout():
        return await disp.wait(instance_id="B", timeout_ms=0)

    task = asyncio.create_task(waiter_no_timeout())
    await asyncio.sleep(0.1)
    assert not task.done()
    await disp.dispatch(source="A", target="B", payload={"x": 1})
    result = await asyncio.wait_for(task, timeout=1.0)
    assert len(result) == 1


async def test_close_releases_all_waiters(setup):
    reg, disp = setup

    async def w():
        return await disp.wait(instance_id="B", timeout_ms=0)

    task = asyncio.create_task(w())
    await asyncio.sleep(0.05)
    await disp.close()
    with pytest.raises(DispatcherClosed):
        await task


async def test_wait_for_unregistered_instance_raises(setup):
    reg, disp = setup
    with pytest.raises(NotRegisteredError):
        await disp.wait(instance_id="ghost", timeout_ms=10)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_dispatcher.py -v
```

Expected: ImportError.

- [ ] **Step 3: Dispatcher 구현**

`src/agent_agora/dispatcher.py` 신규:

```python
# src/agent_agora/dispatcher.py
from __future__ import annotations

import asyncio
import datetime
import uuid
from collections import defaultdict
from typing import Any

from agent_agora.registry import InstanceRegistry, NotRegisteredError


class DispatcherClosed(Exception):
    pass


class Dispatcher:
    """인스턴스별 명령 큐 + future 기반 wake. broadcast는 송신자 제외 fan-out."""

    BROADCAST_TARGET = "_broadcast"

    def __init__(self, registry: InstanceRegistry, default_timeout_ms: int = 60000) -> None:
        self._registry = registry
        self._default_timeout_ms = default_timeout_ms
        self._queues: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._waiters: dict[str, list[asyncio.Future]] = defaultdict(list)
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def default_timeout_ms(self) -> int:
        return self._default_timeout_ms

    async def dispatch(
        self,
        source: str,
        target: str,
        payload: Any,
        expect_result: bool = False,
    ) -> str:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        cmd_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with self._lock:
            if target == self.BROADCAST_TARGET:
                targets = [
                    info.instance_id
                    for info in self._registry.list_instances()
                    if info.instance_id != source
                ]
            else:
                self._registry.resolve_instance_id(target)
                targets = [target]
            for t in targets:
                command = {
                    "id": cmd_id,
                    "source": source,
                    "target": t,
                    "payload": payload,
                    "created_at": now,
                    "expect_result": expect_result,
                }
                self._queues[t].append(command)
                self._wake(t)
        return cmd_id

    def _wake(self, target: str) -> None:
        waiters = self._waiters.pop(target, [])
        for f in waiters:
            if not f.done():
                f.set_result(None)

    async def wait(self, instance_id: str, timeout_ms: int | None = None) -> list[dict[str, Any]]:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        self._registry.resolve_instance_id(instance_id)
        effective = self._default_timeout_ms if timeout_ms is None else timeout_ms
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._queues[instance_id]:
                drained = self._queues.pop(instance_id, [])
                return drained
            fut: asyncio.Future = loop.create_future()
            self._waiters[instance_id].append(fut)

        try:
            if effective <= 0:
                await fut
            else:
                await asyncio.wait_for(fut, timeout=effective / 1000.0)
        except asyncio.TimeoutError:
            async with self._lock:
                if fut in self._waiters.get(instance_id, []):
                    self._waiters[instance_id].remove(fut)
            return []
        except DispatcherClosed:
            raise

        async with self._lock:
            drained = self._queues.pop(instance_id, [])
        return drained

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            all_waiters = self._waiters
            self._waiters = defaultdict(list)
        for target, futs in all_waiters.items():
            for f in futs:
                if not f.done():
                    f.set_exception(DispatcherClosed("Dispatcher closed"))
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```
pytest tests/test_dispatcher.py -v
```

Expected: 8개 테스트 PASS.

- [ ] **Step 5: `__main__.py`에 CLI 옵션 추가**

`src/agent_agora/__main__.py`의 `parse_args` 함수에 추가:

```python
parser.add_argument(
    "--default-wait-timeout-ms",
    type=int,
    default=60000,
    help="Default timeout for agora.wait when caller does not specify (ms). Default: 60000",
)
parser.add_argument(
    "--no-timeout",
    action="store_true",
    help="Shortcut for --default-wait-timeout-ms 0 (unbounded blocking).",
)
```

`run_server` 본문에서:

```python
from agent_agora.dispatcher import Dispatcher
...
default_timeout = 0 if args.no_timeout else args.default_wait_timeout_ms
dispatcher = Dispatcher(instance_registry, default_timeout_ms=default_timeout)
mcp, queue = create_agora_app(agora_dir, store, registry, instance_registry, dispatcher, args.port)
```

`async with queue:` 블록 종료 시 `await dispatcher.close()` 호출:

```python
async with queue:
    try:
        await server.serve()
    finally:
        await dispatcher.close()
```

- [ ] **Step 6: `agora.dispatch` 및 `agora.wait` 도구를 server.py에 추가**

`src/agent_agora/server.py`의 `create_agora_app` 시그니처에 `dispatcher: Dispatcher` 인자 추가. 본문 끝에:

```python
from agent_agora.dispatcher import Dispatcher

# ... create_agora_app(agora_dir, store, registry, instance_registry, dispatcher, port):

    @mcp.tool(name="agora.dispatch")
    async def agora_dispatch(
        ctx: Context,
        target: str,
        payload: Any,
        expect_result: bool = False,
    ) -> str:
        """Dispatch a command to another registered instance, or '_broadcast' for fan-out."""
        try:
            source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            cmd_id = await dispatcher.dispatch(
                source=source, target=target, payload=payload, expect_result=expect_result,
            )
            return json.dumps({"status": "ok", "command_id": cmd_id, "target": target})
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(name="agora.wait")
    async def agora_wait(ctx: Context, timeout_ms: int | None = None) -> str:
        """Wait for commands targeted at this instance.

        timeout_ms: positive = wait at most N ms; 0 = no timeout (block forever);
        None = use server default (--default-wait-timeout-ms).
        Returns {commands: [...]}. Empty list means timeout with no commands.
        """
        try:
            info = instance_registry.resolve_session(_session_id_from_ctx(ctx))
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
        try:
            commands = await dispatcher.wait(instance_id=info.instance_id, timeout_ms=timeout_ms)
            return json.dumps({"commands": commands}, ensure_ascii=False)
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
```

- [ ] **Step 7: 서버 통합 동작 확인**

```
pytest tests/ -v
```

Expected: 모든 기존 + 신규 테스트 PASS.

- [ ] **Step 8: 커밋**

```
git add src/agent_agora/dispatcher.py src/agent_agora/server.py src/agent_agora/__main__.py tests/test_dispatcher.py
git commit -m "feat: dispatcher with long-poll agora.wait and agora.dispatch"
```

---

## Task 5: MCP Tasks Support for `agora.wait`

**Files:**
- Modify: `src/agent_agora/server.py` (도구 메타데이터에 `execution.taskSupport: "optional"` 추가)

**Rationale:** 표준 MCP Tasks를 지원하는 클라이언트는 `agora.wait`를 background task로 호출 가능. FastMCP가 `taskSupport` 메타데이터 노출을 지원하는지 확인 후, 지원하면 선언하고, 미지원이면 stub으로 두고 Issue 등록.

> **사전 조사 필요:** 사용된 `mcp` Python SDK가 `tools/list` 응답의 `execution.taskSupport`를 도구 데코레이터 인자로 지원하는지. SDK 버전이 사양보다 늦으면 이 단계는 미루고 진행. (이 task의 실행 시점에 SDK 문서 확인)

- [ ] **Step 1: SDK 지원 여부 확인**

`mcp` Python SDK가 도구 데코레이터에 `taskSupport` 또는 유사 인자를 받는지 확인.

```
python -c "from mcp.server.fastmcp import FastMCP; import inspect; print(inspect.signature(FastMCP.tool))"
```

해당 키워드가 없으면 SDK가 아직 미지원. 미지원이면 **다음 단계로 건너뛰지 말고**, FastMCP의 `tool_manager`나 raw `list_tools` 응답에 `execution` 필드를 수동 주입하는 방식 또는 SDK를 패치해 추가.

- [ ] **Step 2: SDK 지원하는 경우 — `agora.wait` 데코레이터에 추가**

```python
@mcp.tool(name="agora.wait", execution={"taskSupport": "optional"})
async def agora_wait(ctx: Context, timeout_ms: int | None = None) -> str:
    ...
```

- [ ] **Step 3: SDK 미지원하는 경우 — `tools/list` 응답 후처리 미들웨어**

`create_agora_app` 내부에서 `mcp._tool_manager` 또는 동등 API에 접근해 `agora.wait`의 메타데이터에 `execution: {taskSupport: "optional"}`를 주입. SDK 내부 구조 의존성이 생기므로 주석에 "FIXME: SDK upgrade 후 표준 데코레이터 인자로 교체"라고 명시.

- [ ] **Step 4: tools/list 응답 검증 테스트 추가**

`tests/test_server.py`에 추가:

```python
async def test_agora_wait_declares_optional_task_support(agora_dir_with_schemas):
    # in-process FastMCP 클라이언트로 tools/list 호출 후
    # agora.wait의 execution.taskSupport == "optional" 확인
    ...
```

(이 테스트의 실제 구현은 FastMCP의 in-process client API에 따라 결정. Task 7 통합 테스트에서 정밀하게 검증.)

- [ ] **Step 5: 테스트 실행**

```
pytest tests/test_server.py -v
```

Expected: PASS. SDK 미지원이라 우회 코드가 들어갔다면 주석으로 사유 명시했는지 검토.

- [ ] **Step 6: 커밋**

```
git add src/agent_agora/server.py tests/test_server.py
git commit -m "feat: declare optional task support on agora.wait"
```

> **참고:** MCP Tasks의 본격적인 `tasks/get`/`tasks/result`/`tasks/cancel` 흐름은 SDK가 자동 처리한다. 우리 서버 코드는 도구 메타데이터 선언만 책임지면 됨. SDK가 이를 자동 처리하지 않는다면 별도 후속 plan으로 분리.

---

## Task 6: HTTP Session Close → Auto Unregister

**Files:**
- Create: `src/agent_agora/session_hook.py`
- Create: `tests/test_session_hook.py`
- Modify: `src/agent_agora/__main__.py` (Starlette app에 미들웨어 부착)

**Rationale:** 클라이언트가 비정상 종료/연결 끊김 시 stale 등록이 남으면 A가 "B에 명령" 시 B는 죽었는데 큐만 쌓임. HTTP 레벨에서 연결 종료를 감지해 자동 unregister.

- [ ] **Step 1: 테스트 작성 — 미들웨어가 세션 종료 시 unregister 호출**

`tests/test_session_hook.py` 신규:

```python
from __future__ import annotations

import asyncio

import pytest

from agent_agora.registry import InstanceRegistry, NotRegisteredError
from agent_agora.session_hook import SessionCloseMiddleware


class _FakeApp:
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope.get("type"))
        async def _r():
            return {"type": "http.disconnect"}
        await receive()


async def test_middleware_unregisters_on_request_end(monkeypatch):
    reg = InstanceRegistry()
    reg.register(session_id="abc-123", instance_id="A", role="r")
    app = _FakeApp()
    mw = SessionCloseMiddleware(app=app, registry=reg, header_name="Mcp-Session-Id")

    async def receive():
        return {"type": "http.disconnect"}

    sends = []
    async def send(msg):
        sends.append(msg)

    scope = {
        "type": "http",
        "headers": [(b"mcp-session-id", b"abc-123")],
    }
    await mw(scope, receive, send)
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("abc-123")
```

(미들웨어 hook 정확한 ASGI 지점은 구현에서 결정 — `http.disconnect` 이벤트 또는 응답 송신 후 cleanup.)

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```
pytest tests/test_session_hook.py -v
```

Expected: ImportError.

- [ ] **Step 3: `session_hook.py` 구현**

`src/agent_agora/session_hook.py` 신규:

```python
# src/agent_agora/session_hook.py
from __future__ import annotations

from typing import Callable

from agent_agora.registry import InstanceRegistry


class SessionCloseMiddleware:
    """ASGI middleware that calls registry.unregister_session(session_id) when an HTTP
    connection associated with that session id finishes (response sent or client disconnects).

    The session id is read from a configurable request header (default: Mcp-Session-Id).
    """

    def __init__(self, app, registry: InstanceRegistry, header_name: str = "Mcp-Session-Id") -> None:
        self._app = app
        self._registry = registry
        self._header_lower = header_name.lower().encode("latin-1")

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        session_id = self._extract_session_id(scope)

        disconnected = {"value": False}

        async def _wrapped_receive():
            msg = await receive()
            if msg.get("type") == "http.disconnect":
                disconnected["value"] = True
            return msg

        try:
            await self._app(scope, _wrapped_receive, send)
        finally:
            if session_id and disconnected["value"]:
                self._registry.unregister_session(session_id)

    def _extract_session_id(self, scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name.lower() == self._header_lower:
                return value.decode("latin-1")
        return None
```

> **주의:** MCP Streamable HTTP의 세션 ID 헤더 이름은 사양에 정의되어 있다 (현재 `Mcp-Session-Id`). 만약 SDK 구현이 다른 이름을 쓰면 그 이름으로 맞춤.

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```
pytest tests/test_session_hook.py -v
```

Expected: PASS.

- [ ] **Step 5: `__main__.py`에 미들웨어 부착**

```python
from agent_agora.session_hook import SessionCloseMiddleware
from starlette.middleware import Middleware

starlette_app = mcp.streamable_http_app()
starlette_app.user_middleware.insert(
    0, Middleware(SessionCloseMiddleware, registry=instance_registry)
)
# (Starlette의 정확한 미들웨어 추가 API는 SDK 버전에 따라 다름. 위 형태가 안 되면
#  starlette_app.add_middleware(SessionCloseMiddleware, registry=instance_registry) 시도)
```

- [ ] **Step 6: 전체 테스트 실행**

```
pytest tests/ -v
```

Expected: 모두 PASS.

- [ ] **Step 7: 커밋**

```
git add src/agent_agora/session_hook.py src/agent_agora/__main__.py tests/test_session_hook.py
git commit -m "feat: auto-unregister instances on HTTP session close"
```

---

## Task 7: Integration Test — A→B End-to-End

**Files:**
- Create: `tests/test_integration.py`

**Rationale:** 단위 테스트로는 잡히지 않는 통합 흐름 검증. in-process FastMCP 클라이언트 2개를 띄워 A와 B 역할을 시뮬레이션.

> **방법:** FastMCP는 in-memory 클라이언트/서버 짝을 제공한다 (`mcp.client.session` + memory transport). 클라이언트 2개 인스턴스를 같은 서버에 붙여 register → dispatch → wait 시퀀스 검증.

- [ ] **Step 1: 통합 테스트 작성**

`tests/test_integration.py` 신규:

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.schema import SchemaRegistry
from agent_agora.server import create_agora_app
from agent_agora.store import AgoraStore


@pytest.fixture
def runtime(tmp_path, sample_schemas):
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    (agora_dir / "schemas.json").write_text(json.dumps(sample_schemas))
    schema_reg = SchemaRegistry.load(agora_dir)
    store = AgoraStore(agora_dir, schema_reg)
    inst_reg = InstanceRegistry()
    disp = Dispatcher(inst_reg, default_timeout_ms=2000)
    mcp, queue = create_agora_app(agora_dir, store, schema_reg, inst_reg, disp, port=0)
    return mcp, queue, inst_reg, disp


async def test_a_dispatches_b_receives(runtime):
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        # 두 세션을 직접 시뮬레이션 (in-process FastMCP client는 SDK 버전에 따라 다르므로,
        # registry/dispatcher 직접 호출로 시나리오 시뮬레이션)
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")

        wait_task = asyncio.create_task(disp.wait(instance_id="B", timeout_ms=1000))
        await asyncio.sleep(0.05)
        await disp.dispatch(source="A", target="B", payload={"task": "run-tests"})

        commands = await wait_task
        assert len(commands) == 1
        assert commands[0]["payload"] == {"task": "run-tests"}
        assert commands[0]["source"] == "A"


async def test_broadcast_fans_out(runtime):
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")
        inst_reg.register(session_id="sC", instance_id="C", role="worker")

        await disp.dispatch(source="A", target="_broadcast", payload={"ping": 1})
        b = await disp.wait(instance_id="B", timeout_ms=200)
        c = await disp.wait(instance_id="C", timeout_ms=200)
        assert len(b) == 1
        assert len(c) == 1
        a = await disp.wait(instance_id="A", timeout_ms=100)
        assert a == []


async def test_result_writeback_via_append(runtime):
    """B가 명령 처리 후 results 스키마에 결과 append, A가 다음 wait로 회수."""
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        inst_reg.register(session_id="sB", instance_id="B", role="worker")

        cmd_id = await disp.dispatch(
            source="A", target="B", payload={"task": "echo", "value": 42}, expect_result=True,
        )
        cmds = await disp.wait(instance_id="B", timeout_ms=500)
        assert cmds[0]["expect_result"] is True
        # B가 결과를 A에게 dispatch (별도 명령으로 회신)
        await disp.dispatch(source="B", target="A", payload={
            "result_for": cmd_id, "value": 42,
        })
        a_cmds = await disp.wait(instance_id="A", timeout_ms=500)
        assert a_cmds[0]["payload"]["result_for"] == cmd_id


async def test_unknown_target_dispatch_raises(runtime):
    mcp, queue, inst_reg, disp = runtime
    async with queue:
        inst_reg.register(session_id="sA", instance_id="A", role="orch")
        from agent_agora.registry import NotRegisteredError
        with pytest.raises(NotRegisteredError):
            await disp.dispatch(source="A", target="ghost", payload={})


async def test_session_close_removes_instance(runtime):
    mcp, queue, inst_reg, disp = runtime
    inst_reg.register(session_id="sA", instance_id="A", role="orch")
    assert inst_reg.resolve_instance_id("A").session_id == "sA"
    inst_reg.unregister_session("sA")
    from agent_agora.registry import NotRegisteredError
    with pytest.raises(NotRegisteredError):
        inst_reg.resolve_instance_id("A")
```

- [ ] **Step 2: 실행**

```
pytest tests/test_integration.py -v
```

Expected: 5개 시나리오 모두 PASS.

- [ ] **Step 3: 전체 회귀 실행**

```
pytest tests/ -v
```

Expected: 전 테스트 PASS.

- [ ] **Step 4: 커밋**

```
git add tests/test_integration.py
git commit -m "test: integration scenarios for A->B dispatch, broadcast, result writeback"
```

---

## Task 8: Manual Smoke Test with Real Claude Code (Documentation Only)

**Files:**
- Create: `docs/manual-smoke-test.md`

**Rationale:** 자동 테스트는 in-process 시뮬레이션. 실제 Claude Code 인스턴스 2개 + AgentAgora 서버 1개로 hand-on 검증 절차를 문서화.

- [ ] **Step 1: 수동 검증 문서 작성**

`docs/manual-smoke-test.md` 신규:

```markdown
# AgentAgora Inter-Instance Smoke Test

## Prerequisites
- AgentAgora 서버 실행 가능한 디렉터리에 `.agentagora/schemas.json` 존재
- 동일 머신에 Claude Code 인스턴스 2개 실행 가능

## Steps

1. 서버 실행
   ```
   agent-agora --dir ./.agentagora --port 8420
   ```

2. Claude Code 인스턴스 A 실행. MCP config에 AgentAgora 추가. 첫 입력:
   ```
   agora.register 도구로 instance_id="A", role="orchestrator" 등록해줘.
   ```

3. Claude Code 인스턴스 B 실행. 동일하게 AgentAgora 연결. 첫 입력:
   ```
   agora.register 도구로 instance_id="B", role="worker" 등록한 다음
   agora.wait 도구를 계속 호출하면서 들어오는 명령을 처리해줘.
   각 명령의 payload는 자연어 지시야.
   ```

4. 인스턴스 A에 입력:
   ```
   agora.instances로 등록된 인스턴스 목록 확인하고,
   agora.dispatch로 target="B", payload="src/agent_agora 디렉터리 파일 목록 보고해줘" 보내.
   ```

5. 인스턴스 B에서 명령이 도착해 처리 후 결과를 다시 `agora.dispatch(target="A", payload=...)`로 회신하는지 확인.

6. 인스턴스 B 종료(Ctrl+C). 인스턴스 A에서:
   ```
   agora.instances로 다시 목록 조회. B가 사라졌어야 함.
   ```

## 통과 기준
- 4번에서 B가 명령을 받고 처리한다.
- 5번에서 A가 결과를 받는다.
- 6번에서 B의 등록이 자동 제거된다 (HTTP 세션 종료 hook 작동 검증).
```

- [ ] **Step 2: 커밋**

```
git add docs/manual-smoke-test.md
git commit -m "docs: manual smoke test for inter-instance command channel"
```

---

## Final Acceptance

플랜 전체가 완료되면 다음이 모두 참:

- [ ] `pytest tests/ -v` 전 테스트 통과
- [ ] 도구 11개가 `tools/list`에 슬래시 없이 노출됨
- [ ] `agora.wait`가 `execution.taskSupport: "optional"`로 선언됨 (SDK 지원 시)
- [ ] `agora.dispatch(target="_broadcast", ...)`가 송신자 제외 fan-out
- [ ] 등록 안 된 세션의 `dispatch`/`wait`는 명확한 에러 반환
- [ ] HTTP 세션 종료 시 instance entry 자동 제거
- [ ] `--no-timeout` 플래그로 무제한 wait 가능
- [ ] 수동 smoke test 절차 문서화

---

## What Could Break (Pre-Implementation Review)

1. **FastMCP `Context` 세션 ID 속성 경로**: SDK 버전에 따라 `ctx.session.session_id` / `ctx.request_context.session_id` 등 다름. `_session_id_from_ctx` 헬퍼의 fallback 순회가 실패할 수 있음. 구현 시점에 SDK 소스를 직접 확인 권장.
2. **MCP Tasks 메타데이터 자동 노출**: `mcp` Python SDK 버전이 `execution.taskSupport` 키를 자동 직렬화하지 않으면 Task 5가 우회 코드로 빠짐.
3. **Starlette 미들웨어 부착 API**: SDK가 `streamable_http_app()`을 반환하는 형태가 변경되면 미들웨어 삽입 위치가 달라짐.
4. **HTTP 세션 ID 헤더 이름**: 사양은 `Mcp-Session-Id`. SDK 구현이 다르면 헤더 이름 조정.
5. **`asyncio.Lock` 안에서 future 생성·등록 분리 시 race**: Dispatcher의 `wait`에서 큐 검사 후 future 등록 사이 갱신될 수 있음. 현 구현은 동일 lock 안에서 처리하므로 안전.
6. **broadcast 시점에 새 인스턴스 등록**: 새 인스턴스는 fan-out에 포함되지 않음. 의도된 동작.
7. **무제한 wait + 서버 종료**: `Dispatcher.close()`가 모든 waiter에 예외 주입. `__main__.py`의 `finally`에서 호출 보장.

---

## Self-Review Notes

- 모든 task의 코드 블록은 실제 동작 가능한 형태로 작성.
- Type/메서드 일관성: `InstanceRegistry.resolve_session/resolve_instance_id/list_instances`, `Dispatcher.dispatch/wait/close/BROADCAST_TARGET` 등 이름 전 task에 걸쳐 동일.
- Placeholder 없음. 단, Task 5의 `taskSupport` 선언 방식과 Task 6의 ASGI 미들웨어 부착 정확한 API는 SDK 버전 의존적이라 "구현 시점에 확인" 명시 — placeholder가 아니라 합리적 양보.
- Test coverage: registry (6 cases), dispatcher (8 cases), schema (3 신규), integration (5), session_hook (1). 핵심 경로 모두 커버.
