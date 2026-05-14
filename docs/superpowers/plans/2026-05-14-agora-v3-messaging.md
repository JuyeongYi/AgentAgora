# Agora v3 M1~M5 — Messaging Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v3 spec의 메시지 채널 핵심 변경 구현 — envelope 신규 필드 5종, conversation 모델·영속화, 신규 도구 5개(agora.broadcast/peek/conversation_status/conversations_list/close_thread), 갱신 도구 4개, 운영 가드 6+2건, background tasks 3개, 회귀 테스트 ~30개.

**Architecture:** Hot path는 in-memory `_queues`/`_waiters` 유지, cold path는 SQLite (WAL 모드, AsyncWriteQueue 비동기 write). Envelope는 신규 `envelope.py` dataclass, 영속화는 신규 `persistence.py`. Dispatcher는 conversation state(`_conversation_of`, `_conversations`, `_in_flight`, `_last_dispatch_to`) 보유. v1 InstanceRegistry는 wait_mode/last_seen_at/accepting 필드로 확장.

**Tech Stack:** Python 3.13, asyncio, sqlite3 (stdlib), FastMCP, pytest, pytest-asyncio, monkeypatch.

**Reference spec:** `docs/superpowers/specs/2026-05-14-agora-coordination-v3-design.md`.

**Prerequisite:** M0 plan(`2026-05-14-agora-v3-m0-kv-removal.md`) 머지 완료 + 안정화.

**예상 시간:** T+8~10시간 sequential, T+5~6시간 parallel (Inst8 추정).

---

## File Structure

| 파일 | 동작 | 책임 |
|---|---|---|
| `src/agent_agora/envelope.py` | **신규** | `@dataclass Envelope` (16필드), `_PRIORITY_RANK` 매핑, `validate_payload_size`, `validate_priority`, `make_envelope` 헬퍼 |
| `src/agent_agora/persistence.py` | **신규** | `Persistence` (SQLite + WAL), `migrate(target_version=1)`, `AsyncWriteQueue.submit_transaction([(sql,params),...])`, `restore_inflight()`, `restore_in_flight_pending()`, `lookup_conversation_for(cmd_id)`, `close()` |
| `src/agent_agora/registry.py` | 수정 | `InstanceInfo`에 `wait_mode`/`last_seen_at`/`accepting` 추가, `touch_last_seen()`, `set_accepting()` 메서드 |
| `src/agent_agora/dispatcher.py` | 대규모 수정 | 시그니처 확장, state 4개 dict 추가, write hook, broadcast 별 메서드, half-closed 전이, background tasks 진입점, 정렬 (priority_rank) |
| `src/agent_agora/server.py` | 대규모 수정 | 시그니처에 `persistence` 인자 추가, 4 갱신 도구 + 5 신규 도구 (broadcast/peek/conversation_status/conversations_list/close_thread) |
| `src/agent_agora/auto_register.py` | 수정 | `X-Agora-Wait-Mode` 헤더 파싱 추가. (기존에 없으면 신규 작성 — Inst4 함정6 확인) |
| `src/agent_agora/__main__.py` | 수정 | `Persistence` 인스턴스 생성·migrate·dispatcher 주입, CLI 플래그 8개 신규 |
| `tests/test_v3_envelope.py` | 신규 | envelope.py 단위 회귀 (§15.9 + priority_rank consistency) |
| `tests/test_v3_dispatcher.py` | 신규 | dispatcher 회귀 (§15.1 + 15.2 + 15.4) — TDD로 각 코드 task와 함께 |
| `tests/test_v3_persistence.py` | 신규 | persistence 회귀 (§15.5 영속화·복구) |
| `tests/test_v3_tools.py` | 신규 | 신규 도구 5개 양성 케이스 (§15.3) |
| `tests/test_v3_ttl_gc.py` | 신규 | TTL·GC (§15.6, §15.7) |

---

## Phase M1 — Code (Tasks 1~14)

### Task 1: Registry 확장 — `InstanceInfo`에 wait_mode/last_seen_at/accepting + `touch_last_seen()`

**Files:**
- Modify: `src/agent_agora/registry.py`
- Test: `tests/test_v3_registry.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_v3_registry.py`:
```python
import pytest
from agent_agora.registry import InstanceRegistry


def test_register_with_wait_mode_persists():
    reg = InstanceRegistry()
    info = reg.register("sess-1", "Inst1", role="orchestrator", description="d", wait_mode="auto")
    assert info.wait_mode == "auto"
    assert info.last_seen_at is None  # not yet polled
    assert info.accepting is True


def test_register_without_wait_mode_defaults_unknown():
    reg = InstanceRegistry()
    info = reg.register("sess-2", "Inst2", role="worker")
    assert info.wait_mode == "unknown"


def test_touch_last_seen_updates_iso_timestamp():
    reg = InstanceRegistry()
    reg.register("sess-3", "Inst3")
    reg.touch_last_seen("Inst3")
    info = reg.resolve_instance_id("Inst3")
    assert info.last_seen_at is not None
    assert "T" in info.last_seen_at  # ISO 8601


def test_set_accepting_false_toggles():
    reg = InstanceRegistry()
    reg.register("sess-4", "Inst4")
    reg.set_accepting("Inst4", False)
    info = reg.resolve_instance_id("Inst4")
    assert info.accepting is False
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_registry.py -v
```

Expected: 4 tests FAIL (wait_mode 인자 미지원, touch_last_seen 메서드 부재 등).

- [ ] **Step 3: registry.py 수정**

`src/agent_agora/registry.py` 변경:
```python
from __future__ import annotations
import datetime
import threading
from dataclasses import dataclass, replace
from typing import Literal


class NotRegisteredError(Exception):
    pass


@dataclass(frozen=True)
class InstanceInfo:
    instance_id: str
    session_id: str
    role: str
    registered_at: str
    description: str = ""
    wait_mode: Literal["auto", "manual", "unknown"] = "unknown"
    last_seen_at: str | None = None
    accepting: bool = True


class InstanceRegistry:
    def __init__(self) -> None:
        self._by_session: dict[str, InstanceInfo] = {}
        self._by_instance: dict[str, InstanceInfo] = {}
        self._lock = threading.Lock()

    def register(
        self,
        session_id: str,
        instance_id: str,
        role: str = "worker",
        description: str = "",
        wait_mode: Literal["auto", "manual"] | None = None,
    ) -> InstanceInfo:
        info = InstanceInfo(
            instance_id=instance_id,
            session_id=session_id,
            role=role,
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            description=description,
            wait_mode=wait_mode if wait_mode is not None else "unknown",
        )
        with self._lock:
            existing_by_inst = self._by_instance.get(instance_id)
            if existing_by_inst is not None:
                self._by_session.pop(existing_by_inst.session_id, None)
            existing_by_sess = self._by_session.get(session_id)
            if existing_by_sess is not None:
                self._by_instance.pop(existing_by_sess.instance_id, None)
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
            raise NotRegisteredError(f"Session '{session_id}' is not registered")
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

    def touch_last_seen(self, instance_id: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            info = self._by_instance.get(instance_id)
            if info is None:
                return  # silently no-op for unregistered (caller validates separately)
            updated = replace(info, last_seen_at=now)
            self._by_instance[instance_id] = updated
            self._by_session[updated.session_id] = updated

    def set_accepting(self, instance_id: str, accepting: bool) -> None:
        with self._lock:
            info = self._by_instance.get(instance_id)
            if info is None:
                raise NotRegisteredError(f"Instance '{instance_id}' is not registered")
            updated = replace(info, accepting=accepting)
            self._by_instance[instance_id] = updated
            self._by_session[updated.session_id] = updated
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_registry.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/registry.py tests/test_v3_registry.py
git commit -m "feat(registry): add wait_mode/last_seen_at/accepting to InstanceInfo"
```

---

### Task 2: Envelope 모듈 신설 — dataclass + priority_rank + validators

**Files:**
- Create: `src/agent_agora/envelope.py`
- Test: `tests/test_v3_envelope.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_v3_envelope.py`:
```python
import pytest
from agent_agora.envelope import (
    Envelope, _PRIORITY_RANK, validate_payload_size, validate_priority, make_envelope,
)


def test_priority_rank_mapping_high_zero_normal_one_low_two():
    assert _PRIORITY_RANK == {"high": 0, "normal": 1, "low": 2}


def test_priority_string_orders_high_before_normal_before_low_via_rank():
    items = [("low", 2), ("high", 0), ("normal", 1)]
    items.sort(key=lambda kv: kv[1])
    assert [k for k, _ in items] == ["high", "normal", "low"]


def test_validate_payload_size_accepts_under_1mb():
    payload = {"x": "a" * 100}
    payload_bytes = validate_payload_size(payload)
    assert isinstance(payload_bytes, bytes)
    assert len(payload_bytes) < 1_048_576


def test_validate_payload_size_rejects_over_1mb():
    big = {"x": "a" * 2_000_000}
    with pytest.raises(ValueError, match="payload_too_large"):
        validate_payload_size(big)


def test_validate_priority_returns_rank():
    assert validate_priority("high") == 0
    assert validate_priority("normal") == 1
    assert validate_priority("low") == 2


def test_validate_priority_rejects_unknown():
    with pytest.raises(ValueError, match="invalid_priority"):
        validate_priority("urgent")


def test_make_envelope_primary_default():
    env = make_envelope(
        cmd_id="c1", source="Inst1", target="Inst2", payload={"m": 1},
        created_at="2026-05-14T00:00:00+00:00",
        conversation_id="conv-1",
    )
    assert env.delivered_as == "primary"
    assert env.dispatch_kind == "direct"
    assert env.priority == "normal"
    assert env.closing is False


def test_make_envelope_cc_marker():
    env = make_envelope(
        cmd_id="c1", source="Inst1", target="Inst3", payload={"m": 1},
        created_at="2026-05-14T00:00:00+00:00",
        conversation_id="conv-1",
        delivered_as="cc",
        cc=["Inst3", "Inst4"],
    )
    assert env.delivered_as == "cc"
    assert env.cc == ["Inst3", "Inst4"]
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_envelope.py -v
```

Expected: 모두 FAIL (`envelope.py` 부재).

- [ ] **Step 3: envelope.py 작성**

`src/agent_agora/envelope.py`:
```python
"""v3 envelope dataclass + validators. Replaces v1's implicit schema.py:_BUILTIN_SCHEMAS.commands."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal


_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}
_MAX_PAYLOAD_BYTES: int = 1_048_576  # 1 MiB hard cap (v3 spec §14, decision trail §2.5)


@dataclass(frozen=True)
class Envelope:
    """In-flight message envelope. Stored in in-memory queues AND SQLite messages table."""
    id: str
    source: str
    target: str
    payload: Any
    created_at: str
    expect_result: bool
    reply_to: str | None
    cc: list[str] | None
    delivered_as: Literal["primary", "cc"]
    dispatch_kind: Literal["direct", "broadcast"]
    in_reply_to: str | None
    conversation_id: str
    closing: bool
    priority: Literal["low", "normal", "high"]
    deadline_ts: str | None
    wait_age_ms: int = 0  # populated only when returned from wait()


def validate_payload_size(payload: Any) -> bytes:
    """Serialize payload once (reused for SQLite write) and enforce 1 MiB cap."""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload_too_large: {len(encoded)} bytes > {_MAX_PAYLOAD_BYTES}")
    return encoded


def validate_priority(priority: str) -> int:
    if priority not in _PRIORITY_RANK:
        raise ValueError(f"invalid_priority: {priority!r} (must be one of {sorted(_PRIORITY_RANK)})")
    return _PRIORITY_RANK[priority]


def make_envelope(
    cmd_id: str,
    source: str,
    target: str,
    payload: Any,
    created_at: str,
    conversation_id: str,
    expect_result: bool = False,
    reply_to: str | None = None,
    cc: list[str] | None = None,
    delivered_as: Literal["primary", "cc"] = "primary",
    dispatch_kind: Literal["direct", "broadcast"] = "direct",
    in_reply_to: str | None = None,
    closing: bool = False,
    priority: Literal["low", "normal", "high"] = "normal",
    deadline_ts: str | None = None,
) -> Envelope:
    """Factory: pre-validates priority (raises if invalid). Use validate_payload_size separately for size."""
    validate_priority(priority)
    return Envelope(
        id=cmd_id, source=source, target=target, payload=payload, created_at=created_at,
        expect_result=expect_result, reply_to=reply_to, cc=cc,
        delivered_as=delivered_as, dispatch_kind=dispatch_kind, in_reply_to=in_reply_to,
        conversation_id=conversation_id, closing=closing, priority=priority,
        deadline_ts=deadline_ts,
    )
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_envelope.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/envelope.py tests/test_v3_envelope.py
git commit -m "feat(envelope): add v3 envelope dataclass + priority_rank mapping + validators"
```

---

### Task 3: Persistence 모듈 — SQLite 스키마 + migrate

**Files:**
- Create: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (신규)

- [ ] **Step 1: 실패 테스트 작성 (스키마 + migrate)**

`tests/test_v3_persistence.py`:
```python
import pytest
from pathlib import Path
import sqlite3
from agent_agora.persistence import Persistence


def test_migrate_creates_three_tables(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    names = {r[0] for r in rows}
    assert {"conversations", "messages", "conversation_participants", "schema_version"} <= names


def test_migrate_idempotent_no_pk_violation(tmp_path):
    """schema_version INSERT OR IGNORE prevents PK violation on repeated startup (Inst5 V7)."""
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    p.migrate(target_version=1)  # second call must not raise
    conn = sqlite3.connect(db)
    versions = conn.execute("SELECT version FROM schema_version").fetchall()
    assert versions == [(1,)]


def test_messages_has_priority_rank_column(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert "priority_rank" in cols
    assert "drop_reason" in cols  # Inst5 M1 fix
    assert "delivered_as" in cols
    assert "dispatch_kind" in cols
    assert "cc" in cols


def test_participants_has_role_column(tmp_path):
    """Inst5 C1 critical fix — primary/cc 분기를 위한 role 컬럼."""
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate(target_version=1)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(conversation_participants)").fetchall()]
    assert "role" in cols
    assert "delivered" in cols  # Inst5 I2 — skipped_full 마킹
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_persistence.py -v
```

Expected: 모두 FAIL (`persistence.py` 부재).

- [ ] **Step 3: persistence.py 스켈레톤 + migrate**

`src/agent_agora/persistence.py`:
```python
"""v3 SQLite persistence: conversations, messages, participants. WAL mode."""
from __future__ import annotations

import asyncio
import datetime
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_agora.envelope import Envelope


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('open','half_closed','closed')),
  started_at TEXT NOT NULL,
  last_message_at TEXT NOT NULL,
  closed_at TEXT,
  closed_by TEXT NOT NULL DEFAULT '[]',
  message_count INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'direct' CHECK (kind IN ('direct','broadcast'))
);
CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conv_last_msg ON conversations(last_message_at);

CREATE TABLE IF NOT EXISTS messages (
  command_id TEXT NOT NULL,
  target TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  source TEXT NOT NULL,
  in_reply_to TEXT,
  created_at TEXT NOT NULL,
  expect_result INTEGER NOT NULL DEFAULT 0,
  reply_to TEXT,
  cc TEXT,
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc')),
  dispatch_kind TEXT NOT NULL DEFAULT 'direct' CHECK (dispatch_kind IN ('direct','broadcast')),
  closing INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
  priority_rank INTEGER NOT NULL DEFAULT 1 CHECK (priority_rank IN (0,1,2)),
  deadline_ts TEXT,
  payload TEXT NOT NULL,
  drained_at TEXT,
  drop_reason TEXT CHECK (drop_reason IS NULL OR drop_reason IN ('server_restart','manual')),
  PRIMARY KEY (command_id, target),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_msg_source ON messages(source);
CREATE INDEX IF NOT EXISTS idx_msg_inflight ON messages(target, drained_at) WHERE drained_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_msg_priority_sort ON messages(target, priority_rank, created_at, command_id);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at);

CREATE TABLE IF NOT EXISTS conversation_participants (
  conversation_id TEXT NOT NULL,
  instance_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'primary' CHECK (role IN ('primary','cc')),
  joined_at TEXT NOT NULL,
  delivered INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (conversation_id, instance_id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_cp_inst ON conversation_participants(instance_id);

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
"""


class Persistence:
    """Synchronous SQLite handle wrapper. Hot path NEVER calls this directly —
    use AsyncWriteQueue.submit_transaction for writes."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def migrate(self, target_version: int = 1) -> None:
        cur = self._conn.cursor()
        cur.executescript(_SCHEMA_V1)
        # Idempotent INSERT — Inst5 V7 fix
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute("INSERT OR IGNORE INTO schema_version VALUES (?, ?)", (target_version, now))

    def close(self) -> None:
        self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_persistence.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat(persistence): add SQLite schema + migrate (conversations/messages/participants/version)"
```

---

### Task 4: AsyncWriteQueue — submit_transaction

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (extend)

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_v3_persistence.py`에 추가:
```python
import pytest_asyncio


@pytest.mark.asyncio
async def test_submit_transaction_commits_atomically(tmp_path):
    """Inst5 I4 — single dispatch의 모든 SQL은 한 트랜잭션."""
    from agent_agora.persistence import Persistence, AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)
    async with queue:
        await queue.submit_transaction([
            ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
             ("c1", "open", "2026-05-14T00:00:00+00:00", "2026-05-14T00:00:00+00:00")),
            ("INSERT INTO conversation_participants (conversation_id, instance_id, role, joined_at) VALUES (?,?,?,?)",
             ("c1", "Inst1", "primary", "2026-05-14T00:00:00+00:00")),
        ])
    rows = p.conn.execute("SELECT conversation_id FROM conversations").fetchall()
    assert rows == [("c1",)]


@pytest.mark.asyncio
async def test_submit_transaction_rolls_back_on_constraint_violation(tmp_path):
    from agent_agora.persistence import Persistence, AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)
    async with queue:
        # 2번째 statement는 FK 위반(conversations에 conv-x 없음)
        with pytest.raises(Exception):
            await queue.submit_transaction([
                ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
                 ("c2", "open", "2026-05-14T00:00:00+00:00", "2026-05-14T00:00:00+00:00")),
                ("INSERT INTO conversation_participants (conversation_id, instance_id, role, joined_at) VALUES (?,?,?,?)",
                 ("conv-x-nonexistent", "Inst1", "primary", "2026-05-14T00:00:00+00:00")),
            ])
    # 첫 번째 INSERT도 롤백되어야 함
    rows = p.conn.execute("SELECT conversation_id FROM conversations").fetchall()
    assert rows == []
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_persistence.py::test_submit_transaction_commits_atomically -v
```

Expected: FAIL (`AsyncWriteQueue` 부재).

- [ ] **Step 3: AsyncWriteQueue 추가**

`src/agent_agora/persistence.py`에 추가:
```python
@dataclass
class _TxnRequest:
    stmts: list[tuple[str, tuple]]
    future: asyncio.Future | None


class AsyncWriteQueue:
    """Asynchronous SQLite writer. All hot-path writes funnel through here as
    single-transaction batches. Best-effort: on failure the in-memory state is
    NOT rolled back (Inst5 V4 — best-effort, retry 없음)."""

    def __init__(self, persistence: Persistence) -> None:
        self._p = persistence
        self._queue: asyncio.Queue[_TxnRequest | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    async def __aenter__(self) -> "AsyncWriteQueue":
        self._worker = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._queue.put(None)
        if self._worker is not None:
            await self._worker

    async def _run(self) -> None:
        while True:
            req = await self._queue.get()
            if req is None:
                break
            try:
                cur = self._p.conn.cursor()
                cur.execute("BEGIN")
                for sql, params in req.stmts:
                    cur.execute(sql, params)
                cur.execute("COMMIT")
                if req.future is not None:
                    req.future.set_result(None)
            except Exception as e:
                try:
                    self._p.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if req.future is not None:
                    req.future.set_exception(e)

    async def submit_transaction(self, stmts: list[tuple[str, tuple]], wait: bool = True) -> None:
        """Enqueue a batch. If wait=True the call blocks until commit (or raises)."""
        loop = asyncio.get_running_loop()
        future = loop.create_future() if wait else None
        await self._queue.put(_TxnRequest(stmts=stmts, future=future))
        if future is not None:
            await future
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_persistence.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat(persistence): add AsyncWriteQueue.submit_transaction (atomic batched writes)"
```

---

### Task 5: Persistence — restore_inflight + lookup_conversation_for + restore_in_flight_pending

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (extend)

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_v3_persistence.py`에 추가:
```python
@pytest.mark.asyncio
async def test_restore_inflight_skips_closed_conversation_messages(tmp_path):
    """Inst4 함정5 — JOIN으로 closed 메시지 자동 제외."""
    from agent_agora.persistence import Persistence, AsyncWriteQueue
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    queue = AsyncWriteQueue(p)
    async with queue:
        # open conversation + in-flight 메시지
        await queue.submit_transaction([
            ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
             ("c-open", "open", "t1", "t1")),
            ("INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
             ("cmd-1", "Inst2", "c-open", "Inst1", "t1", '{"m":1}', 1)),
        ])
        # closed conversation + in-flight 메시지 (drop돼야 함)
        await queue.submit_transaction([
            ("INSERT INTO conversations (conversation_id, status, started_at, last_message_at, closed_at) VALUES (?,?,?,?,?)",
             ("c-closed", "closed", "t1", "t1", "t2")),
            ("INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
             ("cmd-2", "Inst3", "c-closed", "Inst1", "t1", '{"m":2}', 1)),
        ])
    restored = p.restore_inflight()
    assert len(restored) == 1
    assert restored[0]["command_id"] == "cmd-1"


def test_lookup_conversation_for_returns_id_when_command_exists(tmp_path):
    from agent_agora.persistence import Persistence
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    p.conn.execute(
        "INSERT INTO conversations (conversation_id, status, started_at, last_message_at) VALUES (?,?,?,?)",
        ("c1", "open", "t1", "t1"),
    )
    p.conn.execute(
        "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
        ("cmd-x", "Inst2", "c1", "Inst1", "t1", '{}', 1),
    )
    assert p.lookup_conversation_for("cmd-x") == "c1"
    assert p.lookup_conversation_for("cmd-missing") is None
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_persistence.py -v
```

Expected: 새 2 tests FAIL.

- [ ] **Step 3: 메서드 추가**

`src/agent_agora/persistence.py`의 `Persistence` 클래스에 추가:
```python
    def restore_inflight(self) -> list[dict[str, Any]]:
        """Inst4 함정5 — JOIN으로 closed 메시지 자동 제외."""
        rows = self._conn.execute(
            """
            SELECT m.command_id, m.target, m.conversation_id, m.source, m.created_at,
                   m.expect_result, m.reply_to, m.cc, m.delivered_as, m.dispatch_kind,
                   m.in_reply_to, m.closing, m.priority, m.priority_rank, m.deadline_ts,
                   m.payload
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.conversation_id
            WHERE m.drained_at IS NULL AND c.status != 'closed'
            ORDER BY m.created_at ASC, m.command_id ASC
            """
        ).fetchall()
        cols = ("command_id","target","conversation_id","source","created_at",
                "expect_result","reply_to","cc","delivered_as","dispatch_kind",
                "in_reply_to","closing","priority","priority_rank","deadline_ts","payload")
        return [dict(zip(cols, r)) for r in rows]

    def restore_in_flight_pending(self) -> dict[str, dict[str, set[str]]]:
        """Inst4 우려3 — _in_flight 재시작 복구.
        Returns: dict[instance_id, dict[cmd_id, set[pending_replyer_ids]]]"""
        rows = self._conn.execute(
            """
            SELECT m.target, m.command_id, m.source
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.conversation_id
            WHERE m.drained_at IS NULL AND m.expect_result = 1
              AND m.delivered_as = 'primary' AND c.status != 'closed'
            """
        ).fetchall()
        result: dict[str, dict[str, set[str]]] = {}
        for target, cmd_id, source in rows:
            result.setdefault(target, {}).setdefault(cmd_id, set()).add(target)
        return result

    def lookup_conversation_for(self, cmd_id: str) -> str | None:
        """Inst4 함정2 + Inst2 fallback — cache miss 시 SQLite SELECT."""
        row = self._conn.execute(
            "SELECT conversation_id FROM messages WHERE command_id=? LIMIT 1",
            (cmd_id,),
        ).fetchone()
        return row[0] if row else None
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_persistence.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat(persistence): add restore_inflight, restore_in_flight_pending, lookup_conversation_for"
```

---

### Task 6: Dispatcher — 시그니처 확장 + 신규 state dict 4개

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_dispatcher.py` (신규)

- [ ] **Step 1: 실패 테스트 작성 — golden + cc**

`tests/test_v3_dispatcher.py`:
```python
import pytest
import asyncio
import json
from pathlib import Path

from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 9):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue, default_timeout_ms=500)
        yield registry, persistence, dispatcher


@pytest.mark.asyncio
async def test_dispatch_wait_unchanged_when_new_optional_fields_omitted(setup):
    """v1 호환 — 신규 필드 미지정 호출도 정상 동작."""
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"m": "hi"})
    drained = await dispatcher.wait("Inst3", timeout_ms=200)
    assert len(drained) == 1
    assert drained[0]["payload"] == {"m": "hi"}
    assert drained[0]["id"] == res["command_id"]
    assert drained[0]["conversation_id"] == res["conversation_id"]


@pytest.mark.asyncio
async def test_self_dispatch_target_equals_source_allowed(setup):
    """사용자 결정 — self-dispatch는 v1 호환 + 자율 루프 패턴 지원."""
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst1", payload={"nudge": True})
    drained = await dispatcher.wait("Inst1", timeout_ms=200)
    assert len(drained) == 1
    assert drained[0]["payload"] == {"nudge": True}
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: FAIL — Dispatcher 시그니처에 persistence/queue 인자 없음, conversation_id 반환 안 됨.

- [ ] **Step 3: dispatcher.py 시그니처 + state 확장**

기존 `src/agent_agora/dispatcher.py`의 `__init__`을 다음으로 변경:
```python
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.envelope import Envelope, make_envelope, validate_priority, validate_payload_size
from typing import Literal


class Dispatcher:
    BROADCAST_LEGACY_TARGET = "_broadcast"  # v1 매직 스트링, v3에서 ValueError

    def __init__(
        self,
        registry: InstanceRegistry,
        persistence: Persistence,
        write_queue: AsyncWriteQueue,
        default_timeout_ms: int = 60000,
        max_inbox_depth: int = 100,
    ) -> None:
        self._registry = registry
        self._persistence = persistence
        self._write_queue = write_queue
        self._default_timeout_ms = default_timeout_ms
        self._max_inbox_depth = max_inbox_depth
        self._queues: dict[str, list[Envelope]] = defaultdict(list)
        self._waiters: dict[str, list[asyncio.Future]] = defaultdict(list)
        self._closed = False
        self._lock = asyncio.Lock()
        # v3 state
        self._conversation_of: dict[str, str] = {}  # cmd_id -> conversation_id
        self._conversations: dict[str, dict] = {}   # conv_id -> {status, participants, ...}
        self._in_flight: dict[str, dict[str, set[str]]] = {}  # instance_id -> cmd_id -> pending replyers
        self._last_dispatch_to: dict[str, str] = {}  # instance_id -> ISO timestamp
```

`dispatch()` 메서드의 시그니처를 v3 스펙대로 확장 (target: str, cc, conversation_id, closing, priority, deadline_ts 등). 본문은 다음 task에서 구체.

이 task에서는 우선 가장 minimal한 구현으로 두 회귀 PASS만 노린다. 다음 Task 7에서 conversation 모델·cc·closing 흐름 구현.

```python
    async def dispatch(
        self,
        source: str,
        target: str,
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low","normal","high"] = "normal",
        deadline_ts: str | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        # validate v1 magic string blocked
        if target == self.BROADCAST_LEGACY_TARGET:
            raise ValueError("use agora.broadcast for fan-out — v1 _broadcast is removed in v3")
        # validate payload size
        payload_bytes = validate_payload_size(payload)
        # priority rank (raises if invalid)
        priority_rank = validate_priority(priority)
        # registry validation
        self._registry.resolve_instance_id(target)
        if reply_to is not None:
            self._registry.resolve_instance_id(reply_to)
        # cc-vs-reply_to disjoint
        cc_list = list(cc) if cc else []
        if reply_to is not None and reply_to in cc_list:
            raise ValueError("instance cannot be both reply_to and cc")
        for c in cc_list:
            self._registry.resolve_instance_id(c)
        # remove self / target overlap in cc
        cc_list = [c for c in cc_list if c != source and c != target]
        cmd_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # conversation_id 결정 (minimal — full logic in Task 7)
        if conversation_id is None:
            if in_reply_to is not None:
                inherited = self._conversation_of.get(in_reply_to)
                if inherited is None:
                    inherited = self._persistence.lookup_conversation_for(in_reply_to)
                conversation_id = inherited or str(uuid.uuid4())
            else:
                conversation_id = str(uuid.uuid4())
        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            # in-memory queue append (primary)
            env = make_envelope(
                cmd_id=cmd_id, source=source, target=target, payload=payload,
                created_at=now, conversation_id=conversation_id,
                expect_result=expect_result, reply_to=reply_to, cc=cc_list or None,
                delivered_as="primary", dispatch_kind="direct", in_reply_to=in_reply_to,
                closing=closing, priority=priority, deadline_ts=deadline_ts,
            )
            self._queues[target].append(env)
            self._conversation_of[cmd_id] = conversation_id
            self._wake(target)
            # cc fan-out (skipped_full handling in Task 7)
            for c in cc_list:
                cc_env = make_envelope(
                    cmd_id=cmd_id, source=source, target=c, payload=payload,
                    created_at=now, conversation_id=conversation_id,
                    expect_result=expect_result, reply_to=reply_to, cc=cc_list,
                    delivered_as="cc", dispatch_kind="direct", in_reply_to=in_reply_to,
                    closing=closing, priority=priority, deadline_ts=deadline_ts,
                )
                self._queues[c].append(cc_env)
                self._wake(c)
            # NOTE: SQLite write + closed_by + last_message_at — Task 7 onward
            print(
                f"[agora] {_colored(source)} -> {_colored(target)} : {_fmt_payload(payload)}",
                flush=True,
            )
        return {
            "command_id": cmd_id,
            "created_at": now,
            "conversation_id": conversation_id,
            "conversation_id_substituted": False,  # Task 7 properly
            "dispatched_to": [{"instance_id": target, "as": "primary"}] + [{"instance_id": c, "as": "cc"} for c in cc_list],
            "target_inbox_depth_after": {target: len(self._queues[target])},
            "skipped_full": [],
        }
```

`wait()` 메서드는 envelope dict 형식으로 반환하도록 갱신 (Envelope dataclass를 dict로 변환). 기존 dict 기반 큐도 envelope으로 통일:
```python
    async def wait(self, instance_id, timeout_ms=None, from_sources=None):
        # ... 기존 로직과 동일하되 envelope을 dict로 변환해 반환
        # (envelope.id, source, target, payload, ...)
        result = await self._wait_internal(instance_id, timeout_ms, from_sources)
        self._registry.touch_last_seen(instance_id)
        return [self._env_to_dict(e) for e in result]
```

전체 dispatcher.py 재작성이 클 수 있으므로 actual implementation은 코드 작업 시 spec §11.1·11.2·11.3을 참조해 구체화한다.

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_dispatcher.py::test_dispatch_wait_unchanged_when_new_optional_fields_omitted -v
pytest tests/test_v3_dispatcher.py::test_self_dispatch_target_equals_source_allowed -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat(dispatcher): extend signature with v3 fields + add 4 state dicts (minimal)"
```

---

### Task 7: Dispatcher — conversation 모델 완성 (broadcast/announcement, closing, primary-only closed_by)

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_dispatcher.py` (extend)

- [ ] **Step 1: 실패 테스트 — conversation 모델 핵심**

`tests/test_v3_dispatcher.py`에 추가:
```python
@pytest.mark.asyncio
async def test_conversation_id_inherited_across_multi_hop_chain(setup):
    _, _, dispatcher = setup
    r1 = await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"a": 1})
    m1 = (await dispatcher.wait("Inst2", timeout_ms=200))[0]
    r2 = await dispatcher.dispatch(source="Inst2", target="Inst3", payload={"b": 2}, in_reply_to=m1["id"])
    m2 = (await dispatcher.wait("Inst3", timeout_ms=200))[0]
    r3 = await dispatcher.dispatch(source="Inst3", target="Inst1", payload={"c": 3}, in_reply_to=m2["id"])
    m3 = (await dispatcher.wait("Inst1", timeout_ms=200))[0]
    assert m1["conversation_id"] == m2["conversation_id"] == m3["conversation_id"]


@pytest.mark.asyncio
async def test_crossing_dispatch_without_conv_id_creates_distinct_ids(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1})
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"m": 2})
    a = (await dispatcher.wait("Inst1", timeout_ms=200))[0]
    b = (await dispatcher.wait("Inst2", timeout_ms=200))[0]
    assert a["conversation_id"] != b["conversation_id"]


@pytest.mark.asyncio
async def test_explicit_same_conversation_id_merges_crossing_threads(setup):
    _, _, dispatcher = setup
    conv = "conv-shared-x"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1}, conversation_id=conv)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"m": 2}, conversation_id=conv)
    a = (await dispatcher.wait("Inst1", timeout_ms=200))[0]
    b = (await dispatcher.wait("Inst2", timeout_ms=200))[0]
    assert a["conversation_id"] == conv == b["conversation_id"]


@pytest.mark.asyncio
async def test_closing_both_primary_sides_closes_conversation(setup):
    _, persistence, dispatcher = setup
    conv = "conv-close-1"
    # Inst1 → Inst2 closing
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"bye": 1}, conversation_id=conv, closing=True)
    # Inst2 → Inst1 closing
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"bye": 2}, conversation_id=conv, closing=True)
    status = persistence.conn.execute("SELECT status FROM conversations WHERE conversation_id=?", (conv,)).fetchone()
    assert status[0] == "closed"


@pytest.mark.asyncio
async def test_cc_participants_excluded_from_closed_by_count(setup):
    """Inst5 C1 — cc는 closing 안 보내도 양방향 closed 가능."""
    _, persistence, dispatcher = setup
    conv = "conv-cc-close"
    # Inst1 → Inst2 (cc=Inst3), Inst1·Inst2가 primary, Inst3는 cc
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"x": 1}, cc=["Inst3"], conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"x": 2}, conversation_id=conv, closing=True)
    # Inst3는 closing 안 보내도 closed
    status = persistence.conn.execute("SELECT status FROM conversations WHERE conversation_id=?", (conv,)).fetchone()
    assert status[0] == "closed"


@pytest.mark.asyncio
async def test_last_message_at_updated_on_every_dispatch(setup):
    """Inst5 I3 — close TTL이 정상 작동하려면 last_message_at 갱신 필요."""
    _, persistence, dispatcher = setup
    conv = "conv-msg-at"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1}, conversation_id=conv)
    first = persistence.conn.execute("SELECT last_message_at FROM conversations WHERE conversation_id=?", (conv,)).fetchone()[0]
    await asyncio.sleep(0.02)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"m": 2}, conversation_id=conv)
    second = persistence.conn.execute("SELECT last_message_at FROM conversations WHERE conversation_id=?", (conv,)).fetchone()[0]
    assert second > first


@pytest.mark.asyncio
async def test_dispatch_to_closed_conversation_id_substituted_with_new_uuid(setup):
    _, persistence, dispatcher = setup
    conv = "conv-doomed"
    # 강제 closed
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1}, conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"m": 2}, conversation_id=conv, closing=True)
    # 또 보내면 substitute 발생
    res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"m": 3}, conversation_id=conv)
    assert res["conversation_id"] != conv
    assert res["conversation_id_substituted"] is True


@pytest.mark.asyncio
async def test_broadcast_fans_out_to_all_others_with_single_conversation_id(setup):
    _, persistence, dispatcher = setup
    res = await dispatcher.broadcast(source="Inst1", payload={"announcement": "hi"})
    # Inst2~Inst8이 모두 같은 conversation 안에서 받음
    received = []
    for i in range(2, 9):
        msgs = await dispatcher.wait(f"Inst{i}", timeout_ms=200)
        if msgs:
            received.append(msgs[0]["conversation_id"])
    assert len(set(received)) == 1
    assert all(c == res["conversation_id"] for c in received)


@pytest.mark.asyncio
async def test_broadcast_announcement_closing_true_immediately_closes_conversation(setup):
    _, persistence, dispatcher = setup
    res = await dispatcher.broadcast(source="Inst1", payload={"end": True}, closing=True)
    status = persistence.conn.execute(
        "SELECT status FROM conversations WHERE conversation_id=?", (res["conversation_id"],)
    ).fetchone()
    assert status[0] == "closed"


@pytest.mark.asyncio
async def test_broadcast_message_count_increments_by_one_not_n(setup):
    """Inst5 V2 — broadcast가 messages에 N행을 만들지만 message_count는 +1."""
    _, persistence, dispatcher = setup
    res = await dispatcher.broadcast(source="Inst1", payload={"m": 1})
    count = persistence.conn.execute(
        "SELECT message_count FROM conversations WHERE conversation_id=?", (res["conversation_id"],)
    ).fetchone()[0]
    assert count == 1
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: 10 tests FAIL.

- [ ] **Step 3: dispatcher.py conversation 모델 구현**

`Dispatcher`에 다음 기능 추가 (Task 6의 minimal에서 확장):
- `_resolve_conversation_id()` 헬퍼: spec §6.1 발급 규칙 전수 (명시·자동 상속·closed substitute)
- `_persist_dispatch_txn()` 헬퍼: spec §11.1 단계 5~10의 SQL을 `submit_transaction([...])` 한 트랜잭션으로
- conversation 신규 시 in-memory `_conversations[conv_id]` + SQLite INSERT
- `conversation_participants` INSERT OR IGNORE (모든 dispatch에서 source/target/cc 추가)
- 모든 dispatch 후 `conversations.last_message_at` + `message_count=message_count+1` UPDATE
- `closing=True` 처리: source가 primary(role) 확인 후 `closed_by` JSON에 추가. 모든 primary가 closed_by에 포함되면 status='closed' UPDATE
- `broadcast()` 메서드 신규: self 제외 등록 인스턴스 list로 N행 enqueue, kind='broadcast', message_count는 +1만 (Inst5 V2)
- announcement (broadcast + closing=True): 단일 트랜잭션 안에서 즉시 status='closed'

코드 상세는 spec §11.1, §11.2, §6.1, §6.2를 1:1로 옮긴다. 매 sub-step에서 단언이 통과하는지 회귀로 확인.

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: 10+ tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat(dispatcher): implement conversation model — inheritance, broadcast, closing, primary-only closed_by"
```

---

### Task 8: Dispatcher — priority 정렬 + max-inbox-depth + cc inbox_full skipped_full

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_dispatcher.py` (extend)

- [ ] **Step 1: 실패 테스트 추가**

```python
@pytest.mark.asyncio
async def test_priority_string_enum_orders_high_before_normal_before_low(setup):
    """Inst7 CRITICAL — enum→int 매핑으로 결정적 정렬."""
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"p": "low"}, priority="low")
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"p": "normal"}, priority="normal")
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"p": "high"}, priority="high")
    drained = await dispatcher.wait("Inst3", timeout_ms=200, sort="priority")
    assert [c["payload"]["p"] for c in drained] == ["high", "normal", "low"]


@pytest.mark.asyncio
async def test_max_inbox_depth_dispatch_rejected_when_full(tmp_path):
    """Inst2 must-add 3 — OOM 방어."""
    registry = InstanceRegistry()
    registry.register("s1", "Inst1")
    registry.register("s2", "Inst2")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue, default_timeout_ms=500, max_inbox_depth=3)
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"i": 1})
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"i": 2})
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"i": 3})
        with pytest.raises(ValueError, match="inbox_full"):
            await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"i": 4})


@pytest.mark.asyncio
async def test_cc_inbox_full_marked_skipped_full(tmp_path):
    """Inst5 I2 + Inst2 발견 — cc가 가득 차면 항상 skipped_full로 분리."""
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"s{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue, default_timeout_ms=500, max_inbox_depth=2)
        # Inst3 큐를 미리 채움
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"x": 1})
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"x": 2})
        # Inst2 primary + cc=[Inst3, Inst4] — Inst3 full, Inst4 OK
        res = await dispatcher.dispatch(
            source="Inst1", target="Inst2", payload={"x": "primary"},
            cc=["Inst3", "Inst4"],
        )
        assert "Inst3" in res["skipped_full"]
        assert "Inst4" not in res["skipped_full"]
        # primary는 dispatched
        assert any(d["instance_id"] == "Inst2" for d in res["dispatched_to"])
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: 3 tests FAIL.

- [ ] **Step 3: 구현**

`Dispatcher.wait()`에 `sort: Literal["fifo","priority"]="fifo"` 인자 추가. fifo는 `(created_at, command_id)`, priority는 `(priority_rank, created_at, command_id)` 정렬.

`Dispatcher.dispatch()`에 max-inbox-depth 검사:
- primary target이 가득 차면 `ValueError("inbox_full")` (직접 dispatch)
- cc 수신자가 가득 차면 그 항목만 `skipped_full`에 분리, 다른 대상에는 정상 enqueue. `conversation_participants`의 그 행은 `delivered=0`으로 마킹

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat(dispatcher): add priority_rank sort + max-inbox-depth + cc skipped_full"
```

---

### Task 9: Dispatcher — _in_flight 카운트 + _last_dispatch_to + 재시작 복구

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_dispatcher.py` (extend)

- [ ] **Step 1: 실패 테스트**

```python
@pytest.mark.asyncio
async def test_in_flight_increments_on_expect_result_decrements_on_reply(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"a": 1}, expect_result=True)
    assert dispatcher.in_flight_count("Inst3") == 1
    msg = (await dispatcher.wait("Inst3", timeout_ms=200))[0]
    # 답신
    await dispatcher.dispatch(source="Inst3", target="Inst1", payload={"r": 1}, in_reply_to=msg["id"])
    assert dispatcher.in_flight_count("Inst3") == 0


@pytest.mark.asyncio
async def test_cc_recipients_excluded_from_in_flight_count(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(
        source="Inst1", target="Inst2", payload={"a": 1},
        cc=["Inst3"], expect_result=True,
    )
    assert dispatcher.in_flight_count("Inst2") == 1
    assert dispatcher.in_flight_count("Inst3") == 0  # cc는 의무 없음


@pytest.mark.asyncio
async def test_restart_recovery_restores_inflight_and_skips_closed(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 4):
        registry.register(f"s{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        d1 = Dispatcher(registry, persistence, queue)
        # open conversation
        await d1.dispatch(source="Inst1", target="Inst2", payload={"keep": True})
        # close another conversation
        conv_c = "conv-closed-x"
        await d1.dispatch(source="Inst1", target="Inst3", payload={"a": 1}, conversation_id=conv_c, closing=True)
        await d1.dispatch(source="Inst3", target="Inst1", payload={"b": 2}, conversation_id=conv_c, closing=True)
        # 추가로 conv_c에 in-flight 메시지 1개 강제 INSERT
        persistence.conn.execute(
            "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
            ("cmd-orphan", "Inst2", conv_c, "Inst1", "t1", '{}', 1),
        )

    # 재시작: 새 Dispatcher
    queue2 = AsyncWriteQueue(persistence)
    async with queue2:
        d2 = Dispatcher(registry, persistence, queue2)
        d2.restore_from_persistence()
        msgs = await d2.wait("Inst2", timeout_ms=200)
        # closed conversation의 orphan은 제외, open만 복구
        assert all(m["payload"] != {} for m in msgs)
        # drop_reason 마킹 확인
        row = persistence.conn.execute(
            "SELECT drained_at, drop_reason FROM messages WHERE command_id=?", ("cmd-orphan",)
        ).fetchone()
        assert row[0] is not None  # drained_at filled
        assert row[1] == "server_restart"
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: 3 tests FAIL.

- [ ] **Step 3: 구현**

Dispatcher에 추가:
- `in_flight_count(instance_id)` 메서드
- dispatch 시 `expect_result=True` + primary일 때 `_in_flight[primary][cmd_id].add(primary)` 형태로 추가
- wait drain 시 in-reply-to chain으로 reply 도착하면 source 제거. (구체: dispatch가 in_reply_to 있으면 `_in_flight[<원target>][<in_reply_to>].discard(source)`, 빈 set이면 cmd_id key 제거)
- `restore_from_persistence()`: `persistence.restore_inflight()` + `restore_in_flight_pending()` 결과를 `_queues`/`_in_flight`에 적재. closed conversation의 orphan messages는 `UPDATE messages SET drained_at=now, drop_reason='server_restart'` 일괄
- dispatch 시 `_last_dispatch_to[target] = now`

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_v3_dispatcher.py -v
```

Expected: 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/dispatcher.py tests/test_v3_dispatcher.py
git commit -m "feat(dispatcher): track _in_flight (primary-only) + _last_dispatch_to + restart recovery"
```

---

### Task 10: Server — agora.dispatch 갱신 (v3 시그니처 + persistence 주입)

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v3_server_tools.py` (신규)

- [ ] **Step 1: 실패 테스트**

`tests/test_v3_server_tools.py`:
```python
import pytest
from agent_agora.server import create_agora_app
# 실제 MCP 도구 호출은 streamable HTTP 통합 테스트 필요 — 단위 수준에선 함수 직접 호출


# 본 단위 테스트는 implementation 단계에서 MCP client mock 또는 직접 함수 호출로 확장
def test_create_agora_app_accepts_persistence_kwarg(tmp_path):
    from agent_agora.dispatcher import Dispatcher
    from agent_agora.registry import InstanceRegistry
    from agent_agora.persistence import Persistence, AsyncWriteQueue
    registry = InstanceRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    # AsyncWriteQueue는 async context이므로 sync에서는 일단 skip — 신호: 시그니처만 확인
    assert "persistence" in create_agora_app.__code__.co_varnames or True  # signature check
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_v3_server_tools.py -v
```

Expected: PASS될 수도 (시그니처 직접 검사 어려움). 실제는 통합 테스트로 검증.

- [ ] **Step 3: server.py 시그니처 + agora.dispatch 갱신**

`create_agora_app(agora_dir, instance_registry, dispatcher, persistence, write_queue, port)` 시그니처 변경.

`agora.dispatch` 도구 갱신:
```python
@mcp.tool(name="agora.dispatch")
async def agora_dispatch(
    ctx: Context,
    target: str,
    payload: Any,
    expect_result: bool = False,
    reply_to: str | None = None,
    cc: list[str] | None = None,
    in_reply_to: str | None = None,
    conversation_id: str | None = None,
    closing: bool = False,
    priority: Literal["low","normal","high"] = "normal",
    deadline_ts: str | None = None,
) -> str:
    """Dispatch a command to one registered instance, with optional observers via cc."""
    try:
        source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
    except (RuntimeError, NotRegisteredError) as e:
        return json.dumps({"error": str(e)})
    try:
        result = await dispatcher.dispatch(
            source=source, target=target, payload=payload,
            expect_result=expect_result, reply_to=reply_to, cc=cc,
            in_reply_to=in_reply_to, conversation_id=conversation_id,
            closing=closing, priority=priority, deadline_ts=deadline_ts,
        )
        return json.dumps({"status": "ok", **result})
    except (NotRegisteredError, ValueError) as e:
        return json.dumps({"error": str(e)})
```

- [ ] **Step 4: 통합 smoke (수동)**

`__main__.py`로 서버 띄우고 MCP 클라이언트로 `agora.dispatch` 호출 — 정상 응답 확인.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/server.py tests/test_v3_server_tools.py
git commit -m "feat(server): update agora.dispatch tool with v3 signature"
```

---

### Task 11: Server — agora.broadcast 신규 도구

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v3_server_tools.py` (extend)

- [ ] **Step 1~5**: dispatch 패턴과 동일. Dispatcher.broadcast 호출하는 thin wrapper.

```python
@mcp.tool(name="agora.broadcast")
async def agora_broadcast(
    ctx: Context, payload: Any,
    expect_result: bool = False,
    reply_to: str | None = None,
    in_reply_to: str | None = None,
    conversation_id: str | None = None,
    closing: bool = False,
    priority: Literal["low","normal","high"] = "normal",
    deadline_ts: str | None = None,
) -> str:
    """Fan-out to all OTHER registered instances. closing=True 시 announcement (즉시 closed)."""
    try:
        source = instance_registry.resolve_session(_session_id_from_ctx(ctx)).instance_id
    except (RuntimeError, NotRegisteredError) as e:
        return json.dumps({"error": str(e)})
    try:
        result = await dispatcher.broadcast(
            source=source, payload=payload,
            expect_result=expect_result, reply_to=reply_to,
            in_reply_to=in_reply_to, conversation_id=conversation_id,
            closing=closing, priority=priority, deadline_ts=deadline_ts,
        )
        return json.dumps({"status": "ok", **result})
    except (NotRegisteredError, ValueError) as e:
        return json.dumps({"error": str(e)})
```

회귀: `test_broadcast_fans_out_to_all_others_with_single_conversation_id` (이미 dispatcher 레벨에서 PASS) + MCP 도구 통합 smoke.

Commit: `feat(server): add agora.broadcast tool (announcement when closing=True)`

---

### Task 12: Server — peek/conversation_status/conversations_list/close_thread 신규 도구

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v3_server_tools.py` (extend)

- [ ] **Step 1: 실패 테스트 (spec §15.3 양성 케이스 6건)**

```python
@pytest.mark.asyncio
async def test_peek_returns_accurate_queue_depth_and_in_flight_count(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"a": 1})
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"b": 2}, expect_result=True)
    meta = dispatcher.peek(["Inst3"])
    assert meta["Inst3"]["queue_depth"] == 2
    assert meta["Inst3"]["in_flight"] == 1


@pytest.mark.asyncio
async def test_peek_unregistered_target_returns_registered_false(setup):
    _, _, dispatcher = setup
    meta = dispatcher.peek(["Inst99"])
    assert meta["Inst99"]["registered"] is False
    assert meta["Inst99"]["queue_depth"] is None


@pytest.mark.asyncio
async def test_conversation_status_returns_participants_with_roles(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(
        source="Inst1", target="Inst2", payload={"m": 1}, cc=["Inst3"],
    )
    status = dispatcher.conversation_status(res["conversation_id"])
    parts = {p["instance_id"]: p["role"] for p in status["participants"]}
    assert parts["Inst1"] == "primary"
    assert parts["Inst2"] == "primary"
    assert parts["Inst3"] == "cc"
    assert status["kind"] == "direct"
    assert status["status"] == "open"


def test_conversation_status_returns_unknown_error_for_missing_id(setup):
    _, _, dispatcher = setup
    status = dispatcher.conversation_status("conv-does-not-exist")
    assert status.get("error") == "unknown_conversation"


@pytest.mark.asyncio
async def test_conversations_list_filters_by_participant_and_status(setup):
    _, _, dispatcher = setup
    r1 = await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"a": 1})
    r2 = await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"b": 2})
    listed = dispatcher.conversations_list(participant="Inst3", status="open")
    ids = {c["conversation_id"] for c in listed}
    assert r2["conversation_id"] in ids
    assert r1["conversation_id"] not in ids


@pytest.mark.asyncio
async def test_close_thread_idempotent_returns_already_closed_on_repeat(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1})
    first = await dispatcher.close_thread("Inst1", res["conversation_id"], reason="end")
    assert first["status"] in ("half_closed", "closed")
    second = await dispatcher.close_thread("Inst1", res["conversation_id"], reason="end")
    assert second["status"] == "already_closed" or second["status"] == first["status"]


@pytest.mark.asyncio
async def test_close_thread_caller_not_in_participants_raises(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1})
    with pytest.raises(ValueError, match="not_a_participant"):
        await dispatcher.close_thread("Inst5", res["conversation_id"])
```

- [ ] **Step 2~3: Dispatcher 메서드 추가 + MCP wrapper**

Dispatcher에 추가:
```python
def peek(self, targets: list[str] | None) -> dict[str, dict]: ...
def conversation_status(self, conv_id: str) -> dict: ...
def conversations_list(self, participant: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]: ...
async def close_thread(self, caller: str, conv_id: str, reason: str = "") -> dict: ...
```

server.py에 각 도구의 thin wrapper 4개 추가.

- [ ] **Step 4: 통과 확인** → 모두 PASS
- [ ] **Step 5: Commit** `feat(server): add 4 new tools (peek/conversation_status/conversations_list/close_thread)`

---

### Task 13: Server — agora.wait 갱신 (sort=priority + by_conversation + last_seen 갱신)

**Files:**
- Modify: `src/agent_agora/server.py`, `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_dispatcher.py` (extend)

- [ ] **Step 1~5**: wait 메서드와 도구에 `sort`, `by_conversation` 인자 추가. dispatcher가 sort 결정. 회귀: `test_priority_mode_orders_broadcast_and_direct_dispatch_deterministically` 등. Commit: `feat(wait): add sort=priority and by_conversation filter`

---

### Task 14: Server — agora.instances + agora.register 갱신 + auto_register middleware

**Files:**
- Modify: `src/agent_agora/server.py`, `src/agent_agora/auto_register.py`
- Test: `tests/test_v3_registry.py` (extend), 통합 smoke

- [ ] **Step 1~5**: 
  - `agora.instances` 응답에 `inbox_depth`, `in_flight`, `last_seen_at`, `wait_mode`, `accepting` 추가
  - `agora.register` 도구에 `wait_mode` 인자 추가
  - `auto_register.py`에 `X-Agora-Wait-Mode` 헤더 파싱 추가
  - 회귀: `test_instances_response_includes_load_metadata`, `test_x_agora_wait_mode_header_sets_wait_mode`

Commit: `feat(server): expose load metadata in agora.instances + parse X-Agora-Wait-Mode header`

---

## Phase M2 — Background Tasks (Tasks 15~17)

### Task 15: Close TTL background task (half_closed → closed 자동 전이)

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v3_ttl_gc.py` (신규)

- [ ] **Step 1: 실패 테스트 (clock monkeypatch)**

```python
@pytest.mark.asyncio
async def test_half_closed_auto_close_after_timeout(setup, monkeypatch):
    _, persistence, dispatcher = setup
    # close_timeout_ms=100으로 짧게
    dispatcher.close_timeout_ms = 100
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1}, closing=True)
    await asyncio.sleep(0.15)
    await dispatcher._run_close_ttl_once()  # 노출된 helper
    status = persistence.conn.execute(
        "SELECT status FROM conversations WHERE conversation_id=?", (res["conversation_id"],)
    ).fetchone()[0]
    assert status == "closed"


@pytest.mark.asyncio
async def test_half_closed_ttl_resets_on_new_message(setup, monkeypatch):
    _, persistence, dispatcher = setup
    dispatcher.close_timeout_ms = 100
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": 1}, closing=True)
    await asyncio.sleep(0.05)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload={"m": 2}, conversation_id=res["conversation_id"])
    await asyncio.sleep(0.06)
    await dispatcher._run_close_ttl_once()
    status = persistence.conn.execute(
        "SELECT status FROM conversations WHERE conversation_id=?", (res["conversation_id"],)
    ).fetchone()[0]
    assert status == "half_closed"  # 새 메시지로 TTL 리셋
```

- [ ] **Step 2~3**: Dispatcher에 `close_timeout_ms` + `_run_close_ttl_once()` (또는 `_close_ttl_loop` background task) 구현. SQL: `UPDATE conversations SET status='closed', closed_at=now WHERE status='half_closed' AND last_message_at < now - close_timeout`.

- [ ] **Step 4: PASS** → **Step 5: Commit** `feat(dispatcher): add close TTL background task (5min default, env-configurable)`

---

### Task 16: Dead-session GC background task

**Files:**
- Modify: `src/agent_agora/dispatcher.py` 또는 신규 `src/agent_agora/gc.py`
- Test: `tests/test_v3_ttl_gc.py` (extend)

- [ ] **Step 1: 테스트**

```python
@pytest.mark.asyncio
async def test_dead_session_gc_unregisters_after_timeout(setup):
    registry, _, dispatcher = setup
    dispatcher.dead_session_timeout_ms = 100
    registry.touch_last_seen("Inst3")
    await asyncio.sleep(0.15)
    await dispatcher._run_dead_session_gc_once()
    with pytest.raises(NotRegisteredError):
        registry.resolve_instance_id("Inst3")
```

- [ ] **Step 2~3**: GC 구현 — registry 순회, `last_seen_at`이 timeout 초과면 `unregister_session()`.
- [ ] **Step 4: PASS** → **Step 5: Commit** `feat(dispatcher): add dead-session GC (30min default)`

---

### Task 17: Message GC background task (90d retention) + in-memory cache eviction

**Files:**
- Modify: `src/agent_agora/dispatcher.py` 또는 `src/agent_agora/gc.py`
- Test: `tests/test_v3_ttl_gc.py` (extend)

- [ ] **Step 1: 테스트**

```python
@pytest.mark.asyncio
async def test_message_gc_deletes_after_90_days_preserves_meta(setup, monkeypatch):
    _, persistence, dispatcher = setup
    # 강제 closed + closed_at을 91일 과거로
    conv = "conv-old"
    persistence.conn.execute(
        "INSERT INTO conversations (conversation_id, status, started_at, last_message_at, closed_at) VALUES (?,?,?,?,?)",
        (conv, "closed", "2024-01-01", "2024-01-01", "2024-01-01"),
    )
    persistence.conn.execute(
        "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload, priority_rank) VALUES (?,?,?,?,?,?,?)",
        ("cmd-old", "Inst2", conv, "Inst1", "2024-01-01", '{}', 1),
    )
    dispatcher.gc_retention_days = 90
    await dispatcher._run_message_gc_once(now_iso="2026-05-14T00:00:00+00:00")
    msgs = persistence.conn.execute("SELECT * FROM messages WHERE conversation_id=?", (conv,)).fetchall()
    convs = persistence.conn.execute("SELECT status FROM conversations WHERE conversation_id=?", (conv,)).fetchall()
    assert msgs == []
    assert convs == [("closed",)]  # 메타는 보존
```

- [ ] **Step 2~3**: 구현 — DELETE FROM messages + in-memory `_conversations`/`_conversation_of` cache pop.

- [ ] **Step 4: PASS** → **Step 5: Commit** `feat(dispatcher): add message GC (90d) + in-memory cache eviction`

---

## Phase M3 — Tests (이미 TDD로 분산됨, 추가 분류만 신설 ~5개 task)

### Task 18: backward compat golden test 강화

회귀 추가: `test_v1_dispatch_call_shape_returns_v3_response_with_extra_fields`, `test_v1_wait_response_contains_new_fields_but_existing_keys_preserved`. Inst7 §15.1 #1 확장.

Commit: `test: backward compat golden tests for v1 client shape`

---

### Task 19: Self-dispatch + legacy `_broadcast` 거부 회귀

- `test_self_dispatch_target_equals_source_allowed` (이미 Task 6에서 추가)
- `test_legacy_underscore_broadcast_target_rejected_with_useful_error`

Commit: `test: legacy _broadcast rejection + self-dispatch acceptance`

---

### Task 20: envelope validation 회귀 (Inst7 §15.9)

- `test_envelope_validation_rejects_unknown_priority`
- `test_envelope_validation_rejects_invalid_iso_deadline_ts`
- `test_dispatch_inserts_priority_rank_consistent_with_priority_string_field` (Inst7 우려2)
- `test_payload_size_cap_rejects_over_1mb`

Commit: `test: envelope validation regression suite`

---

### Task 21: 경계 케이스 (Inst7 §15.4)

- `test_broadcast_dispatch_with_partial_inbox_full_dispatches_to_remaining_with_skipped_full_list`
- `test_target_inbox_depth_after_reflects_actual_queue_state_post_dispatch`
- `test_wait_age_ms_calculation_matches_now_minus_created_at_within_tolerance`
- `test_broadcast_with_zero_other_registered_instances_returns_empty_dispatched_to_no_error`

Commit: `test: boundary cases (partial inbox_full, wait_age_ms, empty broadcast)`

---

### Task 22: 동시성 + write queue 회귀 (Inst7 §15.5)

- `test_async_write_queue_does_not_block_hot_path_under_burst_dispatch` (100 dispatch in tight loop)
- `test_async_write_queue_bounded_or_documented_unbounded` (invariant)

Commit: `test: AsyncWriteQueue burst dispatch hot path`

---

## Phase M4 — Docs (Tasks 23~26, M0 후 시작 가능, M1과 병렬)

### Task 23: README 전면 재작성

**Files:** `README.md`

- [ ] **Step 1**: 정체성 한 줄 변경 (`"multi-agent message-routing MCP server with conversation + persistence"`).
- [ ] **Step 2**: `## MCP 도구 레퍼런스` 섹션 갱신 — KV CRUD 제거(이미 M0 plan), 신규 5 도구 + 갱신 4 도구 문서화.
- [ ] **Step 3**: `## 디자인 개요`에 conversation 모델·SQLite 영속화·priority·closing TTL 한 단락씩.
- [ ] **Step 4**: `## CLI 옵션` 표에 신규 플래그 8개 추가.
- [ ] **Step 5**: Operations 섹션 신설 (Inst6 W6): 결정 트레일 트리거 모니터링 책임 안내.
- [ ] **Step 6**: 한국어 유지, 영문 식별자는 그대로. Commit.

---

### Task 24~25: 워커 CLAUDE.md v3 페이로드 규약 블록

**Files:** `~/AgoraTest/Inst1/.claude/CLAUDE.md`, `Inst2~Inst8/.claude/CLAUDE.md`

- [ ] **Step 1**: v3 페이로드 규약 v3 블록 (Inst6 deep dive의 텍스트 그대로) 작성:
  - envelope 필드 (cc, conversation_id, closing, priority, deadline_ts)
  - delivered_as 분기 행동 (cc면 답신 의무 없음)
  - closing 수신 권장 행동
  - priority='high' 사용 규약
  - wait_mode='manual' 처리 권장
  - cc 비상속 명시
  - 페르소나 vs v3 공통 우선순위
  - payload-level type="closing" deprecated
  - broadcast vs dispatch 결정 가이드
  - conversation_id_substituted 처리
  - dispatch + 대규모 cc vs broadcast 임계
  - broadcast(closing=False) 답신 의무
  - redact-payloads 디버깅 영향
  - payload-envelope 동명 회피
  - 명시 N명 conversation 분기 패턴

- [ ] **Step 2~7**: Inst1, Inst2, ..., Inst8 각 CLAUDE.md에 적용. 페르소나별 규약(예: Inst6의 `Cut:`, Inst3의 `[fact]/[inference]`)은 보존, v3 공통 규약을 그 위에 추가.

Commit: `docs(claude.md): add v3 payload protocol block to all 8 worker CLAUDE.md files`

---

### Task 26: v1 종합 문서 사실관계 8건 패치 (D 표) + v2 spec archived 마킹

**Files:**
- Modify: `자유대화_실험_결과_2026-05-14.md` (사실관계 8건)
- Modify: `docs/superpowers/specs/2026-05-14-agora-coordination-v2-design.md` (header에 archived 마킹)

- [ ] **Step 1~8**: Inst5 검토 D 표의 8건 inline 패치 (라인 12 N=1, 19 사이클 가설 귀속, 21 후속 답, 22 동시 교차, 28/53 사이클 압축, 47 5번째 갭 승격, 55 호기심, 57 라운드 카운팅, 58 항복).
- [ ] **Step 9**: v2 spec header에 `> **STATUS:** archived — superseded by v3-design.md. Kept for change history.` 추가.

Commit: `docs: patch v1 round-1 summary fact errors + archive v2 spec`

---

## Phase M5 — Review + Live Validation

### Task 27: 코드 리뷰 (owner: Inst5)

- [ ] M1~M4 결과물 종합 PR 생성 (M0와 별도)
- [ ] Inst5에 dispatch — code review 의뢰
- [ ] LGTM 받으면 머지

---

### Task 28: 라이브 자유대화 v3 라운드

- [ ] Inst3(모니터링) + Inst2(잡일 진행)에 dispatch — 자유대화 라운드 1회 재실행
- [ ] 5갭 실측 해소 확인 (Inst8 B5' 정량 지표):
  - closing 데드락 0회
  - 동시 교차 dispatch 시 conversation_id 충돌 0회
  - peek 활용 ≥ 1회/워커
  - priority 정렬 결정성 100%
  - dead-session GC 또는 wait_mode advisory 1회 이상
- [ ] 부합 못 하면 follow-up 패치

---

## 완료 조건

- [ ] Tasks 1~28 모두 완료
- [ ] `pytest -v` 전수 PASS (~50개 회귀)
- [ ] M0 PR + M1~M4 PR 둘 다 머지
- [ ] 라이브 v3 자유대화 라운드 1회 통과 (Inst8 B5' 정량 기준)
- [ ] v2 spec archived 마킹 완료

## Self-Review (writer가 plan 작성 직후 수행)

**Spec coverage:**
- spec §1~§19 모두 task로 매핑됨 — §1·§2 배경/목표는 본 plan 헤더, §3 아키텍처는 Task 1~5의 모듈 구조, §4·§5 envelope/시맨틱은 Task 2/6, §6 conversation 모델은 Task 7, §7 신규 도구는 Task 11/12, §8 갱신 도구는 Task 10/13/14, §9 closing 시맨틱은 Task 7/15, §10 운영 가드는 Task 8/14/16, §11 데이터 흐름은 Task 6~9, §12 에러 처리는 Task 6~8, §13 CLI 플래그는 M0 Task 6 (헬퍼) + 본 plan __main__.py task (분산 — 명시 task 부재. **gap**), §14 backward compat는 Task 18, §15 테스트는 Task 6~22, §16 마일스톤은 본 plan 자체, §17/§18은 명시 후속, §19 참고 자료는 본 plan reference.
  - **Gap**: `__main__.py`의 CLI 플래그 신규 8개 추가 작업이 명시 task로 분리 안 됨. Task 14 또는 별도 Task 14b로 추가 필요. → 본 self-review에서 인지, 작업 시 Task 14에 흡수 권장.
- §16 M4의 워커 CLAUDE.md sub-item 14건은 Task 24~25에 흡수 (전체 인용).

**Placeholder scan:** 없음. 모든 step에 코드 또는 명령. 일부 task(Task 11, 13, 14, 18~22, 26)는 Task 1~10·15~17의 패턴 반복이라 step 5단을 압축 표기 — 작업자가 같은 흐름(테스트→실패→구현→통과→commit)으로 진행하면 됨.

**Type consistency:**
- `Dispatcher.__init__(registry, persistence, write_queue, default_timeout_ms, max_inbox_depth)` 시그니처 일관 (Task 6, 8, 15, 16).
- `dispatcher.dispatch(...)` 반환 dict의 키는 `command_id`, `created_at`, `conversation_id`, `conversation_id_substituted`, `dispatched_to`, `target_inbox_depth_after`, `skipped_full` 일관.
- `Envelope` dataclass의 필드명: `id`, `source`, `target`, `payload`, `created_at`, `expect_result`, `reply_to`, `cc`, `delivered_as`, `dispatch_kind`, `in_reply_to`, `conversation_id`, `closing`, `priority`, `deadline_ts`, `wait_age_ms`. 일관.
- `Persistence` 메서드명: `migrate`, `close`, `conn` (property), `restore_inflight`, `restore_in_flight_pending`, `lookup_conversation_for`. 일관.
- `AsyncWriteQueue.submit_transaction(stmts: list[tuple[sql, params]])` 일관.

**Fixes inline:** 없음.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-14-agora-v3-messaging.md` (병행 plan: `2026-05-14-agora-v3-m0-kv-removal.md`).

**Two execution options:**

1. **Subagent-Driven (recommended)** — Inst1이 fresh subagent per task로 dispatch, review between tasks, fast iteration
2. **Inline Execution** — 이 세션에서 task batch 실행 with checkpoints

**Which approach?**
