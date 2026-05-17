# 아고라 파일 공유 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에이전트 간 파일 공유 — 서버 측 파일 스토어 + 워커별 r/w 권한 정책 + MCP·HTTP 전송 경로.

**Architecture:** 서버가 `.agentagora/files/` 스토어와 `files` 메타 테이블을 보유한다. `FileStore`가 저장/조회/GC를, `FilePolicy`가 워커별 gitignore 패턴 권한을 담당한다. 공유자는 `agora.share_file`로 파일을 스토어에 넣고 핸들을 받아 `file_share` 메시지로 보내며, 수신자는 `agora.fetch_file`로 가져간다. 원격은 HTTP `POST/GET /files`. 응집된 한 기능이라 단일 플랜 — 8개 순차 태스크.

**Tech Stack:** Python 3.13, Starlette, SQLite, `pathspec`(신규 의존성), pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 무시(pytest 정답).

spec: `docs/superpowers/specs/2026-05-17-agora-file-sharing-design.md`.

---

### Task 1: `files` 테이블 + `FileStore`

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Modify: `src/agent_agora/errors.py`
- Create: `src/agent_agora/file_store.py`
- Test: `tests/test_file_store.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_file_store.py`:

```python
"""FileStore — 파일 스토어 저장/조회/GC."""
from __future__ import annotations

import datetime

import pytest

from agent_agora.errors import AgoraError
from agent_agora.file_store import FileStore
from agent_agora.persistence import Persistence


def _store(tmp_path, max_bytes=104_857_600):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    return FileStore(tmp_path, p, max_bytes=max_bytes), p


def test_store_path_copies_and_records(tmp_path):
    store, _ = _store(tmp_path)
    src = tmp_path / "report.md"
    src.write_text("hello", encoding="utf-8")
    h = store.store_path(src, "report.md", "Coder1")
    assert set(h) == {"file_id", "name", "size", "sha256"}
    assert h["name"] == "report.md" and h["size"] == 5
    assert src.read_text(encoding="utf-8") == "hello"  # 원본 보존
    meta = store.meta(h["file_id"])
    assert meta["registered_by"] == "Coder1" and meta["sha256"] == h["sha256"]
    assert store.path_of(h["file_id"]).read_bytes() == b"hello"


def test_store_bytes(tmp_path):
    store, _ = _store(tmp_path)
    h = store.store_bytes(b"abc", "x.txt", "Bot1")
    assert h["size"] == 3
    assert store.path_of(h["file_id"]).read_bytes() == b"abc"


def test_too_large_rejected(tmp_path):
    store, _ = _store(tmp_path, max_bytes=4)
    src = tmp_path / "big.bin"
    src.write_bytes(b"12345")
    with pytest.raises(AgoraError) as ei:
        store.store_path(src, "big.bin", "Coder1")
    assert ei.value.code == "file_too_large"


def test_meta_and_path_unknown(tmp_path):
    store, _ = _store(tmp_path)
    assert store.meta("nope") is None
    assert store.path_of("nope") is None


def test_gc_removes_old(tmp_path):
    store, p = _store(tmp_path)
    h = store.store_bytes(b"old", "old.txt", "Coder1")
    future = (datetime.datetime.now(datetime.timezone.utc)
              + datetime.timedelta(days=1)).isoformat()
    removed = store.gc(future)
    assert removed == 1
    assert store.meta(h["file_id"]) is None
    assert store.path_of(h["file_id"]) is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_store.py -q`
Expected: FAIL — `file_store` 모듈·`files` 테이블 없음.

- [ ] **Step 3: `errors.py`에 파일 에러 코드 추가**

`src/agent_agora/errors.py`의 `ERROR_MESSAGES`에 comm-matrix codes 다음 줄들 추가:

```python
    "file_too_large": "[agora] 파일이 너무 큽니다: {size} bytes (상한 {limit}).",
    "file_upload_denied": "[agora] file_upload_denied: {worker}는 '{name}'을 공유할 수 없습니다 (파일 권한 정책).",
    "file_download_denied": "[agora] file_download_denied: {worker}는 '{name}'을 받을 수 없습니다 (파일 권한 정책).",
    "unknown_file": "[agora] file_id '{file_id}'를 찾을 수 없습니다.",
    "file_policy_invalid": "[agora] file-policy.json 오류: {detail}",
```

- [ ] **Step 4: `persistence.py` — `files` 테이블 + 메서드**

`_SCHEMA_V1` 문자열 끝(`bot_subscriptions` 인덱스 다음)에 추가:

```sql
CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  content_type TEXT,
  registered_by TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at);
```

(`migrate()`는 `executescript`로 `IF NOT EXISTS`라 기존 DB도 다음 기동에 테이블이 생긴다 — 버전 범프 불필요.)

`Persistence` 클래스에 메서드 추가:

```python
    _FILE_COLS = ("file_id", "name", "size", "sha256", "content_type",
                  "registered_by", "created_at")

    def save_file(self, file_id, name, size, sha256, content_type,
                  registered_by, created_at) -> None:
        self._conn.execute(
            "INSERT INTO files (file_id,name,size,sha256,content_type,"
            "registered_by,created_at) VALUES (?,?,?,?,?,?,?)",
            (file_id, name, size, sha256, content_type, registered_by, created_at))

    def get_file(self, file_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT file_id,name,size,sha256,content_type,registered_by,created_at "
            "FROM files WHERE file_id=?", (file_id,)).fetchone()
        return dict(zip(self._FILE_COLS, row)) if row is not None else None

    def files_before(self, cutoff_iso: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT file_id FROM files WHERE created_at < ?", (cutoff_iso,)).fetchall()
        return [r[0] for r in rows]

    def delete_file(self, file_id: str) -> None:
        self._conn.execute("DELETE FROM files WHERE file_id=?", (file_id,))
```

- [ ] **Step 5: `file_store.py` 작성**

`src/agent_agora/file_store.py`:

```python
"""파일 스토어 — .agentagora/files/ 바이트 저장 + files 메타 테이블 관리."""
from __future__ import annotations

import datetime
import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from agent_agora.errors import AgoraError
from agent_agora.persistence import Persistence

_DEFAULT_MAX_BYTES = 104_857_600  # 100 MB


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class FileStore:
    """공유 파일 바이트는 agora_dir/files/<file_id>에, 메타는 SQLite files 테이블에."""

    def __init__(self, agora_dir: Path, persistence: Persistence, *,
                 max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._dir = agora_dir / "files"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._persistence = persistence
        self._max_bytes = max_bytes

    def _record(self, file_id, name, size, sha, ctype, registered_by) -> dict:
        self._persistence.save_file(file_id, name, size, sha, ctype,
                                    registered_by, _now_iso())
        return {"file_id": file_id, "name": name, "size": size, "sha256": sha}

    def store_path(self, src: Path, name: str, registered_by: str | None) -> dict:
        """로컬 파일 src를 스토어에 *복사*(원본 보존)하고 핸들을 반환한다."""
        size = src.stat().st_size
        if size > self._max_bytes:
            raise AgoraError("file_too_large", size=size, limit=self._max_bytes)
        file_id = str(uuid.uuid4())
        dest = self._dir / file_id
        shutil.copyfile(src, dest)
        return self._record(file_id, name, size, _sha256_file(dest),
                            mimetypes.guess_type(name)[0], registered_by)

    def store_bytes(self, data: bytes, name: str, registered_by: str | None) -> dict:
        """바이트를 스토어에 저장하고 핸들을 반환한다 (HTTP 업로드용)."""
        if len(data) > self._max_bytes:
            raise AgoraError("file_too_large", size=len(data), limit=self._max_bytes)
        file_id = str(uuid.uuid4())
        (self._dir / file_id).write_bytes(data)
        return self._record(file_id, name, len(data), hashlib.sha256(data).hexdigest(),
                            mimetypes.guess_type(name)[0], registered_by)

    def meta(self, file_id: str) -> dict | None:
        return self._persistence.get_file(file_id)

    def path_of(self, file_id: str) -> Path | None:
        """스토어 내 파일 경로. 메타·바이트 둘 다 있어야 반환, 아니면 None."""
        if self._persistence.get_file(file_id) is None:
            return None
        p = self._dir / file_id
        return p if p.is_file() else None

    def gc(self, cutoff_iso: str) -> int:
        """created_at < cutoff_iso 인 파일을 바이트·메타 모두 삭제. 삭제 수 반환."""
        victims = self._persistence.files_before(cutoff_iso)
        for fid in victims:
            (self._dir / fid).unlink(missing_ok=True)
            self._persistence.delete_file(fid)
        return len(victims)
```

- [ ] **Step 6: 테스트 통과 + 전체 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_store.py -q`
Expected: 5개 PASS.
Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/persistence.py src/agent_agora/errors.py src/agent_agora/file_store.py tests/test_file_store.py
git commit -m "feat: 파일 스토어 — files 테이블 + FileStore"
```

---

### Task 2: `file_share` 빌트인 스키마

**Files:**
- Modify: `src/agent_agora/schemas.py`
- Modify: `src/agent_agora/default_schemas.jsonl`
- Modify: `src/agent_agora/__main__.py`
- Test: `tests/test_file_store.py` (스키마 상수 검증)

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_file_store.py`에 추가:

```python
from agent_agora.schemas import FILE_SHARE_NAME, FILE_SHARE_BODY


def test_file_share_schema_constant():
    assert FILE_SHARE_NAME == "file_share"
    props = FILE_SHARE_BODY["properties"]
    assert props["msgtype"]["const"] == "file_share"
    for k in ("file_id", "name", "size", "sha256", "from", "ts"):
        assert k in props
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_store.py -k file_share -q`
Expected: FAIL — `FILE_SHARE_NAME` 미정의.

- [ ] **Step 3: `schemas.py`에 상수 추가**

`src/agent_agora/schemas.py`의 `SCHEMA_CONFLICT_BODY` 정의 다음에 추가:

```python
FILE_SHARE_NAME = "file_share"
FILE_SHARE_BODY: dict[str, Any] = {
    "type": "object",
    "required": ["msgtype", "file_id", "name", "size", "sha256", "from", "ts"],
    "properties": {
        "msgtype": {"type": "string", "const": "file_share"},
        "file_id": {"type": "string"},
        "name": {"type": "string"},
        "size": {"type": "integer"},
        "sha256": {"type": "string"},
        "from": {"type": "string"},
        "ts": {"type": "string", "format": "date-time"},
        "note": {"type": "string"},
    },
    "additionalProperties": False,
}
```

- [ ] **Step 4: `default_schemas.jsonl`에 등재**

`src/agent_agora/default_schemas.jsonl` 끝에 한 줄 추가 — `body`는 `FILE_SHARE_BODY`와 동일한 객체의 compact JSON, `kind`는 `conversation`:

```json
{"name":"file_share","kind":"conversation","purpose":"파일 공유 핸들 통지 — share_file로 얻은 핸들을 수신자에 전달.","body":{"type":"object","required":["msgtype","file_id","name","size","sha256","from","ts"],"properties":{"msgtype":{"type":"string","const":"file_share"},"file_id":{"type":"string"},"name":{"type":"string"},"size":{"type":"integer"},"sha256":{"type":"string"},"from":{"type":"string"},"ts":{"type":"string","format":"date-time"},"note":{"type":"string"}},"additionalProperties":false}}
```

`body`가 `FILE_SHARE_BODY`와 의미상 동일해야 한다(startup 재등록이 idempotent 하려면) — Python `==`로 검증할 것.

- [ ] **Step 5: `__main__.py` startup에 permanent 등록**

`src/agent_agora/__main__.py`의 startup에서 `schema_conflict`를 register하는 줄 다음에 `file_share`도 permanent 등록한다:

```python
    from agent_agora.schemas import (SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY,
                                     FILE_SHARE_NAME, FILE_SHARE_BODY)
    ...
    schema_registry.register(
        FILE_SHARE_NAME, FILE_SHARE_BODY,
        kind="conversation", purpose="파일 공유 핸들 통지")
```

(`schema_conflict` 등록 코드를 찾아 그 형태를 그대로 따른다. jsonl 로드가 먼저 `file_share`를 등록했어도 같은 body라 idempotent.)

- [ ] **Step 6: 테스트 통과 + 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS. (빌트인 스키마 개수를 하드코딩한 테스트가 있으면 7→8로 갱신 — `git grep`으로 확인.)

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/schemas.py src/agent_agora/default_schemas.jsonl src/agent_agora/__main__.py tests/test_file_store.py
git commit -m "feat: file_share 빌트인 스키마"
```

---

### Task 3: `agora.share_file` · `agora.fetch_file` MCP 도구

이 태스크는 정책 게이트 없이 도구를 만든다(FilePolicy는 Task 4·5). `create_agora_app`이 `file_store`를 받아 도구 클로저에 캡처한다.

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_file_sharing.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_file_sharing.py`. 서버 앱 fixture는 `tests/test_v4_comm_matrix.py`의 `cm_app`/`_tool`/`_FakeCtx` 패턴을 참고해 만들되 `file_store`를 노출한다(`create_agora_app`에 `file_store` 인자 추가 — Step 3). 핵심:

```python
"""파일 공유 MCP 도구·HTTP·정책 테스트."""
from __future__ import annotations

import json

import pytest

# (fixture file_app: create_agora_app으로 mcp를 만들고 Inst1·Inst2 등록,
#  (mcp, dispatcher, file_store, file_policy)를 yield — cm_app 구조 복제)


@pytest.mark.asyncio
async def test_share_then_fetch(file_app, tmp_path):
    mcp, _, file_store, _ = file_app
    src = tmp_path / "doc.md"
    src.write_text("payload", encoding="utf-8")
    r = json.loads(await _tool(mcp, "agora.share_file")(
        _FakeCtx("sess-Inst1"), path=str(src)))
    assert r["status"] == "ok"
    fid = r["handle"]["file_id"]
    dest = tmp_path / "got.md"
    r2 = json.loads(await _tool(mcp, "agora.fetch_file")(
        _FakeCtx("sess-Inst2"), file_id=fid, dest_path=str(dest)))
    assert r2["status"] == "ok"
    assert dest.read_text(encoding="utf-8") == "payload"


@pytest.mark.asyncio
async def test_fetch_unknown_file(file_app, tmp_path):
    mcp, _, _, _ = file_app
    r = json.loads(await _tool(mcp, "agora.fetch_file")(
        _FakeCtx("sess-Inst2"), file_id="nope", dest_path=str(tmp_path / "x")))
    assert "unknown_file" in r["error"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_sharing.py -q`
Expected: FAIL — 도구 미정의.

- [ ] **Step 3: `create_agora_app`에 `file_store` 인자 + 두 도구**

`server.py`의 `create_agora_app` 시그니처에 `file_store` 파라미터를 추가하고 `mcp._agora_file_store = file_store`로 노출한다(기존 `_agora_*` 속성 패턴). 두 MCP 도구를 등록한다(`agora.register_schema` 등 기존 도구 옆):

```python
    @mcp.tool(name="agora.share_file")
    async def agora_share_file(ctx: Context, path: str) -> str:
        """Share a local file through the store. Returns a handle to dispatch
        in a file_share message."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        caller = _resolve_caller(session_id, instance_registry, bot_registry)
        import os.path
        name = os.path.basename(path)
        try:
            handle = file_store.store_path(Path(path), name, caller)
        except (AgoraError, OSError) as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "ok", "handle": handle}, ensure_ascii=False)

    @mcp.tool(name="agora.fetch_file")
    async def agora_fetch_file(ctx: Context, file_id: str, dest_path: str) -> str:
        """Fetch a shared file from the store into dest_path."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        caller = _resolve_caller(session_id, instance_registry, bot_registry)
        meta = file_store.meta(file_id)
        if meta is None:
            return json.dumps({"error": str(AgoraError("unknown_file", file_id=file_id))})
        src = file_store.path_of(file_id)
        if src is None:
            return json.dumps({"error": str(AgoraError("unknown_file", file_id=file_id))})
        import shutil
        try:
            shutil.copyfile(src, dest_path)
        except OSError as e:
            return json.dumps({"error": f"fetch failed: {e}"})
        return json.dumps({"status": "ok", "name": meta["name"], "size": meta["size"]})
```

`_resolve_caller(session_id, instance_registry, bot_registry)` — 호출자 instance_id를 워커/봇 registry에서 해석하는 헬퍼. server.py에 없으면 추가한다(워커 우선, 없으면 봇, 둘 다 아니면 `session_id` 반환):

```python
def _resolve_caller(session_id, instance_registry, bot_registry) -> str:
    for reg in (instance_registry, bot_registry):
        try:
            return reg.resolve_session(session_id).instance_id
        except NotRegisteredError:
            continue
    return session_id
```

`Path` import가 server.py에 있는지 확인하고 없으면 `from pathlib import Path` 추가.

- [ ] **Step 4: `__main__.py`·테스트 fixture에서 `create_agora_app(file_store=...)` 배선**

`__main__.py`에서 `FileStore`를 생성해 `create_agora_app`에 넘긴다:

```python
    from agent_agora.file_store import FileStore
    file_store = FileStore(agora_dir, persistence)
```

`create_agora_app(...)` 호출에 `file_store=file_store` 추가. `create_agora_app`을 호출하는 다른 테스트가 깨지면(`file_store` 필수 인자) — 인자에 기본값을 두지 말고, 호출처를 갱신하거나 `tests/`의 공통 헬퍼를 고친다. `git grep create_agora_app`으로 호출처를 모두 찾는다.

- [ ] **Step 5: 테스트 통과 + 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py src/agent_agora/__main__.py tests/test_file_sharing.py tests/
git commit -m "feat: agora.share_file·agora.fetch_file MCP 도구"
```

---

### Task 4: `FilePolicy`

**Files:**
- Modify: `pyproject.toml` (`pathspec` 의존성)
- Create: `src/agent_agora/file_policy.py`
- Test: `tests/test_file_policy.py`

- [ ] **Step 1: `pathspec` 의존성 추가**

`pyproject.toml`의 `dependencies` 배열에 `"pathspec>=0.12"`를 추가하고 설치:

Run: `.venv\Scripts\python.exe -m pip install "pathspec>=0.12"`
Expected: 설치 성공.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_file_policy.py`:

```python
"""FilePolicy — 워커별 r/w gitignore 패턴 권한."""
from __future__ import annotations

import json

import pytest

from agent_agora.errors import AgoraError
from agent_agora.file_policy import FilePolicy

_POLICY = json.dumps({
    "workers": {
        "Coder1": {"r": ["*"], "w": ["*.py", "*.md", "!secret_*.py"]},
        "Reviewer1": {"r": ["*.md"], "w": []},
    },
    "fallback": {"r": ["*.txt"], "w": []},
})


def test_inactive_allows_all():
    fp = FilePolicy()
    assert fp.active is False
    assert fp.can_upload("anyone", "x.exe") is True
    assert fp.can_download("anyone", "x.exe") is True


def test_worker_upload_patterns():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_upload("Coder1", "app.py") is True
    assert fp.can_upload("Coder1", "notes.md") is True
    assert fp.can_upload("Coder1", "secret_key.py") is False  # ! negation
    assert fp.can_upload("Coder1", "data.bin") is False


def test_worker_download_patterns():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_download("Coder1", "anything.bin") is True   # r=["*"]
    assert fp.can_download("Reviewer1", "doc.md") is True
    assert fp.can_download("Reviewer1", "app.py") is False     # r=["*.md"]


def test_fallback_for_unlisted():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_download("Ghost", "readme.txt") is True   # fallback r
    assert fp.can_download("Ghost", "app.py") is False
    assert fp.can_upload("Ghost", "app.py") is False        # fallback w=[]


def test_missing_dimension_asymmetric_default():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"X": {"w": ["*.md"]}}}))
    # r 누락 → ["*"] → 전체 허용
    assert fp.can_download("X", "anything.bin") is True
    # w 명시
    assert fp.can_upload("X", "a.md") is True
    fp.load_json(json.dumps({"workers": {"Y": {"r": ["*.md"]}}}))
    # w 누락 → [] → 전부 거부
    assert fp.can_upload("Y", "a.md") is False


def test_no_fallback_unlisted_unrestricted():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"X": {"r": [], "w": []}}}))
    assert fp.can_upload("Unlisted", "x.exe") is True
    assert fp.can_download("Unlisted", "x.exe") is True


def test_load_json_rejects_bad():
    fp = FilePolicy()
    with pytest.raises(AgoraError) as ei:
        fp.load_json("not json")
    assert ei.value.code == "file_policy_invalid"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_policy.py -q`
Expected: FAIL — `file_policy` 모듈 없음.

- [ ] **Step 4: `file_policy.py` 작성**

`src/agent_agora/file_policy.py`:

```python
"""파일 공유 권한 — 워커별 r/w gitignore 패턴. .agentagora/file-policy.json.

비활성(파일 없음) 시 전원 무제한. CommMatrix와 같은 거버넌스 패턴.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pathspec

from agent_agora.errors import AgoraError


class FilePolicy:
    """워커별 파일 업/다운로드 권한. r/w는 gitignore식 패턴 목록."""

    def __init__(self) -> None:
        self._workers: dict[str, dict[str, Any]] = {}
        self._fallback: dict[str, Any] | None = None
        self.active: bool = False

    def load_json(self, text: str) -> None:
        """file-policy.json 텍스트를 파싱해 *제자리 교체*. 잘못된 구조는 AgoraError."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AgoraError("file_policy_invalid", detail=str(e)) from None
        if not isinstance(data, dict):
            raise AgoraError("file_policy_invalid", detail="최상위는 JSON 객체여야 함")
        workers = data.get("workers", {})
        if not isinstance(workers, dict):
            raise AgoraError("file_policy_invalid", detail="'workers'는 객체여야 함")
        self._workers = workers
        self._fallback = data.get("fallback")
        self.active = True

    def _entry(self, worker_id: str) -> dict[str, Any] | None:
        """워커 정책 항목. 비활성·미등재+fallback없음이면 None(무제한)."""
        if not self.active:
            return None
        return self._workers.get(worker_id, self._fallback)

    @staticmethod
    def _match(patterns: list[str], file_name: str) -> bool:
        spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
        return spec.match_file(file_name)

    def can_upload(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 업로드할 수 있는가."""
        entry = self._entry(worker_id)
        if entry is None:
            return True
        return self._match(entry.get("w", []), file_name)  # w 누락 → [] → 거부

    def can_download(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 다운로드할 수 있는가."""
        entry = self._entry(worker_id)
        if entry is None:
            return True
        return self._match(entry.get("r", ["*"]), file_name)  # r 누락 → ["*"] → 허용

    def snapshot(self) -> dict[str, Any]:
        """현재 정책 조회용 (admin GET)."""
        if not self.active:
            return {}
        return {"workers": dict(self._workers), "fallback": self._fallback}


def load_file_policy(path: Path) -> FilePolicy:
    """path의 file-policy.json을 로드. 파일이 없으면 비활성 FilePolicy(무제한)."""
    fp = FilePolicy()
    if path.exists():
        fp.load_json(path.read_text("utf-8"))
    return fp
```

- [ ] **Step 5: 테스트 통과 + 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_policy.py -q`
Expected: 7개 PASS.
Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml src/agent_agora/file_policy.py tests/test_file_policy.py
git commit -m "feat: FilePolicy — 워커별 r/w gitignore 패턴 권한"
```

---

### Task 5: 정책 게이트 배선 + startup 로드

`share_file`/`fetch_file`에 `FilePolicy` 검사를 끼우고, startup에서 `file-policy.json`을 로드한다.

**Files:**
- Modify: `src/agent_agora/server.py`
- Modify: `src/agent_agora/__main__.py`
- Test: `tests/test_file_sharing.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_file_sharing.py`에 추가. `file_app` fixture가 노출하는 `file_policy`에 정책을 로드해 게이트를 검증:

```python
@pytest.mark.asyncio
async def test_share_file_upload_denied(file_app, tmp_path):
    mcp, _, _, file_policy = file_app
    file_policy.load_json(json.dumps({"workers": {"Inst1": {"r": ["*"], "w": ["*.md"]}}}))
    src = tmp_path / "evil.exe"
    src.write_bytes(b"x")
    r = json.loads(await _tool(mcp, "agora.share_file")(
        _FakeCtx("sess-Inst1"), path=str(src)))
    assert "file_upload_denied" in r["error"]


@pytest.mark.asyncio
async def test_fetch_file_download_denied(file_app, tmp_path):
    mcp, _, file_store, file_policy = file_app
    h = file_store.store_bytes(b"data", "app.py", "Inst1")
    file_policy.load_json(json.dumps({"workers": {"Inst2": {"r": ["*.md"], "w": []}}}))
    r = json.loads(await _tool(mcp, "agora.fetch_file")(
        _FakeCtx("sess-Inst2"), file_id=h["file_id"], dest_path=str(tmp_path / "x")))
    assert "file_download_denied" in r["error"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_sharing.py -k denied -q`
Expected: FAIL — 게이트 없음.

- [ ] **Step 3: 도구에 게이트 배선**

`server.py`의 `create_agora_app`에 `file_policy` 파라미터를 추가하고 `mcp._agora_file_policy = file_policy`로 노출한다. `agora_share_file`에서 `file_store.store_path` 호출 전에:

```python
        if not file_policy.can_upload(caller, name):
            return json.dumps({"error": str(AgoraError(
                "file_upload_denied", worker=caller, name=name))})
```

`agora_fetch_file`에서 `meta`를 얻은 직후(`src` 복사 전):

```python
        if not file_policy.can_download(caller, meta["name"]):
            return json.dumps({"error": str(AgoraError(
                "file_download_denied", worker=caller, name=meta["name"]))})
```

- [ ] **Step 4: `__main__.py` startup 로드**

`__main__.py`에서 `FilePolicy`를 로드해 `create_agora_app`에 넘긴다:

```python
    from agent_agora.file_policy import load_file_policy
    file_policy = load_file_policy(agora_dir / "file-policy.json")
```

`create_agora_app(...)` 호출에 `file_policy=file_policy` 추가. `create_agora_app` 호출처(테스트 공통 헬퍼 포함)를 `git grep`으로 찾아 인자를 맞춘다.

- [ ] **Step 5: 테스트 통과 + 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py src/agent_agora/__main__.py tests/test_file_sharing.py tests/
git commit -m "feat: 파일 공유 정책 게이트 배선 + file-policy.json startup 로드"
```

---

### Task 6: HTTP `POST /files` · `GET /files/<id>`

**Files:**
- Create: `src/agent_agora/file_routes.py`
- Modify: `src/agent_agora/__main__.py`
- Test: `tests/test_file_routes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_file_routes.py` — `test_admin_routes.py`의 Starlette `TestClient` 패턴:

```python
"""파일 HTTP 엔드포인트 테스트."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.file_policy import FilePolicy
from agent_agora.file_routes import register
from agent_agora.file_store import FileStore
from agent_agora.persistence import Persistence


def _client(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    store = FileStore(tmp_path, p)
    policy = FilePolicy()
    app = Starlette()
    register(app, file_store=store, file_policy=policy)
    return TestClient(app), store


def test_upload_then_download(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/files", content=b"hello bytes",
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "doc.md"})
    assert r.status_code == 200
    fid = r.json()["file_id"]
    r2 = client.get(f"/files/{fid}", headers={"X-Agora-Instance-Id": "Reviewer1"})
    assert r2.status_code == 200
    assert r2.content == b"hello bytes"


def test_download_unknown_404(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/files/nope", headers={"X-Agora-Instance-Id": "X"})
    assert r.status_code == 404


def test_upload_denied_403(tmp_path):
    import json as _j
    client, _ = _client(tmp_path)
    client_policy_app = client  # policy 객체에 직접 로드
    # _client의 policy에 접근하려면 fixture 구조를 조정 — register에 넘긴 policy를
    # 테스트에서 보유하도록 _client가 (client, store, policy)를 반환하게 한다.
```

`_client`가 `(client, store, policy)`를 반환하도록 고치고, `test_upload_denied_403`은 `policy.load_json(...)`으로 `Coder1`의 `w`를 `["*.md"]`로 제한한 뒤 `.exe` 업로드가 403인지 검증한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_routes.py -q`
Expected: FAIL — `file_routes` 모듈 없음.

- [ ] **Step 3: `file_routes.py` 작성**

`src/agent_agora/file_routes.py`:

```python
"""파일 공유 HTTP 엔드포인트 — POST /files (업로드), GET /files/<id> (다운로드).

원격 워커용. localhost 전용·토큰 없음 — 서버 127.0.0.1 바인딩에 의존.
요청자 식별은 X-Agora-Instance-Id 헤더(auto-register와 동일).
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from agent_agora.errors import AgoraError


def register(app: Starlette, *, file_store, file_policy) -> None:
    """app에 파일 업로드·다운로드 라우트를 등록한다."""

    async def upload(request: Request) -> JSONResponse:
        worker = request.headers.get("X-Agora-Instance-Id", "")
        name = request.headers.get("X-Agora-File-Name", "upload.bin")
        if not file_policy.can_upload(worker, name):
            return JSONResponse(
                {"error": str(AgoraError("file_upload_denied", worker=worker, name=name))},
                status_code=403)
        data = await request.body()
        try:
            handle = file_store.store_bytes(data, name, worker or None)
        except AgoraError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(handle)

    async def download(request: Request) -> Response:
        file_id = request.path_params["file_id"]
        worker = request.headers.get("X-Agora-Instance-Id", "")
        meta = file_store.meta(file_id)
        if meta is None:
            return JSONResponse({"error": "unknown_file"}, status_code=404)
        if not file_policy.can_download(worker, meta["name"]):
            return JSONResponse(
                {"error": str(AgoraError("file_download_denied", worker=worker,
                                         name=meta["name"]))},
                status_code=403)
        path = file_store.path_of(file_id)
        if path is None:
            return JSONResponse({"error": "unknown_file"}, status_code=404)
        return Response(path.read_bytes(), media_type=meta["content_type"]
                        or "application/octet-stream")

    app.router.routes.append(Route("/files", upload, methods=["POST"]))
    app.router.routes.append(Route("/files/{file_id}", download, methods=["GET"]))
```

- [ ] **Step 4: `__main__.py` 와이어링**

`__main__.py`에서 `admin_routes.maybe_register`/`dashboard` 등록 옆에 추가:

```python
        from agent_agora.file_routes import register as register_files
        register_files(starlette_app, file_store=file_store, file_policy=file_policy)
        print("  Files    : POST /files, GET /files/<id>")
```

- [ ] **Step 5: 테스트 통과 + 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/file_routes.py src/agent_agora/__main__.py tests/test_file_routes.py
git commit -m "feat: 파일 HTTP 엔드포인트 — POST/GET /files"
```

---

### Task 7: `/admin/file-policy` 엔드포인트

**Files:**
- Modify: `src/agent_agora/admin_routes.py`
- Modify: `src/agent_agora/__main__.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_admin_routes.py`에 추가(기존 `_TOKEN`·패턴 재사용):

```python
import json as _json
from agent_agora.file_policy import FilePolicy
from agent_agora.admin_routes import make_file_policy_route


def _fp_client(file_policy):
    app = Starlette(routes=[make_file_policy_route(file_policy, _TOKEN)])
    return TestClient(app)


def test_file_policy_post_replaces():
    fp = FilePolicy()
    body = _json.dumps({"workers": {"Coder1": {"r": ["*"], "w": ["*.py"]}}})
    r = _fp_client(fp).post("/admin/file-policy", content=body,
                            headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200
    assert fp.can_upload("Coder1", "a.py") is True
    assert fp.can_upload("Coder1", "a.exe") is False


def test_file_policy_get_returns_snapshot():
    fp = FilePolicy()
    fp.load_json(_json.dumps({"workers": {"Coder1": {"r": ["*"], "w": []}}}))
    r = _fp_client(fp).get("/admin/file-policy",
                           headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200
    assert r.json()["policy"]["workers"]["Coder1"]["w"] == []


def test_file_policy_post_without_token_401():
    fp = FilePolicy()
    r = _fp_client(fp).post("/admin/file-policy", content="{}")
    assert r.status_code == 401
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_routes.py -k file_policy -q`
Expected: FAIL — `make_file_policy_route` 미정의.

- [ ] **Step 3: `admin_routes.py`에 file-policy 라우트**

`admin_routes.py`에 `make_comm_matrix_route`(현 `make_admin_route`)와 같은 구조로 `make_file_policy_route`를 추가한다:

```python
def make_file_policy_route(file_policy, token: str) -> Route:
    """파일 권한 정책 admin 라우트. POST=교체(JSON 바디), GET=조회."""

    async def endpoint(request: Request) -> JSONResponse:
        if not _authorized(request, token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.method == "GET":
            return JSONResponse({"active": file_policy.active,
                                 "policy": file_policy.snapshot()})
        body = (await request.body()).decode("utf-8")
        try:
            file_policy.load_json(body)
        except AgoraError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "ok", "active": file_policy.active})

    return Route("/admin/file-policy", endpoint, methods=["GET", "POST"])
```

`maybe_register`(admin 라우트 등록 함수)가 `file_policy`도 받아 이 라우트를 함께 등록하도록 시그니처를 확장한다 — 또는 `__main__.py`에서 별도로 `make_file_policy_route`를 `starlette_app.router.routes`에 append한다(`AGORA_ADMIN_TOKEN`이 있을 때만). 후자가 단순하다.

- [ ] **Step 4: `__main__.py` 와이어링**

`__main__.py`의 admin 등록 블록에서, `AGORA_ADMIN_TOKEN`이 설정돼 있으면 file-policy 라우트도 등록:

```python
        _admin_token = os.environ.get("AGORA_ADMIN_TOKEN")
        if _admin_token:
            from agent_agora.admin_routes import make_file_policy_route
            starlette_app.router.routes.append(
                make_file_policy_route(file_policy, _admin_token))
```

(기존 `maybe_register`가 token 유무를 이미 검사하므로, 그 결과/패턴에 맞춰 일관되게 배치한다.)

- [ ] **Step 5: 테스트 통과 + 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/admin_routes.py src/agent_agora/__main__.py tests/test_admin_routes.py
git commit -m "feat: /admin/file-policy 엔드포인트"
```

---

### Task 8: `file_gc_sweep` TTL GC

**Files:**
- Modify: `src/agent_agora/sweeper.py`
- Modify: `src/agent_agora/__main__.py`
- Test: `tests/test_file_store.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_file_store.py`에 추가:

```python
from agent_agora.sweeper import Sweeper


def test_file_gc_sweep_removes_expired(tmp_path):
    store, p = _store(tmp_path)
    h = store.store_bytes(b"old", "old.txt", "Coder1")
    sw = Sweeper.__new__(Sweeper)  # GC만 검증 — 최소 구성
    # file_gc_sweep이 file_store·file_retention_days만 쓰도록 구현됐다면:
    removed = _file_gc(store, file_retention_days=0)
    assert removed == 1
    assert store.meta(h["file_id"]) is None
```

위 테스트는 의사코드 — Step 3에서 `Sweeper.file_gc_sweep`의 정확한 시그니처를 정한 뒤 그에 맞춘다. 권장: `Sweeper`가 생성자에서 `file_store`와 `file_retention_days`를 받고 `file_gc_sweep(now=None) -> int`를 노출. 테스트는 `Sweeper`를 정상 생성(다른 sweep 의존성 포함)해 `file_retention_days=0`으로 만들고 `file_gc_sweep()`이 1을 반환·파일이 사라짐을 검증한다. `tests/`의 기존 `Sweeper` 생성 패턴(`test_v3_recovery.py` 등)을 참고한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_file_store.py -k file_gc -q`
Expected: FAIL — `file_gc_sweep` 미정의.

- [ ] **Step 3: `Sweeper`에 `file_gc_sweep` 추가**

`src/agent_agora/sweeper.py`의 `Sweeper` 생성자에 `file_store`와 `file_retention_days`(기본 7) 파라미터를 추가하고 보관한다. 메서드 추가:

```python
    def file_gc_sweep(self, now: datetime.datetime | None = None) -> int:
        """보관 기간을 지난 공유 파일을 스토어·메타에서 삭제. 삭제 수 반환."""
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=self._file_retention_days)
        return self._file_store.gc(cutoff.isoformat())
```

`Dispatcher.__init__`이 `Sweeper(...)`를 생성하는 곳(dispatcher refactor Plan 3에서 추가됨)에 `file_store`·`file_retention_days`를 넘기도록 한다 — `Dispatcher.__init__`이 `file_store`를 받아야 하므로 `Dispatcher` 생성자에 `file_store` 파라미터를 추가하고 `__main__.py`의 `Dispatcher(...)` 호출에 넘긴다. (`Dispatcher` 자체는 `file_store`를 `Sweeper`에 전달만 한다.)

- [ ] **Step 4: `__main__.py` GC 루프 배선**

`__main__.py`의 GC 루프(현 `dispatcher.sweeper.message_gc_sweep()`를 호출하는 곳)에 한 줄 추가:

```python
            dispatcher.sweeper.file_gc_sweep()
```

- [ ] **Step 5: 테스트 통과 + 전체 회귀**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/sweeper.py src/agent_agora/dispatcher.py src/agent_agora/__main__.py tests/test_file_store.py
git commit -m "feat: file_gc_sweep — 공유 파일 TTL GC"
```

---

## 완료 기준

- `agora.share_file`/`agora.fetch_file`로 워커가 파일을 공유·수신한다(로컬 파일시스템).
- `POST /files`/`GET /files/<id>`로 원격 업/다운로드가 된다.
- `FilePolicy`가 워커별 r/w gitignore 패턴으로 업/다운로드를 게이트한다 — `r` 누락
  전체 허용, `w` 누락 전체 거부, 파일 없으면 무제한.
- `file_share` 빌트인 스키마로 핸들을 메시지에 실어 보낸다.
- `/admin/file-policy`로 정책을 재기동 없이 교체한다.
- `file_gc_sweep`이 보관 기간 지난 파일을 정리한다.
- 전체 테스트 스위트 통과.

## 비고

`Dispatcher`·`create_agora_app` 생성자에 `file_store`·`file_policy` 인자가 추가되므로,
이들을 호출하는 기존 테스트 헬퍼를 각 태스크에서 함께 갱신한다(`git grep`으로 호출처
확인). cross-cutting 시그니처 변경이라 매 태스크 끝에 전체 스위트가 green이어야 한다.
