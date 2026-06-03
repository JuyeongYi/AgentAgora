# 파일 공유 일원화 (agora-channel file.put/get) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 파일 공유를 브로커 HTTP `/files`(중앙 저장+송신) 단일 경로로 일원화하고, 워커는 `agora-channel`의 `file.put`/`file.get` MCP 도구로만 파일을 다룬다(분산·OS 무관). 단일머신 전용 로컬-복사 도구(`agora.share_file`/`fetch_file`)는 폐기.

**Architecture:** `agora-channel`(워커 PC에서 도는 stdio MCP 서버)이 워커 로컬 파일을 IO하면서 브로커 HTTP `/files`로 전송한다. `Server.run`(표준 도구 처리)으로 전환하되, `run`이 write 스트림을 인자로 받으므로 같은 `write_stream`으로 백그라운드 watch가 claude/channel 알림을 emit한다(MCP 서버 1개 유지). HTTP 글루는 `_broker_http`에 추가.

**Tech Stack:** Python 3.13, MCP SDK(lowlevel `Server`/`stdio_server`), httpx, pytest. 브랜치 `feat/file-sharing-unification`. 테스트는 `.venv/Scripts/python.exe -m pytest`.

---

## File Structure

| 파일 | 책임 |
|------|------|
| `src/agent_agora/_broker_http.py` | `/channel/wait`에 더해 `/files` 업로드(`upload_file`)·다운로드(`download_file`) httpx 헬퍼 |
| `src/agent_agora/files/routes.py` | 다운로드 응답에 `Content-Disposition: filename`(어댑터가 원래 이름 추출용) |
| `src/agent_agora/channel_adapter.py` | `file.put`/`file.get` 도구 등록 + `Server.run` 전환 + write_stream 공유 emit |
| `src/agent_agora/server.py` | `agora.share_file`/`agora.fetch_file` 제거 |
| `tests/test_broker_http_files.py` | upload/download 헬퍼 단위 |
| `tests/test_channel_file_tools.py` | file.put/get 도구 핸들러 단위(브로커 mock) |
| `tests/test_file_sharing.py` | share_file/fetch_file 제거 반영(기존) |

---

### Task 1: `_broker_http` 파일 업로드/다운로드 헬퍼

**Files:**
- Modify: `src/agent_agora/_broker_http.py`
- Test: `tests/test_broker_http_files.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broker_http_files.py
import pytest
import httpx
from agent_agora import _broker_http


def _base(broker_mcp="http://h:8420/mcp"):
    return _broker_http.channel_wait_base_url(broker_mcp)  # http://h:8420


@pytest.mark.anyio
async def test_upload_file_posts_bytes_with_headers(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"file_id": "fid", "name": "a.txt", "size": 3, "sha256": "x"}

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, headers=None):
            captured.update(url=url, content=content, headers=headers)
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    handle = await _broker_http.upload_file(
        "http://h:8420/mcp", instance_id="W1", name="a.txt", data=b"abc")
    assert handle["file_id"] == "fid"
    assert captured["url"].endswith("/files")
    assert captured["headers"]["X-Agora-Instance-Id"] == "W1"
    assert captured["headers"]["X-Agora-File-Name"] == "a.txt"
    assert captured["content"] == b"abc"


@pytest.mark.anyio
async def test_download_file_returns_bytes_and_name(monkeypatch):
    class FakeResp:
        status_code = 200
        content = b"hello"
        headers = {"content-disposition": 'attachment; filename="report.pdf"'}
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    data, name = await _broker_http.download_file(
        "http://h:8420/mcp", instance_id="W1", file_id="fid")
    assert data == b"hello"
    assert name == "report.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_broker_http_files.py -q`
Expected: FAIL — `AttributeError: module 'agent_agora._broker_http' has no attribute 'upload_file'`

(테스트가 `anyio` 마커를 쓰면 `pytest-asyncio`의 `asyncio` 마커로 바꾸거나, 동기 래퍼로 `asyncio.run`을 쓴다. 이 저장소는 `asyncio_mode=auto`이므로 `async def test_...`만으로 충분 — `@pytest.mark.anyio` 줄을 제거하고 `async def`만 남길 것.)

- [ ] **Step 3: Write minimal implementation**

`_broker_http.py` 끝에 추가:
```python
def files_base_url(broker_mcp_url: str) -> str:
    """브로커 /files 베이스 URL(= channel_wait_base_url + /files)."""
    return channel_wait_base_url(broker_mcp_url) + "/files"


async def upload_file(broker_mcp_url: str, *, instance_id: str, name: str,
                      data: bytes) -> dict:
    """워커 바이트를 브로커 POST /files로 업로드하고 핸들(dict)을 반환한다."""
    url = files_base_url(broker_mcp_url)
    headers = {"X-Agora-Instance-Id": instance_id, "X-Agora-File-Name": name}
    async with httpx.AsyncClient(timeout=None) as http:
        resp = await http.post(url, content=data, headers=headers)
        resp.raise_for_status()
        out = resp.json()
        return out if isinstance(out, dict) else {}


async def download_file(broker_mcp_url: str, *, instance_id: str,
                        file_id: str) -> tuple[bytes, str]:
    """브로커 GET /files/<id>에서 바이트와 원래 파일명(Content-Disposition)을 받는다."""
    url = files_base_url(broker_mcp_url) + "/" + file_id
    headers = {"X-Agora-Instance-Id": instance_id}
    async with httpx.AsyncClient(timeout=None) as http:
        resp = await http.get(url, headers=headers)
        resp.raise_for_status()
        name = _filename_from_disposition(resp.headers.get("content-disposition"))
        return resp.content, name


def _filename_from_disposition(disp: str | None) -> str:
    """Content-Disposition에서 filename 추출. 없으면 빈 문자열."""
    if not disp:
        return ""
    for part in disp.split(";"):
        part = part.strip()
        if part.lower().startswith("filename="):
            return part[len("filename="):].strip().strip('"')
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_broker_http_files.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/_broker_http.py tests/test_broker_http_files.py
git commit -m "feat(files): _broker_http에 /files 업로드·다운로드 헬퍼"
```

---

### Task 2: 다운로드 응답에 파일명(Content-Disposition)

**Files:**
- Modify: `src/agent_agora/files/routes.py` (download 함수)
- Test: `tests/test_file_sharing.py` (다운로드 헤더 확인 추가)

- [ ] **Step 1: Write the failing test**

`tests/test_file_sharing.py`에 추가(기존 업로드/다운로드 테스트 픽스처 재사용 — 없으면 라이브 TestClient 패턴):
```python
def test_download_includes_filename_disposition(files_test_client):
    # files_test_client: POST /files로 'r.txt' 업로드 후 file_id 확보하는 기존 픽스처
    client, file_id = files_test_client  # (TestClient, 업로드된 file_id)
    r = client.get(f"/files/{file_id}", headers={"X-Agora-Instance-Id": "W1"})
    assert r.status_code == 200
    assert "filename" in r.headers.get("content-disposition", "")
```
(기존 `test_file_sharing.py`의 다운로드 테스트가 있으면 그 안에 `content-disposition` 단언만 추가. 픽스처 이름은 실제 파일에 맞춘다.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_sharing.py -k disposition -q`
Expected: FAIL — `content-disposition` 헤더 없음

- [ ] **Step 3: Write minimal implementation**

`files/routes.py`의 `download` 마지막 반환을 수정:
```python
        return FileResponse(
            path,
            media_type=meta["content_type"] or "application/octet-stream",
            filename=meta["name"],   # Content-Disposition: attachment; filename="..."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_sharing.py -k disposition -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/files/routes.py tests/test_file_sharing.py
git commit -m "feat(files): 다운로드에 Content-Disposition filename(어댑터 inbox 이름용)"
```

---

### Task 3: `agora-channel`에 `file.put`/`file.get` 도구 + `Server.run` 전환

**Files:**
- Modify: `src/agent_agora/channel_adapter.py`
- Test: `tests/test_channel_file_tools.py`

핵심: `_serve_channel`을 `Server.run`(도구 처리)으로 전환하되, `stdio_server()`의 `write_stream`을 보유해 백그라운드 watch가 같은 스트림으로 emit한다.

- [ ] **Step 1: Write the failing test (도구 핸들러 — 브로커 HTTP를 monkeypatch)**

```python
# tests/test_channel_file_tools.py
import json
import asyncio
import pytest
from pathlib import Path
from agent_agora import channel_adapter as ca


async def test_file_put_uploads_and_returns_handle(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_bytes(b"abc")

    async def fake_upload(broker, *, instance_id, name, data):
        assert data == b"abc" and name == "a.txt" and instance_id == "W1"
        return {"file_id": "fid", "name": "a.txt", "size": 3}

    monkeypatch.setattr(ca._broker_http, "upload_file", fake_upload)
    call = ca._make_file_call_tool("http://h:8420/mcp", "W1")
    result = await call("file.put", {"path": str(src)})
    data = json.loads(result[0].text)
    assert data["file_id"] == "fid"


async def test_file_get_downloads_to_inbox(tmp_path, monkeypatch):
    async def fake_download(broker, *, instance_id, file_id):
        return b"hello", "report.txt"

    monkeypatch.setattr(ca._broker_http, "download_file", fake_download)
    monkeypatch.chdir(tmp_path)
    call = ca._make_file_call_tool("http://h:8420/mcp", "W1")
    result = await call("file.get", {"file_id": "fid"})
    data = json.loads(result[0].text)
    saved = Path(data["path"])
    assert saved.read_bytes() == b"hello"
    assert saved == tmp_path / "agora-inbox" / "report.txt"


async def test_file_get_existing_dest_errors(tmp_path, monkeypatch):
    async def fake_download(broker, *, instance_id, file_id):
        return b"hello", "report.txt"

    monkeypatch.setattr(ca._broker_http, "download_file", fake_download)
    inbox = tmp_path / "agora-inbox"
    inbox.mkdir()
    (inbox / "report.txt").write_bytes(b"old")
    monkeypatch.chdir(tmp_path)
    call = ca._make_file_call_tool("http://h:8420/mcp", "W1")
    result = await call("file.get", {"file_id": "fid"})
    data = json.loads(result[0].text)
    assert "file_exists" in data["error"]
    assert (inbox / "report.txt").read_bytes() == b"old"   # 덮어쓰지 않음
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_channel_file_tools.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_make_file_call_tool'`

- [ ] **Step 3: Write minimal implementation**

`channel_adapter.py` 상단 import에 추가:
```python
import json
import os
from pathlib import Path

from agent_agora import _broker_http
from mcp.types import TextContent, Tool
```

도구 정의 + 핸들러 팩토리 추가(파일 상단의 글루 영역, `_serve_channel` 위):
```python
_FILE_TOOLS = [
    Tool(name="file.put",
         description="Upload a local file to the broker store. Returns {file_id, name, size, sha256}. "
                     "Dispatch the file_id in a file_share message.",
         inputSchema={"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"]}),
    Tool(name="file.get",
         description="Download a shared file by file_id. Saves to dest_path, or ./agora-inbox/<name> "
                     "if omitted. Errors (file_exists) if the destination already exists.",
         inputSchema={"type": "object",
                      "properties": {"file_id": {"type": "string"},
                                     "dest_path": {"type": "string"}},
                      "required": ["file_id"]}),
]


def _make_file_call_tool(broker: str, instance_id: str):
    """file.put/file.get을 처리하는 call_tool 핸들러를 만든다."""
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        def out(obj) -> list[TextContent]:
            return [TextContent(type="text", text=json.dumps(obj, ensure_ascii=False))]
        try:
            if name == "file.put":
                path = Path(arguments["path"])
                data = path.read_bytes()           # 워커 로컬 파일
                handle = await _broker_http.upload_file(
                    broker, instance_id=instance_id, name=path.name, data=data)
                return out(handle)
            if name == "file.get":
                file_id = arguments["file_id"]
                dest = arguments.get("dest_path")
                data, remote_name = await _broker_http.download_file(
                    broker, instance_id=instance_id, file_id=file_id)
                target = (Path(dest) if dest
                          else Path("agora-inbox") / (remote_name or file_id))
                if target.exists():
                    return out({"error": f"file_exists: '{target.as_posix()}'에 파일이 "
                                          f"이미 있습니다. dest_path로 다른 위치를 지정하거나 "
                                          f"기존 파일을 옮기세요."})
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                return out({"path": target.as_posix(), "name": remote_name,
                            "size": len(data)})
            return out({"error": f"unknown tool: {name}"})
        except FileNotFoundError as e:
            return out({"error": f"file not found: {e}"})
        except Exception as e:  # noqa: BLE001 — 도구 에러는 워커에 JSON으로 전달
            return out({"error": f"{type(e).__name__}: {e}"})

    return call_tool
```

`_serve_channel`을 `Server.run` + write_stream 공유 emit으로 재작성:
```python
async def _serve_channel(
    instance_id: str, broker: str, wait_timeout_ms: int,
) -> None:
    """stdio 채널 서버: Server.run(file.put/get 도구) + 백그라운드 watch emit.

    Server.run이 write_stream을 인자로 받으므로, 같은 write_stream으로 watch가
    claude/channel 알림을 emit한다(서버 1개 유지, 수동 디스패치 없음)."""
    server = Server("agora-channel", instructions=CHANNEL_INSTRUCTIONS)
    file_call = _make_file_call_tool(broker, instance_id)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return list(_FILE_TOOLS)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        return await file_call(name, arguments)

    init_opts = server.create_initialization_options(
        experimental_capabilities={"claude/channel": {}})

    async with stdio_server() as (read_stream, write_stream):
        async def emit(content: str, meta: dict[str, str]) -> None:
            raw = JSONRPCNotification(
                jsonrpc="2.0",
                method="notifications/claude/channel",
                params={"content": content, "meta": meta})
            try:
                await write_stream.send(SessionMessage(message=JSONRPCMessage(raw)))
            except (anyio.ClosedResourceError, anyio.BrokenResourceError) as exc:
                raise asyncio.CancelledError from exc

        watch_task = asyncio.create_task(
            _run_watch_emit(instance_id, broker, wait_timeout_ms, emit))
        try:
            await server.run(read_stream, write_stream, init_opts)
        finally:
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                print(f"[agora-channel] watch task 종료 중 예외: {exc!r}",
                      file=sys.stderr, flush=True)
            await _unregister_from_broker(broker, instance_id)
```

`_run_watch`를 emit 콜백 기반 `_run_watch_emit`으로 교체(기존 `_run_watch`의 session/_emit 의존 제거):
```python
async def _run_watch_emit(
    instance_id: str, broker: str, wait_timeout_ms: int, emit,
) -> None:
    """브로커에 HTTP MCP 클라이언트로 붙어 watch_loop를 돌린다(emit 콜백 사용).
    연결이 끊기면 backoff 후 재연결 — 절대 크래시하지 않는다."""
    backoff = _BACKOFF_START_S
    while True:
        try:
            async with streamable_http_client(broker) as conn:
                async with ClientSession(conn[0], conn[1]) as broker_session:
                    await broker_session.initialize()
                    backoff = _BACKOFF_START_S
                    wait_notify, peek_pending = _make_broker_callables(
                        broker_session, broker)
                    await watch_loop(
                        instance_id, wait_notify, peek_pending, emit,
                        wait_timeout_ms=wait_timeout_ms)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[agora-channel] 브로커 연결 실패 ({exc!r}); {backoff:.0f}s 후 재시도",
                  file=sys.stderr, flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_CAP_S)
```
기존 `_run_watch`(session 인자)·`_emit`(session 인자)은 제거하거나, 다른 곳에서 import되면(테스트) 유지 여부 확인 후 정리.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_channel_file_tools.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 채널 어댑터 기존 테스트 회귀 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_channel_adapter.py -q` (있으면)
Expected: PASS. `_run_watch`/`_emit` 시그니처 변경에 걸리는 테스트가 있으면 `_run_watch_emit`/emit 콜백 기준으로 수정.

- [ ] **Step 6: Commit**

```bash
git add src/agent_agora/channel_adapter.py tests/test_channel_file_tools.py
git commit -m "feat(channel): file.put/file.get 도구 + Server.run 전환(write_stream 공유 emit)"
```

---

### Task 4: `server.py`에서 `agora.share_file`/`agora.fetch_file` 제거

**Files:**
- Modify: `src/agent_agora/server.py:669-708` (share_file/fetch_file 블록)
- Test: `tests/test_file_sharing.py` (해당 도구 테스트 제거/조정)

- [ ] **Step 1: 기존 테스트에서 share_file/fetch_file 의존 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_sharing.py -q`
Expected: 현재 PASS. share_file/fetch_file 도구를 호출하는 테스트를 식별(grep `share_file`/`fetch_file` in tests).

- [ ] **Step 2: 도구 블록 제거**

`server.py`에서 다음 블록 전체 삭제(`if file_store is not None:` 아래 두 도구):
```python
    if file_store is not None:
        @mcp.tool(name="agora.share_file")
        async def agora_share_file(...):
            ...
        @mcp.tool(name="agora.fetch_file")
        async def agora_fetch_file(...):
            ...
```
(파일 저장소 자체와 HTTP `/files`는 그대로 — MCP 로컬-복사 도구만 제거.)
`shutil`/`os`/`Path` import가 이 블록에서만 쓰였는지 확인하고, 다른 사용처 없으면 정리.

- [ ] **Step 3: share_file/fetch_file 테스트 제거**

`tests/test_file_sharing.py`에서 `agora.share_file`/`agora.fetch_file` 도구를 호출하는 테스트 함수를 삭제(HTTP `/files` 업로드·다운로드 테스트는 유지). 파일 공유의 정본은 이제 HTTP + 채널 도구다.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_sharing.py -q`
Expected: PASS (share_file/fetch_file 테스트 제거 후, HTTP /files 테스트만 녹색)

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/server.py tests/test_file_sharing.py
git commit -m "refactor(files): MCP agora.share_file/fetch_file(로컬복사) 제거 — HTTP/채널로 일원화"
```

---

### Task 5: 전체 스위트 + 문서

**Files:**
- Modify: `docs/file-sharing.md` (있으면 — 일원화 반영), `docs/superpowers/specs/2026-06-03-file-sharing-unification-design.md`(상태)

- [ ] **Step 1: 전체 스위트**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 전부 PASS. share_file/fetch_file 제거·채널 어댑터 변경에 따른 회귀 0.

- [ ] **Step 2: 문서 갱신**

`docs/file-sharing.md`(있으면)에서 `agora.share_file`/`fetch_file` 설명을 `file.put`/`file.get`(채널 도구) + HTTP `/files`로 교체. 흐름: `file.put(path)` → file_id → `agora.dispatch(file_share)` → 수신측 `file.get(file_id)` → `./agora-inbox/<name>`. spec 상태 줄을 "구현 완료"로.

- [ ] **Step 3: Commit**

```bash
git add docs/file-sharing.md docs/superpowers/specs/2026-06-03-file-sharing-unification-design.md
git commit -m "docs(files): 파일 공유 일원화(file.put/get) 사용법 + spec 상태"
```

---

## Self-Review

**Spec coverage:**
- 구조/위치(_broker_http, routes, channel_adapter, server) → Task 1·2·3·4 ✅
- 인터페이스 file.put/get → Task 3 ✅
- 데이터 흐름(put→dispatch→get) → Task 3·문서 ✅
- 일원화(HTTP /files 단일, 로컬복사 폐기) → Task 4 ✅
- inbox 기본 경로 + file_exists 충돌 에러 → Task 3 테스트 ✅
- 수신 파일명(Content-Disposition) → Task 2 ✅
- 도구+알림 공존(Server.run + write_stream 공유) → Task 3 ✅
- 테스트 → Task 1·3·4 + 통합 Task 5 ✅

**Placeholder scan:** Task 2 픽스처 이름·Task 4 grep 대상은 "실제 파일에 맞춘다"로 위임 — 기존 테스트 구조 의존이라 구현 시 확인. 그 외 코드 스텝은 완전 코드.

**Type consistency:** `upload_file(broker, *, instance_id, name, data)`·`download_file(broker, *, instance_id, file_id)→(bytes, name)`·`_make_file_call_tool(broker, instance_id)→call_tool(name, arguments)→[TextContent]`·`_run_watch_emit(instance_id, broker, wait_timeout_ms, emit)` — Task 1·3 정의와 호출 일치. emit 콜백 시그니처 `emit(content, meta)`는 `watch_loop`/`_serve_channel`과 일치.

**구현 시 확인:** (1) `tests/test_channel_adapter.py` 등이 기존 `_run_watch`/`_emit`(session 인자)을 import/테스트하면 `_run_watch_emit`로 갱신. (2) `pytest-asyncio asyncio_mode=auto`라 async 테스트에 마커 불필요 — Step 1 테스트의 `@pytest.mark.anyio`는 제거. (3) `Server.run`이 도구 미지원 클라이언트와도 핸드셰이크되는지(claude/channel capability와 무관하게 tools 노출) 통합에서 확인.
