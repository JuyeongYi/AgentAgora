# wait-tool-gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the blocking long-poll tool `agora.wait_notify` from the default MCP tool surface of channel-mode workers, replacing the adapter/SDK transport with an always-on `GET /channel/wait` HTTP endpoint.

**Architecture:** Add a Starlette HTTP route `GET /channel/wait` (same pattern as `file_routes`/`dashboard_routes`) that delegates to the existing `dispatcher.wait_notify` method. Gate the MCP `agora.wait_notify` tool behind a `--add-wait` flag (default off). Switch the `agora-channel` adapter and the `AgoraBot` SDK to call the HTTP endpoint with `httpx` instead of the MCP tool.

**Tech Stack:** Python 3.13, FastMCP, Starlette, httpx, pytest, pytest-asyncio.

---

## Spec

Source of truth: `docs/superpowers/specs/2026-05-18-wait-tool-gating-design.md`.

## File Structure

- **Create** `src/agent_agora/channel_routes.py` — `register(app, *, dispatcher)` that
  appends the `GET /channel/wait` route. Mirrors `file_routes.py`/`dashboard_routes.py`.
- **Modify** `src/agent_agora/server.py` — `create_agora_app` gains an `add_wait: bool = False`
  parameter; the `agora.wait_notify` `@mcp.tool` registration moves inside `if add_wait:`.
- **Modify** `src/agent_agora/__main__.py` — `--add-wait` CLI flag; `_build_app` gains
  `add_wait` and forwards it; `run_server` calls `channel_routes.register`.
- **Modify** `src/agent_agora/channel_adapter.py` — the `wait_notify` callable becomes an
  HTTP `GET /channel/wait` call via `httpx`; `peek_pending` stays on the MCP `agora.peek` tool.
- **Modify** `src/agent_agora/bot.py` — `AgoraBot.run()`'s receive loop uses the HTTP
  `GET /channel/wait` endpoint instead of the `agora.wait_notify` MCP tool.
- **Create** `tests/test_channel_routes.py` — route behavior.
- **Modify** `tests/test_main.py`, `tests/test_v4_wait_notify.py`,
  `tests/test_channel_adapter.py`, `tests/test_v4_bot_sdk.py` — coverage updates.
- **Modify** `docs/channel-mode.md` — flow description.

A shared helper `_channel_wait_base_url(mcp_url)` (strip a trailing `/mcp`) is needed by
both the adapter and the SDK. Put it in `channel_adapter.py` and import it from `bot.py`
to keep it DRY (Task 5 defines it; Task 6 reuses it).

---

## Task 1: `GET /channel/wait` HTTP route

**Files:**
- Create: `src/agent_agora/channel_routes.py`
- Test: `tests/test_channel_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_channel_routes.py`:

```python
"""GET /channel/wait HTTP 엔드포인트 테스트."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.bot_registry import BotRegistry
from agent_agora.channel_routes import register
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import AsyncWriteQueue, Persistence
from agent_agora.registry import InstanceRegistry
from _helpers import make_schema_registry, tany


@pytest.fixture
async def client(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 4):
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
            default_timeout_ms=300)
        app = Starlette()
        register(app, dispatcher=dispatcher)
        yield TestClient(app), dispatcher


@pytest.mark.asyncio
async def test_wait_returns_snapshot_when_queue_nonempty(client):
    tc, dispatcher = client
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    r = tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 200})
    assert r.status_code == 200
    body = r.json()
    assert body == {"instance_id": "Inst2", "pending": 1, "sources": ["Inst1"]}


@pytest.mark.asyncio
async def test_wait_timeout_returns_empty_snapshot(client):
    tc, dispatcher = client
    r = tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 50})
    assert r.status_code == 200
    assert r.json() == {"instance_id": "Inst2", "pending": 0, "sources": []}


@pytest.mark.asyncio
async def test_wait_missing_instance_id_is_400(client):
    tc, _ = client
    r = tc.get("/channel/wait", params={"timeout_ms": 50})
    assert r.status_code == 400
    assert "error" in r.json()


@pytest.mark.asyncio
async def test_wait_is_non_destructive(client):
    tc, dispatcher = client
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1))
    tc.get("/channel/wait", params={"instance_id": "Inst2", "timeout_ms": 100})
    drained = await dispatcher.flush("Inst2")
    assert len(drained) == 1


@pytest.mark.asyncio
async def test_wait_omitted_timeout_uses_server_default(client):
    tc, dispatcher = client
    # default_timeout_ms=300 → no timeout_ms param still returns within ~300ms
    r = tc.get("/channel/wait", params={"instance_id": "Inst2"})
    assert r.status_code == 200
    assert r.json()["pending"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_channel_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.channel_routes'`.

- [ ] **Step 3: Write the route module**

Create `src/agent_agora/channel_routes.py`:

```python
"""채널 어댑터·봇 SDK용 인박스 감지 HTTP 엔드포인트 — GET /channel/wait.

agora-channel 어댑터와 AgoraBot SDK가 워커 인박스 도착을 감지하는 always-on
경로. 블로킹 long-poll 도구 agora.wait_notify를 워커 MCP 도구 표면에서 들어내고
이 HTTP 라우트로 대체한다. localhost 전용·토큰 없음 — 서버 127.0.0.1 바인딩에
의존. wait_notify는 advisory·비파괴 peek이라(pending 개수·sources 목록만 노출)
always-on이어도 안전하다.

spec: docs/superpowers/specs/2026-05-18-wait-tool-gating-design.md.
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_agora.dispatcher import DispatcherClosed


def register(app: Starlette, *, dispatcher) -> None:
    """app에 GET /channel/wait 라우트를 등록한다."""

    async def wait_endpoint(request: Request) -> JSONResponse:
        instance_id = request.query_params.get("instance_id")
        if not instance_id:
            return JSONResponse(
                {"error": "instance_id query parameter is required"},
                status_code=400)
        raw_timeout = request.query_params.get("timeout_ms")
        timeout_ms = None
        if raw_timeout is not None and raw_timeout != "":
            try:
                timeout_ms = int(raw_timeout)
            except ValueError:
                return JSONResponse(
                    {"error": "timeout_ms must be an integer"},
                    status_code=400)
        try:
            result = await dispatcher.wait_notify(
                instance_id=instance_id, timeout_ms=timeout_ms)
        except DispatcherClosed:
            return JSONResponse(
                {"error": "server is shutting down"}, status_code=503)
        return JSONResponse(result)

    app.router.routes.append(
        Route("/channel/wait", wait_endpoint, methods=["GET"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_channel_routes.py -v`
Expected: PASS — all 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/channel_routes.py tests/test_channel_routes.py docs/superpowers/specs/2026-05-18-wait-tool-gating-design.md docs/superpowers/plans/2026-05-18-wait-tool-gating.md
git commit -m "feat: add GET /channel/wait HTTP endpoint for inbox detection"
```

---

## Task 2: Gate `agora.wait_notify` MCP tool behind `add_wait`

**Files:**
- Modify: `src/agent_agora/server.py` (signature ~line 65-76; tool registration ~line 529-539)
- Test: `tests/test_v4_wait_notify.py:106-112`

- [ ] **Step 1: Update the failing test**

Replace `test_wait_notify_tool_registered` at the bottom of `tests/test_v4_wait_notify.py`
with three tests:

```python
def test_wait_notify_tool_not_registered_by_default(agora_dir):
    """_build_app은 기본적으로 agora.wait_notify 도구를 등록하지 않는다."""
    from agent_agora.__main__ import _build_app
    mcp = _build_app(agora_dir=agora_dir, port=8499)
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "agora.wait_notify" not in names


def test_wait_notify_tool_registered_with_add_wait(agora_dir):
    """add_wait=True면 agora.wait_notify 도구가 등록된다."""
    from agent_agora.__main__ import _build_app
    mcp = _build_app(agora_dir=agora_dir, port=8499, add_wait=True)
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "agora.wait_notify" in names


def test_flush_tool_always_registered(agora_dir):
    """agora.flush는 게이팅과 무관하게 항상 등록된다."""
    from agent_agora.__main__ import _build_app
    mcp = _build_app(agora_dir=agora_dir, port=8499)
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "agora.flush" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_v4_wait_notify.py -v -k "tool"`
Expected: FAIL — `test_wait_notify_tool_not_registered_by_default` fails (tool still
registered); `test_wait_notify_tool_registered_with_add_wait` fails (`_build_app` has no
`add_wait` kwarg → `TypeError`).

- [ ] **Step 3: Add `add_wait` parameter to `create_agora_app`**

In `src/agent_agora/server.py`, add `add_wait: bool = False` to the `create_agora_app`
signature. Change:

```python
def create_agora_app(
    agora_dir: Path,
    instance_registry: InstanceRegistry,
    schema_registry: SchemaRegistry,
    bot_registry: BotRegistry,
    comm_matrix: CommMatrix,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
    file_store: Any = None,
    file_policy: Any = None,
) -> FastMCP:
```

to:

```python
def create_agora_app(
    agora_dir: Path,
    instance_registry: InstanceRegistry,
    schema_registry: SchemaRegistry,
    bot_registry: BotRegistry,
    comm_matrix: CommMatrix,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
    file_store: Any = None,
    file_policy: Any = None,
    add_wait: bool = False,
) -> FastMCP:
```

- [ ] **Step 4: Gate the `agora.wait_notify` tool registration**

In `src/agent_agora/server.py`, the current block is:

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

Replace it with the same block wrapped in `if add_wait:` (note: nested defs under an
`if` are valid Python; the `@mcp.tool` decorator runs only when `add_wait` is truthy):

```python
    if add_wait:
        @mcp.tool(name="agora.wait_notify")
        async def agora_wait_notify(instance_id: str, timeout_ms: int | None = None) -> str:
            """Non-destructive long-poll — block until instance_id has inbound,
            then return {instance_id, pending, sources} without draining the queue.
            Opt-in via --add-wait. The agora-channel adapter and AgoraBot SDK use
            the GET /channel/wait HTTP endpoint instead. instance_id need not be
            registered."""
            try:
                result = await dispatcher.wait_notify(
                    instance_id=instance_id, timeout_ms=timeout_ms)
                return json.dumps(result, ensure_ascii=False)
            except DispatcherClosed:
                return json.dumps({"error": "server is shutting down"})
```

`DispatcherClosed` is already imported at the top of `server.py` (`from
agent_agora.dispatcher import Dispatcher, DispatcherClosed`) — leave it.

- [ ] **Step 5: Add `add_wait` to `_build_app` and forward it**

In `src/agent_agora/__main__.py`, the `_build_app` signature is:

```python
def _build_app(
    agora_dir: Path,
    port: int,
    no_tls: bool = False,
    default_wait_timeout_ms: int = 60000,
    max_inbox_depth: int = 100,
    db_path: Path | None = None,
    close_timeout_ms: int = 300_000,
    dead_session_timeout_ms: int = 1_800_000,
    gc_retention_days: int = 90,
    file_retention_days: int = 7,
):
```

Add `add_wait: bool = False,` as the last parameter. Then in the `create_agora_app(...)`
call inside `_build_app`, add `add_wait=add_wait,` after `file_policy=file_policy,`:

```python
    mcp = create_agora_app(
        agora_dir=agora_dir,
        instance_registry=instance_registry,
        schema_registry=schema_registry,
        bot_registry=bot_registry,
        comm_matrix=comm_matrix,
        persistence=persistence,
        dispatcher=dispatcher,
        port=port,
        file_store=file_store,
        file_policy=file_policy,
        add_wait=add_wait,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_v4_wait_notify.py -v`
Expected: PASS — all tests, including the three new tool-registration tests.

- [ ] **Step 7: Commit**

```bash
git add src/agent_agora/server.py src/agent_agora/__main__.py tests/test_v4_wait_notify.py
git commit -m "feat: gate agora.wait_notify MCP tool behind add_wait flag"
```

---

## Task 3: `--add-wait` CLI flag

**Files:**
- Modify: `src/agent_agora/__main__.py` (`parse_args` ~line 11-43; `run_server` ~line 177-188)
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
def test_add_wait_flag_defaults_false():
    assert parse_args(["--port", "8420"]).add_wait is False


def test_add_wait_flag_true_when_given():
    assert parse_args(["--add-wait"]).add_wait is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_main.py -v -k add_wait`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'add_wait'`.

- [ ] **Step 3: Add the `--add-wait` argument**

In `src/agent_agora/__main__.py`, inside `parse_args`, add this line after the
`--restore` argument block (before `return parser.parse_args(argv)`):

```python
    parser.add_argument(
        "--add-wait",
        action="store_true",
        help="레거시·디버깅용 — agora.wait_notify MCP 도구를 등록한다. "
             "기본 미등록. 채널 어댑터·봇 SDK는 GET /channel/wait를 쓴다.",
    )
```

- [ ] **Step 4: Forward `add_wait` from `run_server` to `_build_app`**

In `src/agent_agora/__main__.py`, inside `run_server`, the `_build_app(...)` call ends
with `file_retention_days=args.file_retention_days,`. Add `add_wait=args.add_wait,`
after it:

```python
    mcp = _build_app(
        agora_dir=agora_dir,
        port=args.port,
        no_tls=args.no_tls,
        default_wait_timeout_ms=default_timeout,
        max_inbox_depth=args.max_inbox_depth,
        db_path=db_path,
        close_timeout_ms=args.close_timeout_ms,
        dead_session_timeout_ms=args.dead_session_timeout_ms,
        gc_retention_days=args.gc_retention_days,
        file_retention_days=args.file_retention_days,
        add_wait=args.add_wait,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_main.py -v`
Expected: PASS — all tests.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/__main__.py tests/test_main.py
git commit -m "feat: add --add-wait CLI flag"
```

---

## Task 4: Register `/channel/wait` route in `run_server`

**Files:**
- Modify: `src/agent_agora/__main__.py` (`run_server` route-registration block ~line 210-235)

- [ ] **Step 1: Register the route**

In `src/agent_agora/__main__.py`, inside `run_server`, after the `register_files(...)`
call and its `print("  Files    : ...")` line, add:

```python
        from agent_agora.channel_routes import register as register_channel
        register_channel(starlette_app, dispatcher=dispatcher)
        print("  Channel  : GET /channel/wait")
```

This route is always registered — independent of `--add-wait` — because the adapter and
SDK depend on it (spec §3.1).

- [ ] **Step 2: Verify the server still imports and the app builds**

Run: `py -3.13 -c "from agent_agora.__main__ import _build_app; print('import OK')"`
Expected: `import OK`.

Run the full main test module: `py -3.13 -m pytest tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/agent_agora/__main__.py
git commit -m "feat: wire GET /channel/wait route into server startup"
```

---

## Task 5: Switch `agora-channel` adapter to HTTP `wait_notify`

**Files:**
- Modify: `src/agent_agora/channel_adapter.py` (`_make_broker_callables` ~line 122-141; imports ~line 12-24)
- Test: `tests/test_channel_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_channel_adapter.py`:

```python
def test_channel_wait_base_url_strips_mcp_suffix():
    from agent_agora.channel_adapter import _channel_wait_base_url
    assert _channel_wait_base_url("http://127.0.0.1:8420/mcp") == "http://127.0.0.1:8420"
    assert _channel_wait_base_url("http://h:9/mcp/") == "http://h:9"
    # no /mcp suffix → returned unchanged (minus any trailing slash)
    assert _channel_wait_base_url("http://h:9") == "http://h:9"
    assert _channel_wait_base_url("http://h:9/") == "http://h:9"


@pytest.mark.asyncio
async def test_http_wait_notify_calls_channel_wait_endpoint(monkeypatch):
    """HTTP wait_notify 콜러블이 GET /channel/wait를 올바른 파라미터로 호출한다."""
    from agent_agora.channel_adapter import _make_http_wait_notify

    seen = {}

    class _FakeResponse:
        def json(self):
            return {"instance_id": "InstA", "pending": 2, "sources": ["PM"]}
        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url, params=None):
            seen["url"] = url
            seen["params"] = params
            return _FakeResponse()

    monkeypatch.setattr("agent_agora.channel_adapter.httpx.AsyncClient",
                        _FakeAsyncClient)
    wait_notify = _make_http_wait_notify("http://127.0.0.1:8420/mcp")
    result = await wait_notify("InstA", 5000)
    assert result == {"instance_id": "InstA", "pending": 2, "sources": ["PM"]}
    assert seen["url"] == "http://127.0.0.1:8420/channel/wait"
    assert seen["params"] == {"instance_id": "InstA", "timeout_ms": 5000}


@pytest.mark.asyncio
async def test_http_wait_notify_returns_error_dict_on_failure(monkeypatch):
    """HTTP 호출 실패 시 {error:...} dict를 반환한다 — watch_loop가 backoff한다."""
    from agent_agora.channel_adapter import _make_http_wait_notify

    class _BoomClient:
        def __init__(self, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url, params=None):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("agent_agora.channel_adapter.httpx.AsyncClient",
                        _BoomClient)
    wait_notify = _make_http_wait_notify("http://127.0.0.1:8420/mcp")
    result = await wait_notify("InstA", 5000)
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_channel_adapter.py -v -k "channel_wait or http_wait"`
Expected: FAIL — `ImportError: cannot import name '_channel_wait_base_url'` /
`_make_http_wait_notify`.

- [ ] **Step 3: Add the HTTP wait helpers**

In `src/agent_agora/channel_adapter.py`, add `import httpx` to the imports (after
`import anyio`):

```python
import anyio
import httpx
```

Then add these two functions just before `_make_broker_callables` (after the
`_result_json` helper):

```python
def _channel_wait_base_url(broker_mcp_url: str) -> str:
    """브로커 MCP URL에서 GET /channel/wait의 베이스 URL을 유도한다.

    어댑터는 --broker로 MCP 엔드포인트(http://host:port/mcp)를 받는다.
    /channel/wait는 같은 호스트·포트의 다른 경로다 — /mcp 꼬리를 떼어낸다."""
    url = broker_mcp_url.rstrip("/")
    if url.endswith("/mcp"):
        url = url[: -len("/mcp")]
    return url.rstrip("/")


def _make_http_wait_notify(broker_mcp_url: str):
    """GET /channel/wait를 호출하는 wait_notify 콜러블을 만든다.

    blocking long-poll 도구 agora.wait_notify를 대체한다 — 워커 MCP 도구
    표면을 오염시키지 않는 HTTP 경로다. 호출 실패 시 {error:...} dict를
    반환한다(watch_loop가 이 신호를 보면 backoff한다)."""
    wait_url = _channel_wait_base_url(broker_mcp_url) + "/channel/wait"

    async def wait_notify(instance_id: str, timeout_ms: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=None) as http:
                resp = await http.get(
                    wait_url,
                    params={"instance_id": instance_id,
                            "timeout_ms": timeout_ms})
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001 — 연결 실패는 backoff 신호
            return {"error": f"channel/wait HTTP 호출 실패: {exc!r}"}

    return wait_notify
```

Note: `timeout=None` on the `httpx.AsyncClient` disables the client-side timeout — the
endpoint itself long-polls and bounds the wait with the server's `timeout_ms`.

- [ ] **Step 4: Use the HTTP wait_notify in `_make_broker_callables`**

`_make_broker_callables` currently builds both `wait_notify` and `peek_pending` from the
MCP `broker_session`. Change its signature to also accept the broker URL, and build
`wait_notify` from HTTP. Replace the whole function:

```python
def _make_broker_callables(broker_session: ClientSession, broker_mcp_url: str):
    """브로커 콜러블 (wait_notify, peek_pending)을 만든다.

    wait_notify는 GET /channel/wait HTTP 엔드포인트를 쓴다 — blocking long-poll
    도구를 워커 MCP 도구 표면에서 들어낸 결과. peek_pending은 논블로킹·비파괴
    agora.peek MCP 도구를 그대로 쓴다."""

    wait_notify = _make_http_wait_notify(broker_mcp_url)

    async def peek_pending(instance_id: str) -> int:
        result = await broker_session.call_tool(
            "agora.peek", {"targets": [instance_id]},
        )
        data = _result_json(result)
        entry = data.get(instance_id) or {}
        depth = entry.get("queue_depth")
        return depth if isinstance(depth, int) else 0

    return wait_notify, peek_pending
```

- [ ] **Step 5: Pass the broker URL at the call site**

In `src/agent_agora/channel_adapter.py`, inside `_run_watch`, the call is:

```python
                    wait_notify, peek_pending = _make_broker_callables(
                        broker_session)
```

Change it to pass `broker`:

```python
                    wait_notify, peek_pending = _make_broker_callables(
                        broker_session, broker)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_channel_adapter.py -v`
Expected: PASS — all tests (existing `watch_loop` tests still pass; they use fake
callables and never touch HTTP).

- [ ] **Step 7: Commit**

```bash
git add src/agent_agora/channel_adapter.py tests/test_channel_adapter.py
git commit -m "feat: switch agora-channel adapter to GET /channel/wait HTTP endpoint"
```

---

## Task 6: Switch `AgoraBot` SDK to HTTP `wait_notify`

**Files:**
- Modify: `src/agent_agora/bot.py` (`run` ~line 134-149; imports ~line 21-33)
- Test: `tests/test_v4_bot_sdk.py`

- [ ] **Step 1: Update the failing test**

In `tests/test_v4_bot_sdk.py`, the test `test_run_uses_wait_notify_then_flush` asserts the
bot calls the `agora.wait_notify` MCP tool. Replace that whole test (lines ~199-229,
the `_StopLoop` class plus the test) with:

```python
class _StopLoop(Exception):
    pass


@pytest.mark.asyncio
async def test_run_uses_http_wait_then_flush(monkeypatch):
    """run()은 GET /channel/wait HTTP 엔드포인트로 도착을 기다린 뒤 agora.flush를
    호출한다. agora.wait_notify MCP 도구는 더 이상 호출하지 않는다."""
    seen_wait_calls: list = []
    seen_flush_calls: list = []

    async def fake_http_wait(self, instance_id, timeout_ms):
        seen_wait_calls.append((instance_id, timeout_ms))
        if len(seen_wait_calls) >= 2:
            raise _StopLoop()  # 루프 탈출
        return {"instance_id": instance_id, "pending": 0, "sources": []}

    monkeypatch.setattr("agent_agora.bot.AgoraBot._http_wait", fake_http_wait)

    class _FlushSession(FakeSession):
        async def call_tool(self, name, args):
            if name == "agora.flush":
                seen_flush_calls.append(args)
                return _FakeResult({"commands": []})
            if name == "agora.wait_notify":
                raise AssertionError(
                    "run()은 agora.wait_notify MCP 도구를 호출하면 안 된다")
            return await super().call_tool(name, args)

    bot = _ReturnBot()
    bot._session = _FlushSession()
    with pytest.raises(_StopLoop):
        await bot.run()
    assert seen_wait_calls
    assert all(t == _ReturnBot.WAIT_TIMEOUT_MS for _, t in seen_wait_calls)
    assert len(seen_flush_calls) >= 1


def test_channel_wait_url_derived_from_mcp_url():
    """봇의 /channel/wait URL은 MCP URL에서 /mcp 꼬리를 떼어 유도된다."""
    bot = _ReturnBot(url="http://127.0.0.1:8420/mcp")
    assert bot._channel_wait_url() == "http://127.0.0.1:8420/channel/wait"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.13 -m pytest tests/test_v4_bot_sdk.py -v -k "http_wait or channel_wait"`
Expected: FAIL — `AttributeError: ... has no attribute '_http_wait'` /
`_channel_wait_url`.

- [ ] **Step 3: Add the HTTP wait machinery to `AgoraBot`**

In `src/agent_agora/bot.py`, add `import httpx` to the imports (after the
`from mcp.client.streamable_http import streamable_http_client` line):

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import httpx
```

Add these two methods to the `AgoraBot` class. Place them right after the `now()`
staticmethod (before `async def emit`):

```python
    def _channel_wait_url(self) -> str:
        """GET /channel/wait의 전체 URL. self.url(MCP 엔드포인트)에서 /mcp
        꼬리를 떼어 같은 호스트·포트의 채널 경로를 유도한다."""
        base = self.url.rstrip("/")
        if base.endswith("/mcp"):
            base = base[: -len("/mcp")]
        return base.rstrip("/") + "/channel/wait"

    async def _http_wait(self, instance_id: str, timeout_ms: int) -> dict:
        """GET /channel/wait로 인박스 도착을 long-poll한다.

        blocking long-poll 도구 agora.wait_notify의 대체 경로 — 봇은 MCP 도구
        표면 대신 이 HTTP 엔드포인트를 쓴다. 호출 실패는 봇을 죽이지 않는다:
        {error:...}를 반환하고, 이어지는 flush가 인박스를 드레인하고
        last_seen heartbeat를 갱신한다."""
        try:
            async with httpx.AsyncClient(timeout=None) as http:
                resp = await http.get(
                    self._channel_wait_url(),
                    params={"instance_id": instance_id,
                            "timeout_ms": timeout_ms})
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001 — 봇은 wait 실패에 죽지 않는다
            return {"error": f"channel/wait HTTP 호출 실패: {exc!r}"}
```

- [ ] **Step 4: Use `_http_wait` in `run()`**

In `src/agent_agora/bot.py`, the `run()` loop body is:

```python
        while True:
            await self.session.call_tool(
                "agora.wait_notify",
                {"instance_id": self.INSTANCE_ID,
                 "timeout_ms": self.WAIT_TIMEOUT_MS})
            res = _result_json(await self.session.call_tool("agora.flush", {}))
            for cmd in res.get("commands", []):
                await self._dispatch(cmd)
```

Replace the `wait_notify` MCP call with `_http_wait`:

```python
        while True:
            await self._http_wait(self.INSTANCE_ID, self.WAIT_TIMEOUT_MS)
            res = _result_json(await self.session.call_tool("agora.flush", {}))
            for cmd in res.get("commands", []):
                await self._dispatch(cmd)
```

Also update the `run()` docstring's first sentence — change `wait_notify로 도착을
기다리고` to `GET /channel/wait로 도착을 기다리고`:

```python
    async def run(self) -> None:
        """수신 루프. GET /channel/wait HTTP 엔드포인트로 도착을 기다리고
        (event-driven — 구독 스키마 메시지가 라우팅되면 즉시 리턴), flush로
        인박스를 드레인한다. 메시지 없이 heartbeat 주기로 wait가 리턴해도
        이어지는 flush가 last_seen을 갱신해 dead-bot sweep용 heartbeat를
        유지한다."""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.13 -m pytest tests/test_v4_bot_sdk.py -v`
Expected: PASS — all tests.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/bot.py tests/test_v4_bot_sdk.py
git commit -m "feat: switch AgoraBot SDK receive loop to GET /channel/wait"
```

---

## Task 7: Update `docs/channel-mode.md`

**Files:**
- Modify: `docs/channel-mode.md`

- [ ] **Step 1: Update the flow description**

In `docs/channel-mode.md`, the "동작 흐름" section step 1 says:

```
1. **idle** — 워커 턴이 없다. 어댑터는 서버의 `agora.wait_notify`를 long-poll한다.
```

Change to:

```
1. **idle** — 워커 턴이 없다. 어댑터는 서버의 `GET /channel/wait` HTTP
   엔드포인트를 long-poll한다. (`agora.wait_notify` MCP 도구는 워커 도구
   표면에서 제거됐다 — 어댑터·봇은 HTTP 경로를 쓴다.)
```

In the same section's ASCII diagram, the line `agora.wait_notify 해제` becomes
`GET /channel/wait 해제`.

- [ ] **Step 2: Verify the doc reads correctly**

Run: `py -3.13 -m pytest tests/ -q` (full suite — confirm nothing broke)
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add docs/channel-mode.md
git commit -m "docs: update channel-mode flow for GET /channel/wait"
```

---

## Final verification

- [ ] Run the full suite: `py -3.13 -m pytest tests/ -v`. All pass.
- [ ] Confirm `agora.wait_notify` is NOT in the default tool surface and IS present with
  `--add-wait` (`tests/test_v4_wait_notify.py`).
- [ ] Confirm the adapter and SDK no longer call the `agora.wait_notify` MCP tool.
