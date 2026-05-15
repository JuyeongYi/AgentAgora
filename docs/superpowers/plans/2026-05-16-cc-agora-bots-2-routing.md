# cc-agora Bots — Plan 2: 봇 라우팅 (서버 사이드)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 서버를 pub/sub broker로 확장한다 — 봇이 schema를 구독하고, broker가 `msgtype` 매칭으로 envelope을 구독 봇·observer에 자동 fan-out하며, 봇은 `agora.bot_emit`으로 결과를 비동기 전파한다.

**Architecture:** 새 `BotRegistry`(봇 전용 네임스페이스 + subscribe schema 역인덱스)를 추가하고 Plan 1의 `SchemaRegistry`와 나란히 `_build_app` → `create_agora_app` → `Dispatcher`로 배선한다. 배선은 *동작 변경 없는 리팩터*로 먼저 끝낸 뒤, `Dispatcher.dispatch`/`broadcast`에 봇 fan-out(`delivered_as` = `subscribed`/`cc`)을 추가하고, `target` 생략 schema-routed dispatch와 `bot_emit`을 구현한다. 봇은 `agora.register_bot` / `agora.wait` / `agora.bot_emit` 3개 도구만 쓰는 MCP client다.

**Tech Stack:** Python 3.13, FastMCP, jsonschema, SQLite(WAL), pytest + pytest-asyncio.

**범위:** spec [`2026-05-15-cc-agora-bots-design.md`](../specs/2026-05-15-cc-agora-bots-design.md) v4의 **2개 분할 plan 중 2번**. Plan 1(스키마 강제 — `2026-05-16-cc-agora-bots-1-schema.md`)이 **이미 master에 머지된 상태를 전제**한다. plugin v2.2 / `agora_bot_sdk` / `bot.py.template`(§3.11, §8 item 9)는 별도 spec — 제외.

**Plan 1이 남긴 것 (Plan 2의 출발점):**
- `errors.py` — `AgoraError(ValueError)` + `ERROR_MESSAGES`(schema 코드 5종).
- `schemas.py` — `SchemaRegistry`(`register(name, body, kind, purpose, registered_by)` / `get` / `validator` / `list_meta` / `list_all`), `SchemaEntry`, jsonl 로더, `BUNDLED_DEFAULT_SCHEMAS`.
- `persistence.py` — `schemas` 테이블 + `save_schema`/`restore_schemas`.
- `dispatcher.py` — `Dispatcher.__init__(registry, persistence, write_queue, *, schema_registry, default_timeout_ms=..., ...)`; `_validate_payload(payload) -> str`; `dispatch`/`broadcast`가 msgtype을 강제.
- `server.py` — `create_agora_app(agora_dir, instance_registry, schema_registry, persistence, dispatcher, port)`; `agora.register_schema`/`schemas`/`schemas_list` 도구.
- `__main__.py` — `_build_app`가 `SchemaRegistry`를 구성.
- `tests/_helpers.py` — `make_schema_registry()`, `tany()`, `wf()`, `TEST_ANY_BODY`. `conftest.py`에 `schema_registry` fixture + `tests/` sys.path.

---

## Spec 정합 보정 (Plan 2 해당분)

1. **`agora.register_bot`의 `schemas` 인자 값은 `{kind, purpose, body}` 전체 정의.** spec §3.3은 `schemas: dict[str, dict]`로만 적었다. 결정 23(모든 schema는 `kind`+`purpose` 메타) 정합을 위해 각 값은 `{"kind": "bot-task", "purpose": "...", "body": {...}}` 형태로 받는다. 봇이 등록하는 schema는 §3.2상 반드시 `bot-task` kind여야 하므로 `kind != "bot-task"`면 거부한다.
2. **`bot_subscriptions` 테이블 PK는 `(instance_id, schema_name, kind)`.** spec §5.2는 PK를 `(instance_id, schema_name)`로 적었으나, 봇이 같은 schema를 `subscribe`와 `emit` 양쪽으로 선언할 수 있어(§3.3 `subscribe_schemas`+`emit_schemas`) PK에 `kind`를 포함한다. `schemas(name)` FK는 두지 않는다 — `register_bot`이 schema와 subscription을 같은 호출에서 등록할 때 쓰기 순서 결합을 피하기 위함(§9.6의 일괄 사전검증으로 정합 보장).
3. **봇 subscription은 audit 기록만, `BotRegistry`로 복원하지 않는다.** spec §5.2는 "재시작 시 subscription 복원"이라 적었으나 — 봇은 살아있는 MCP client 세션이라 재시작 시 세션이 끊기고 재접속하며 `register_bot`을 다시 호출한다. 죽은 세션을 가리키는 ghost 봇을 부활시키면 라우팅이 깨진다. `bot_subscriptions` 테이블은 audit/durability 목적으로 쓰기만 하고 startup 시 `BotRegistry`로 읽어들이지 않는다. (schema 카탈로그는 Plan 1대로 복원한다 — 그건 의미가 있다.)

---

## File Structure

### 신규 파일
- `src/agent_agora/bot_registry.py` — `BotInfo`, `BotRegistry`. 봇 전용 네임스페이스 + subscribe schema 역인덱스.
- `tests/test_v4_bot_registry.py` — `BotRegistry` 단위 테스트.
- `tests/test_v4_routing.py` — Dispatcher 봇 fan-out / `bot_emit` / `wait` 라우팅 테스트.
- `tests/test_v4_bots.py` — server 봇 도구 + §8.8 통합 테스트.

### 수정 파일
- `src/agent_agora/errors.py` — `ERROR_MESSAGES`에 봇 에러 코드 추가.
- `src/agent_agora/persistence.py` — `bot_subscriptions` 테이블, `messages.delivered_as` CHECK에 `'subscribed'`, `save_bot_subscriptions`/`restore_bot_subscriptions`/`lookup_source_for`.
- `src/agent_agora/envelope.py` — `delivered_as` Literal에 `"subscribed"`.
- `src/agent_agora/dispatcher.py` — `bot_registry` 주입; `dispatch`/`broadcast` 봇 fan-out; `target` 생략 dispatch; `bot_emit`; `wait` 봇 resolution; `_message_source` 추적.
- `src/agent_agora/server.py` — `create_agora_app`에 `bot_registry`; `agora.register_bot`/`agora.bots`/`agora.bot_emit` 도구; `agora.find` 워커·봇 통합; `agora.dispatch` `target` 선택 + 봇 호출 차단; `agora.broadcast` 봇 호출 차단; `agora.wait` 봇 resolution.
- `src/agent_agora/__main__.py` — `_build_app`에 `BotRegistry` 배선.
- `tests/conftest.py` — `bot_registry` fixture.
- `tests/test_v4_schemas.py` — 봇 에러 코드 테스트 1건.
- `tests/test_v3_persistence.py` · `test_v3_envelope.py` — 신규 테이블/필드 테스트.
- `tests/test_v3_dispatcher.py` · `test_v3_recovery.py` · `test_v3_ttl_gc.py` · `test_integration.py` · `test_v4_schema_enforcement.py` · `test_main.py` — Dispatcher/`create_agora_app` 생성 시그니처에 `bot_registry` 추가.

### 책임 경계
- `bot_registry.py` — 봇 식별·구독 역인덱스. schema body 모름(이름만).
- `dispatcher.py` — `bot_registry`를 *소비*만 한다(라우팅).
- `server.py` — MCP 도구 표면. 세션 ↔ instance/bot resolution.

---

## Task 1: errors.py — 봇 에러 코드 추가

**Files:**
- Modify: `src/agent_agora/errors.py`
- Test: `tests/test_v4_schemas.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_schemas.py`에 추가:

```python
def test_plan2_bot_codes_present():
    expected = {
        "no_route", "unhandled_schema", "bot_emit_not_a_bot",
        "description_required", "subscribe_required",
        "cannot_subscribe_conversation", "schema_kind_not_bot_task",
    }
    assert expected <= set(ERROR_MESSAGES)


def test_no_route_message_formats_msgtype():
    e = AgoraError("no_route", msgtype="pytest_run")
    assert e.code == "no_route"
    assert "pytest_run" in str(e)


def test_unhandled_schema_message_formats_bot_and_msgtype():
    e = AgoraError("unhandled_schema", bot="bot_x", msgtype="deploy")
    assert "bot_x" in str(e) and "deploy" in str(e)
```

(`AgoraError`, `ERROR_MESSAGES` are already imported at the top of `test_v4_schemas.py` from Plan 1.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_schemas.py -v -k "plan2 or no_route or unhandled_schema"`
Expected: FAIL — codes not in `ERROR_MESSAGES`.

- [ ] **Step 3: errors.py 수정** — `ERROR_MESSAGES` dict에 항목 추가(기존 5개 schema 코드 뒤에):

```python
    # Plan 2 — bot routing codes
    "no_route": "[agora] msgtype '{msgtype}'를 구독하는 봇이 없고 target도 없습니다.",
    "unhandled_schema": "[agora] 봇 {bot}는 msgtype '{msgtype}'를 구독하지 않습니다.",
    "bot_emit_not_a_bot": "[agora] agora.bot_emit은 봇만 호출할 수 있습니다.",
    "description_required": "[agora] 봇 mode는 description이 필수입니다.",
    "subscribe_required": "[agora] bot-handler는 구독 schema가 비어있을 수 없습니다.",
    "cannot_subscribe_conversation": "[agora] conversation kind schema '{name}'는 봇이 구독할 수 없습니다.",
    "schema_kind_not_bot_task": "[agora] 봇이 등록하는 schema '{name}'는 kind가 'bot-task'여야 합니다.",
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_schemas.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/errors.py tests/test_v4_schemas.py
git commit -m "feat: add bot routing error codes (§4.5)"
```

---

## Task 2: SQLite — bot_subscriptions 테이블 + delivered_as CHECK

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v3_persistence.py`에 추가:

```python
def test_migrate_creates_bot_subscriptions_table(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    names = {r[0] for r in p.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "bot_subscriptions" in names


def test_messages_delivered_as_check_allows_subscribed(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    sql = p.conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='messages'").fetchone()[0]
    assert "subscribed" in sql
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v3_persistence.py -v -k "bot_subscriptions or delivered_as_check"`
Expected: FAIL.

- [ ] **Step 3: persistence.py 수정**

(a) In the `_SCHEMA_V1` string, find the `messages` table's `delivered_as` column line:
```python
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc')),
```
Replace it with (adds `'subscribed'`):
```python
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc','subscribed')),
```

(b) Append to the END of the `_SCHEMA_V1` string (after the `schemas` table that Plan 1 added):
```sql
CREATE TABLE IF NOT EXISTS bot_subscriptions (
  instance_id TEXT NOT NULL,
  schema_name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('subscribe','emit')),
  PRIMARY KEY (instance_id, schema_name, kind)
);
CREATE INDEX IF NOT EXISTS idx_bot_sub_schema ON bot_subscriptions(schema_name);
```

> `messages` 테이블 CHECK 변경은 `CREATE TABLE IF NOT EXISTS`라 *신규 DB*에만 적용된다. 기존 개발 DB는 재생성 대상(본 plan 범위 밖). `migrate()` 본문은 변경 불필요.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v3_persistence.py -v`
Expected: PASS (전체 — 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat: SQLite bot_subscriptions table + delivered_as 'subscribed'"
```

---

## Task 3: Persistence — bot_subscriptions save/restore + lookup_source_for

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v3_persistence.py`에 추가:

```python
def test_save_and_restore_bot_subscriptions(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    p.save_bot_subscriptions("bot_x", subscribe=["s1", "s2"], emit=["s1"])
    subs = p.restore_bot_subscriptions()
    assert sorted(subs["bot_x"]["subscribe"]) == ["s1", "s2"]
    assert subs["bot_x"]["emit"] == ["s1"]


def test_save_bot_subscriptions_replaces_prior_rows(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    p.save_bot_subscriptions("bot_x", subscribe=["old"], emit=[])
    p.save_bot_subscriptions("bot_x", subscribe=["new"], emit=[])
    subs = p.restore_bot_subscriptions()
    assert subs["bot_x"]["subscribe"] == ["new"]


def test_lookup_source_for_returns_message_source(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    p.conn.execute(
        "INSERT INTO conversations (conversation_id, status, started_at, last_message_at) "
        "VALUES ('c1', 'open', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")
    p.conn.execute(
        "INSERT INTO messages (command_id, target, conversation_id, source, created_at, payload) "
        "VALUES ('cmd1', 'Inst2', 'c1', 'Inst1', '2026-01-01T00:00:00Z', '{}')")
    assert p.lookup_source_for("cmd1") == "Inst1"
    assert p.lookup_source_for("nonexistent") is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v3_persistence.py -v -k "bot_subscriptions or lookup_source"`
Expected: FAIL — methods do not exist.

- [ ] **Step 3: 구현** — `persistence.py`의 `Persistence` 클래스에 메서드 추가(`restore_schemas` 아래):

```python
    def save_bot_subscriptions(
        self, instance_id: str, subscribe: list[str], emit: list[str],
    ) -> None:
        """봇 구독을 audit용으로 영속화한다. 같은 instance_id의 기존 행은 교체한다.
        (BotRegistry는 재시작 시 이 테이블에서 복원하지 않는다 — 봇이 재접속하며 재등록한다.)"""
        self._conn.execute("DELETE FROM bot_subscriptions WHERE instance_id=?", (instance_id,))
        for s in subscribe:
            self._conn.execute(
                "INSERT OR IGNORE INTO bot_subscriptions (instance_id, schema_name, kind) "
                "VALUES (?, ?, 'subscribe')", (instance_id, s))
        for s in emit:
            self._conn.execute(
                "INSERT OR IGNORE INTO bot_subscriptions (instance_id, schema_name, kind) "
                "VALUES (?, ?, 'emit')", (instance_id, s))

    def restore_bot_subscriptions(self) -> dict[str, dict[str, list[str]]]:
        rows = self._conn.execute(
            "SELECT instance_id, schema_name, kind FROM bot_subscriptions").fetchall()
        out: dict[str, dict[str, list[str]]] = {}
        for instance_id, schema_name, kind in rows:
            entry = out.setdefault(instance_id, {"subscribe": [], "emit": []})
            entry["subscribe" if kind == "subscribe" else "emit"].append(schema_name)
        return out

    def lookup_source_for(self, cmd_id: str) -> str | None:
        """cmd_id의 원 source를 SQLite에서 조회 (bot_emit in_reply_to cache miss 폴백)."""
        row = self._conn.execute(
            "SELECT source FROM messages WHERE command_id=? LIMIT 1", (cmd_id,)
        ).fetchone()
        return row[0] if row else None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v3_persistence.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat: persist bot subscriptions (audit) + lookup_source_for"
```

---

## Task 4: bot_registry.py — BotInfo + BotRegistry

**Files:**
- Create: `src/agent_agora/bot_registry.py`
- Create: `tests/test_v4_bot_registry.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_bot_registry.py`:

```python
import pytest
from agent_agora.bot_registry import BotInfo, BotRegistry
from agent_agora.registry import NotRegisteredError


def test_register_handler_bot_and_resolve():
    br = BotRegistry()
    info = br.register(
        session_id="sess-b1", instance_id="bot_pytest",
        description="run pytest", bot_mode="handler",
        subscribe_schemas=["pytest_run"], emit_schemas=["bot_reply"])
    assert isinstance(info, BotInfo)
    assert info.subscribe_schemas == ("pytest_run",)
    assert info.emit_schemas == ("bot_reply",)
    assert br.resolve_session("sess-b1").instance_id == "bot_pytest"
    assert br.resolve_instance_id("bot_pytest").bot_mode == "handler"


def test_subscribers_of_reverse_index():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["pytest_run"])
    br.register(session_id="s2", instance_id="bot_b", description="d",
                bot_mode="handler", subscribe_schemas=["pytest_run", "metric_log"])
    assert br.subscribers_of("pytest_run") == {"bot_a", "bot_b"}
    assert br.subscribers_of("metric_log") == {"bot_b"}
    assert br.subscribers_of("nope") == set()


def test_observer_bot_not_in_subscriber_index():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_obs", description="d", bot_mode="observer")
    assert br.observers() == {"bot_obs"}
    assert br.subscribers_of("anything") == set()


def test_unregister_removes_from_indexes():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["pytest_run"])
    br.unregister_session("s1")
    assert br.subscribers_of("pytest_run") == set()
    with pytest.raises(NotRegisteredError):
        br.resolve_instance_id("bot_a")


def test_reregister_same_instance_replaces_old_subscriptions():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["old_schema"])
    br.register(session_id="s2", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["new_schema"])
    assert br.subscribers_of("old_schema") == set()
    assert br.subscribers_of("new_schema") == {"bot_a"}
    assert br.resolve_instance_id("bot_a").session_id == "s2"


def test_list_bots_and_is_bot():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["x"])
    assert [b.instance_id for b in br.list_bots()] == ["bot_a"]
    assert br.is_bot("bot_a") is True
    assert br.is_bot("worker_x") is False


def test_resolve_session_unknown_raises():
    br = BotRegistry()
    with pytest.raises(NotRegisteredError):
        br.resolve_session("nope")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_bot_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.bot_registry'`

- [ ] **Step 3: bot_registry.py 구현** — `src/agent_agora/bot_registry.py`:

```python
"""v4 BotRegistry — bot-only namespace, parallel to InstanceRegistry (결정 16)."""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, replace
from typing import Literal

from agent_agora.registry import NotRegisteredError

BotMode = Literal["handler", "observer"]


@dataclass(frozen=True)
class BotInfo:
    instance_id: str
    session_id: str
    description: str
    bot_mode: BotMode
    subscribe_schemas: tuple[str, ...] = ()
    emit_schemas: tuple[str, ...] = ()
    registered_at: str = ""
    last_seen_at: str | None = None


class BotRegistry:
    """봇 전용 네임스페이스. subscribe schema -> 봇 역인덱스(fan-out 라우팅용)를 보관한다.
    재시작 시 복원하지 않는다 — 봇은 살아있는 MCP client 세션이라 재접속 시 재등록한다."""

    def __init__(self) -> None:
        self._by_session: dict[str, BotInfo] = {}
        self._by_instance: dict[str, BotInfo] = {}
        self._subscribers: dict[str, set[str]] = {}   # schema_name -> {handler bot id}
        self._observers: set[str] = set()
        self._lock = threading.Lock()

    def _detach_locked(self, info: BotInfo) -> None:
        """인덱스에서 한 봇을 떼어낸다. _lock 보유 상태에서 호출."""
        self._by_session.pop(info.session_id, None)
        self._by_instance.pop(info.instance_id, None)
        self._observers.discard(info.instance_id)
        for s in info.subscribe_schemas:
            subs = self._subscribers.get(s)
            if subs is not None:
                subs.discard(info.instance_id)
                if not subs:
                    self._subscribers.pop(s, None)

    def register(
        self,
        session_id: str,
        instance_id: str,
        description: str,
        bot_mode: BotMode,
        subscribe_schemas: tuple[str, ...] | list[str] = (),
        emit_schemas: tuple[str, ...] | list[str] = (),
    ) -> BotInfo:
        info = BotInfo(
            instance_id=instance_id, session_id=session_id, description=description,
            bot_mode=bot_mode,
            subscribe_schemas=tuple(subscribe_schemas),
            emit_schemas=tuple(emit_schemas),
            registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        with self._lock:
            prior = self._by_instance.get(instance_id)
            if prior is not None:
                self._detach_locked(prior)
            prior_sess = self._by_session.get(session_id)
            if prior_sess is not None:
                self._detach_locked(prior_sess)
            self._by_session[session_id] = info
            self._by_instance[instance_id] = info
            if bot_mode == "observer":
                self._observers.add(instance_id)
            else:
                for s in info.subscribe_schemas:
                    self._subscribers.setdefault(s, set()).add(instance_id)
        return info

    def unregister_session(self, session_id: str) -> None:
        with self._lock:
            info = self._by_session.get(session_id)
            if info is not None:
                self._detach_locked(info)

    def resolve_session(self, session_id: str) -> BotInfo:
        with self._lock:
            info = self._by_session.get(session_id)
        if info is None:
            raise NotRegisteredError(f"Bot session '{session_id}' is not registered")
        return info

    def resolve_instance_id(self, instance_id: str) -> BotInfo:
        with self._lock:
            info = self._by_instance.get(instance_id)
        if info is None:
            raise NotRegisteredError(f"Bot '{instance_id}' is not registered")
        return info

    def is_bot(self, instance_id: str) -> bool:
        with self._lock:
            return instance_id in self._by_instance

    def subscribers_of(self, schema_name: str) -> set[str]:
        """schema_name을 구독하는 handler 봇 instance_id 집합 (다봇 fan-out용)."""
        with self._lock:
            return set(self._subscribers.get(schema_name, set()))

    def observers(self) -> set[str]:
        with self._lock:
            return set(self._observers)

    def list_bots(self) -> list[BotInfo]:
        with self._lock:
            return list(self._by_instance.values())

    def touch_last_seen(self, instance_id: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            info = self._by_instance.get(instance_id)
            if info is None:
                return
            updated = replace(info, last_seen_at=now)
            self._by_instance[instance_id] = updated
            self._by_session[updated.session_id] = updated
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_bot_registry.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/bot_registry.py tests/test_v4_bot_registry.py
git commit -m "feat: BotRegistry — bot namespace + subscribe schema reverse index"
```

---

## Task 5: envelope.py — delivered_as 'subscribed'

**Files:**
- Modify: `src/agent_agora/envelope.py`
- Test: `tests/test_v3_envelope.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v3_envelope.py`에 추가:

```python
def test_make_envelope_accepts_subscribed_delivered_as():
    env = make_envelope(
        cmd_id="c1", source="s", target="t", payload={"msgtype": "x"},
        created_at="2026-01-01T00:00:00Z", conversation_id="conv1",
        delivered_as="subscribed",
    )
    assert env.delivered_as == "subscribed"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v3_envelope.py -v -k subscribed`
Expected: `make_envelope`에 런타임 검증이 없어 PASS할 수 있다 — 그렇다면 Step 3은 타입 힌트 정합만 수행. (이 테스트의 진짜 목적은 `"subscribed"` 값이 정상 통과함을 고정하는 것.)

- [ ] **Step 3: envelope.py 수정**

`Envelope` dataclass의 `delivered_as` 필드 타입을 교체:
```python
    delivered_as: Literal["primary", "cc", "subscribed"]
```
`make_envelope` 함수 시그니처의 `delivered_as` 파라미터 타입을 교체:
```python
    delivered_as: Literal["primary", "cc", "subscribed"] = "primary",
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v3_envelope.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/envelope.py tests/test_v3_envelope.py
git commit -m "feat: envelope delivered_as supports 'subscribed'"
```

---

## Task 6: BotRegistry 배선 — 동작 변경 없는 리팩터

> **ordering 핵심.** `Dispatcher` 생성자에 `bot_registry`를 주입하고 `_build_app`/`create_agora_app`/모든 테스트 fixture를 같은 커밋에서 갱신한다. `Dispatcher`는 `bot_registry`를 *저장만* 하고 아직 라우팅에 쓰지 않는다 — 동작은 완전히 동일하다. `_message_source` dict도 이 task에서 초기화한다(Task 7부터 사용).

**Files:**
- Modify: `src/agent_agora/dispatcher.py`, `src/agent_agora/server.py`, `src/agent_agora/__main__.py`
- Modify: `tests/conftest.py`, `tests/test_v3_dispatcher.py`, `test_v3_recovery.py`, `test_v3_ttl_gc.py`, `test_integration.py`, `test_v4_schema_enforcement.py`
- Test: `tests/test_main.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_main.py`에 추가:

```python
def test_build_app_wires_bot_registry(tmp_path):
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp = _build_app(agora_dir=agora_dir, port=0)
    bot_registry = mcp._agora_bot_registry
    assert bot_registry.list_bots() == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_main.py -v -k wires_bot`
Expected: FAIL — `AttributeError: ... _agora_bot_registry`

- [ ] **Step 3: Dispatcher 생성자 수정** — `dispatcher.py`:

import 추가(기존 import 블록):
```python
from agent_agora.bot_registry import BotRegistry
```

`Dispatcher.__init__` 시그니처에 `schema_registry` 다음 줄로 `bot_registry`를 추가(keyword-only 필수):
```python
        *,
        schema_registry: SchemaRegistry,
        bot_registry: BotRegistry,
        default_timeout_ms: int = 60000,
```

`__init__` 본문, `self._schema_registry = schema_registry` 다음 줄에 추가:
```python
        self._bot_registry = bot_registry
```

`__init__` 본문의 v3 state 초기화부(`self._last_dispatch_to: dict[str, str] = {}` 다음)에 추가:
```python
        # cmd_id -> source (bot_emit in_reply_to 라우팅용)
        self._message_source: dict[str, str] = {}
```

이 task에서 `_bot_registry`·`_message_source`는 *저장/초기화만* 한다 — 어디서도 읽지 않는다.

- [ ] **Step 4: create_agora_app 시그니처 수정** — `server.py`:

import 추가:
```python
from agent_agora.bot_registry import BotRegistry
```

`create_agora_app` 시그니처에 `schema_registry` 다음으로 `bot_registry`를 추가:
```python
def create_agora_app(
    agora_dir: Path,
    instance_registry: InstanceRegistry,
    schema_registry: SchemaRegistry,
    bot_registry: BotRegistry,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
) -> FastMCP:
```

본문은 변경하지 않는다 — `bot_registry`는 Task 11/12까지 미사용(미사용 인자 허용).

- [ ] **Step 5: __main__.py `_build_app` 수정**

`_build_app` 본문의 import 줄에 `BotRegistry` 추가:
```python
    from agent_agora.bot_registry import BotRegistry
```
(`from agent_agora.registry import InstanceRegistry` 줄 옆에 둔다.)

`instance_registry = InstanceRegistry()` 다음 줄에 추가:
```python
    bot_registry = BotRegistry()
```

`Dispatcher(...)` 생성 호출에 `schema_registry=schema_registry,` 다음 줄로 추가:
```python
        bot_registry=bot_registry,
```

`create_agora_app(...)` 호출에 `schema_registry=schema_registry,` 다음 줄로 추가:
```python
        bot_registry=bot_registry,
```

`mcp._agora_schema_registry = schema_registry` 다음 줄에 추가:
```python
    mcp._agora_bot_registry = bot_registry  # type: ignore[attr-defined]
```

- [ ] **Step 6: conftest.py — bot_registry fixture 추가**

`tests/conftest.py` 끝(`schema_registry` fixture 옆)에 추가:
```python
from agent_agora.bot_registry import BotRegistry  # noqa: E402


@pytest.fixture
def bot_registry():
    return BotRegistry()
```

- [ ] **Step 7: 모든 Dispatcher / create_agora_app 생성 사이트 갱신**

`grep -rn "Dispatcher(" tests/` 와 `grep -rn "create_agora_app(" tests/`로 모든 생성 지점을 찾는다. 각 `Dispatcher(...)` 호출에 `bot_registry=BotRegistry()`를 추가하고, 각 `create_agora_app(...)` 호출에 `bot_registry=...`를 추가한다. 해당 테스트 파일 상단에 `from agent_agora.bot_registry import BotRegistry` import를 추가한다.

예 — `tests/test_v3_dispatcher.py`의 fixture:
```python
# before
dispatcher = Dispatcher(registry, persistence, queue,
                        schema_registry=make_schema_registry(),
                        default_timeout_ms=500)
# after
dispatcher = Dispatcher(registry, persistence, queue,
                        schema_registry=make_schema_registry(),
                        bot_registry=BotRegistry(),
                        default_timeout_ms=500)
```

예 — `tests/test_v4_schema_enforcement.py`의 `app` fixture는 `create_agora_app`도 호출하므로 둘 다 갱신:
```python
dispatcher = Dispatcher(instance_registry, persistence, queue,
                        schema_registry=schema_registry, bot_registry=bot_registry,
                        default_timeout_ms=300)
mcp = create_agora_app(
    agora_dir=tmp_path, instance_registry=instance_registry,
    schema_registry=schema_registry, bot_registry=bot_registry,
    persistence=persistence, dispatcher=dispatcher, port=0)
```
(`app` fixture는 `bot_registry = BotRegistry()`를 fixture 본문에서 만들어 두 호출에 같은 인스턴스를 넘긴다. `setup` fixture는 `create_agora_app`을 안 쓰므로 `Dispatcher(...)`에만 `bot_registry=BotRegistry()`를 추가.)

대상 파일: `test_v3_dispatcher.py`, `test_v3_recovery.py`, `test_v3_ttl_gc.py`, `test_integration.py`, `test_v4_schema_enforcement.py` — 단 grep 결과를 신뢰하고 빠짐없이 적용.

- [ ] **Step 8: 전체 테스트 + 부팅 스모크**

Run: `pytest tests/ -v` — 전체 통과(171 + Task 1~5의 신규 테스트, 회귀 0 — 순수 리팩터).

Boot smoke (임시 dir 사용, Bash timeout ~8000ms):
`& 'C:\Users\Jooyo\AppData\Roaming\uv\tools\agent-agora\Scripts\python.exe' -m agent_agora --dir $env:TEMP\agora_smoke_p2t6 --port 8771 --no-tls --no-timeout`
Expected: `AgentAgora starting on ...` 출력, traceback 없음. 이후 임시 dir 삭제.

- [ ] **Step 9: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/server.py src/agent_agora/__main__.py tests/
git commit -m "refactor: wire BotRegistry through build_app/create_agora_app/Dispatcher (no behavior change)"
```

---

## Task 7: Dispatcher — dispatch() 봇 fan-out + target 생략

> `dispatch`가 봇 체커를 통과하도록 전면 개정한다 — `target`이 `str | None`, msgtype 구독 봇에 `subscribed` fan-out, observer에 `cc` fan-out, `target` 생략 시 schema-routed, 구독 봇 없고 target도 없으면 `no_route`. target이 봇인데 그 msgtype 미구독이면 `unhandled_schema`.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_routing.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_routing.py`:

```python
import pytest
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.bot_registry import BotRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.errors import AgoraError
from _helpers import make_schema_registry, tany, wf


def _register_pytest_schema(dispatcher):
    body = {
        "type": "object",
        "required": ["msgtype", "scenario"],
        "properties": {
            "msgtype": {"type": "string", "const": "pytest_run"},
            "scenario": {"type": "string"},
        },
        "additionalProperties": False,
    }
    dispatcher._schema_registry.register(
        "pytest_run", body, kind="bot-task", purpose="pytest 실행 요청")
    return {"msgtype": "pytest_run", "scenario": "smoke"}


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            registry, persistence, queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            default_timeout_ms=500)
        yield registry, dispatcher


@pytest.mark.asyncio
async def test_dispatch_fans_out_to_subscribing_bots(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=payload)
    inst2 = await dispatcher.wait("Inst2", timeout_ms=200)
    bot_a = await dispatcher.wait("bot_a", timeout_ms=200)
    assert inst2[0]["delivered_as"] == "primary"
    assert bot_a[0]["delivered_as"] == "subscribed"
    delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
    assert delivered == {"Inst2": "primary", "bot_a": "subscribed"}


@pytest.mark.asyncio
async def test_dispatch_target_omitted_routes_to_bots(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    bot_a = await dispatcher.wait("bot_a", timeout_ms=200)
    assert len(bot_a) == 1 and bot_a[0]["delivered_as"] == "subscribed"
    assert all(d["as"] == "subscribed" for d in res["dispatched_to"])
    assert res["target_inbox_depth_after"] == {}


@pytest.mark.asyncio
async def test_dispatch_target_omitted_no_subscriber_raises_no_route(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    assert ei.value.code == "no_route"


@pytest.mark.asyncio
async def test_dispatch_to_bot_target_not_subscribing_raises_unhandled(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["other_unused"])
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="bot_a", payload=payload)
    assert ei.value.code == "unhandled_schema"


@pytest.mark.asyncio
async def test_dispatch_observer_receives_cc(setup):
    registry, dispatcher = setup
    dispatcher._bot_registry.register(
        session_id="bo1", instance_id="bot_obs", description="d", bot_mode="observer")
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=wf("관찰"))
    obs = await dispatcher.wait("bot_obs", timeout_ms=200)
    assert len(obs) == 1 and obs[0]["delivered_as"] == "cc"


@pytest.mark.asyncio
async def test_dispatch_to_worker_still_works_unchanged(setup):
    registry, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m="hi"))
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    assert len(drained) == 1 and drained[0]["delivered_as"] == "primary"
```

> 이 테스트 파일은 `_helpers`를 import한다 — `tests/`는 `conftest.py`가 sys.path에 넣어둬 동작한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_routing.py -v -k "fans_out or target_omitted or to_bot_target or observer_receives or worker_still"`
Expected: FAIL — `target=None` 거부 / 봇이 메시지 못 받음.

- [ ] **Step 3: `dispatch` 메서드 전면 교체**

`dispatcher.py`의 `dispatch` 메서드 전체를 다음으로 교체:

```python
    async def dispatch(
        self,
        source: str,
        target: str | None,
        payload: Any,
        expect_result: bool = False,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low", "normal", "high"] = "normal",
        deadline_ts: str | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        if target is not None and (not isinstance(target, str) or not target):
            raise ValueError("target must be a non-empty instance_id string or None")
        msgtype = self._validate_payload(payload)
        payload_bytes = validate_payload_size(payload)
        priority_rank = validate_priority(priority)

        # target resolution — worker or bot (결정 22: 봇 체커 우선)
        target_kind: str | None = None  # "worker" | "bot"
        if target is not None:
            if self._bot_registry.is_bot(target):
                target_kind = "bot"
                bot_info = self._bot_registry.resolve_instance_id(target)
                if bot_info.bot_mode == "handler" and msgtype not in bot_info.subscribe_schemas:
                    raise AgoraError("unhandled_schema", bot=target, msgtype=msgtype)
            else:
                self._registry.resolve_instance_id(target)  # raises NotRegisteredError
                target_kind = "worker"
        if reply_to is not None:
            self._registry.resolve_instance_id(reply_to)
        cc_list = list(cc) if cc else []
        cc_list = [c for c in cc_list if c != source and c != target]
        if reply_to is not None and reply_to in cc_list:
            raise ValueError("instance cannot be both reply_to and cc")
        for c in cc_list:
            self._registry.resolve_instance_id(c)

        # 봇 체커 — msgtype 구독 handler 봇 + observer
        subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
        observer_bots = sorted(self._bot_registry.observers())
        if target is None and not subscriber_bots:
            raise AgoraError("no_route", msgtype=msgtype)

        cmd_id = str(uuid.uuid4())
        now = _now_iso()
        conv_id, is_new_conv, substituted = self._resolve_conversation_id(conversation_id, in_reply_to)

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            # primary inbox depth (target 있을 때만)
            if target is not None and len(self._queues[target]) >= self._max_inbox_depth:
                raise ValueError(f"inbox_full: {target} has {len(self._queues[target])} pending")
            cc_deliver: list[str] = []
            skipped_full: list[str] = []
            for c in cc_list:
                if len(self._queues[c]) >= self._max_inbox_depth:
                    skipped_full.append(c)
                else:
                    cc_deliver.append(c)

            if is_new_conv or conv_id not in self._conversations:
                self._conversations[conv_id] = self._new_conversation_state(kind="direct")
            state = self._conversations[conv_id]
            self._add_participant(state, source, role="primary", delivered=True)
            if target is not None:
                self._add_participant(state, target, role="primary", delivered=True)
            for c in cc_deliver:
                self._add_participant(state, c, role="cc", delivered=True)
            for c in skipped_full:
                self._add_participant(state, c, role="cc", delivered=False)
            state["last_message_at"] = now
            state["message_count"] += 1

            self._conversation_of[cmd_id] = conv_id
            self._message_source[cmd_id] = source

            def _make(tid: str, das: str, *, er: bool, cl: bool) -> Envelope:
                return make_envelope(
                    cmd_id=cmd_id, source=source, target=tid, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=er, reply_to=reply_to,
                    cc=(cc_list if cc_list else None),
                    delivered_as=das, dispatch_kind="direct",
                    in_reply_to=in_reply_to,
                    closing=cl,
                    priority=priority, deadline_ts=deadline_ts,
                )

            # primary envelope (target 있을 때만). primary/cc observer는 closing 플래그를
            # 그대로 싣는다(기존 동작 유지). 봇 fan-out 봉투는 closing=False — 봇은
            # conversation 종결 참가자가 아니다.
            primary_env: Envelope | None = None
            if target is not None:
                primary_env = _make(target, "primary", er=expect_result, cl=closing)
                self._queues[target].append(primary_env)
                self._last_dispatch_to[target] = now
                self._wake(target)

            if expect_result and target is not None and target != source and target_kind != "bot":
                self._in_flight.setdefault(source, {}).setdefault(cmd_id, set()).add(target)

            # cc observer envelopes (명시 cc)
            cc_envs: list[Envelope] = []
            for c in cc_deliver:
                e = _make(c, "cc", er=expect_result, cl=closing)
                cc_envs.append(e)
                self._queues[c].append(e)
                self._last_dispatch_to[c] = now
                self._wake(c)

            # subscriber 봇 fan-out (delivered_as=subscribed). target과 같은 봇은 중복 제외.
            sub_envs: list[Envelope] = []
            for bot_id in subscriber_bots:
                if bot_id == target:
                    continue
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                e = _make(bot_id, "subscribed", er=False, cl=False)
                sub_envs.append(e)
                self._queues[bot_id].append(e)
                self._add_participant(state, bot_id, role="cc", delivered=True)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)

            # observer 봇 fan-out (delivered_as=cc)
            obs_envs: list[Envelope] = []
            for bot_id in observer_bots:
                if bot_id == target or bot_id in subscriber_bots:
                    continue
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                e = _make(bot_id, "cc", er=False, cl=False)
                obs_envs.append(e)
                self._queues[bot_id].append(e)
                self._add_participant(state, bot_id, role="cc", delivered=True)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)

            # reply correlation: decrement in_flight for original source
            if in_reply_to is not None:
                original_conv = self._conversation_of.get(in_reply_to)
                if original_conv is not None:
                    for _original_sender, pending_map in self._in_flight.items():
                        s = pending_map.get(in_reply_to)
                        if s is not None and source in s:
                            s.discard(source)
                            if not s:
                                pending_map.pop(in_reply_to, None)

            # closing handling (primary source only)
            if closing and state["participants"].get(source, {}).get("role") == "primary":
                if source not in state["closed_by"]:
                    state["closed_by"].append(source)
                if state["status"] == "open":
                    state["status"] = "half_closed"
                self._maybe_close(conv_id, state)

            await self._persist_dispatch_txn(
                state=state, conv_id=conv_id, is_new_conv=is_new_conv,
                env=primary_env, cc_envs=cc_envs + sub_envs + obs_envs,
                skipped_full=skipped_full,
                payload_bytes=payload_bytes, priority_rank=priority_rank,
            )

            _to = _colored(target) if target is not None else "(schema-routed)"
            print(
                f"[agora] {_colored(source)} -> {_to}"
                + (f" (cc: {','.join(_colored(c) for c in cc_deliver)})" if cc_deliver else "")
                + (f" (bots: {','.join(_colored(b) for b in subscriber_bots)})" if subscriber_bots else "")
                + f" : {_fmt_payload(payload)}",
                flush=True,
            )

        dispatched_to: list[dict[str, str]] = []
        if target is not None:
            dispatched_to.append({"instance_id": target, "as": "primary"})
        dispatched_to += [{"instance_id": c, "as": "cc"} for c in cc_deliver]
        dispatched_to += [{"instance_id": b, "as": "subscribed"}
                          for b in subscriber_bots if b != target]
        return {
            "command_id": cmd_id,
            "created_at": now,
            "conversation_id": conv_id,
            "conversation_id_substituted": substituted,
            "dispatched_to": dispatched_to,
            "target_inbox_depth_after": (
                {target: len(self._queues[target])} if target is not None else {}),
            "skipped_full": skipped_full,
        }
```

> 변경 요약: `target: str | None`; 봇 체커 우선; `_make` 헬퍼로 envelope 생성 통일; subscriber/observer 봇 fan-out; `target` 생략 시 `no_route` 가드; `in_flight`는 worker target + `expect_result`일 때만(봇 target은 §9.4대로 무시); `cc_envs`를 한 번만 만들어 큐·persist에 재사용.

- [ ] **Step 4: `message_gc_sweep`에 `_message_source` eviction 추가**

`message_gc_sweep` 메서드의 `stale_cmds` 처리 루프를 찾는다:
```python
        stale_cmds = [cid for cid, conv in self._conversation_of.items() if conv in victim_ids]
        for cid in stale_cmds:
            self._conversation_of.pop(cid, None)
```
루프 본문에 한 줄 추가:
```python
        for cid in stale_cmds:
            self._conversation_of.pop(cid, None)
            self._message_source.pop(cid, None)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_v4_routing.py -v`
Expected: PASS.

- [ ] **Step 6: 회귀 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체). 단 `agora.dispatch` MCP 도구는 아직 `target` 필수 시그니처라 — server 도구 테스트가 깨지면 Task 12에서 고친다. 이 task에서 `pytest tests/`가 깨지는 건 **dispatcher 직접 호출 테스트뿐**이어야 하며 그건 모두 통과해야 한다. server.py를 경유하는 기존 테스트(`test_v4_schema_enforcement.py` 등)는 `agora.dispatch` 도구가 `dispatcher.dispatch(target=...)`를 호출하므로 `target`을 항상 넘겨 — 그대로 통과한다.

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_routing.py
git commit -m "feat: Dispatcher dispatch() bot fan-out + target-omitted schema routing"
```

---

## Task 8: Dispatcher — broadcast() 봇 fan-out

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_routing.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_routing.py`에 추가:

```python
@pytest.mark.asyncio
async def test_broadcast_fans_out_to_subscribing_bots(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.broadcast(source="Inst1", payload=payload)
    bot_a = await dispatcher.wait("bot_a", timeout_ms=200)
    assert len(bot_a) == 1 and bot_a[0]["delivered_as"] == "subscribed"
    inst2 = await dispatcher.wait("Inst2", timeout_ms=200)
    assert inst2[0]["delivered_as"] == "primary"
    delivered = {d["instance_id"]: d["as"] for d in res["dispatched_to"]}
    assert delivered["bot_a"] == "subscribed"


@pytest.mark.asyncio
async def test_broadcast_observer_receives_cc(setup):
    registry, dispatcher = setup
    dispatcher._bot_registry.register(
        session_id="bo1", instance_id="bot_obs", description="d", bot_mode="observer")
    await dispatcher.broadcast(source="Inst1", payload=wf("공지"))
    obs = await dispatcher.wait("bot_obs", timeout_ms=200)
    assert len(obs) == 1 and obs[0]["delivered_as"] == "cc"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_routing.py -v -k broadcast`
Expected: FAIL — 봇이 broadcast를 못 받음.

- [ ] **Step 3: `broadcast` 수정**

`broadcast` 메서드에서, `self._validate_payload(payload)` 줄을 다음으로 교체(반환값을 잡는다):
```python
        msgtype = self._validate_payload(payload)
```

`targets = [...]` 리스트 컴프리헨션 *다음 줄*에 추가:
```python
        subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
        observer_bots = sorted(self._bot_registry.observers())
```

`async with self._lock:` 블록 안, 워커 primary `for t in deliverable:` 루프(envelope 생성·enqueue)가 끝난 *다음*, `# closing → if broadcast announcement` 주석 *앞*에 추가:
```python
            # subscriber 봇 fan-out (delivered_as=subscribed)
            for bot_id in subscriber_bots:
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                s_env = make_envelope(
                    cmd_id=cmd_id, source=source, target=bot_id, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=False, reply_to=reply_to, cc=None,
                    delivered_as="subscribed", dispatch_kind="broadcast",
                    in_reply_to=in_reply_to,
                    closing=False, priority=priority, deadline_ts=deadline_ts,
                )
                envs.append(s_env)
                self._queues[bot_id].append(s_env)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)
            # observer 봇 fan-out (delivered_as=cc)
            for bot_id in observer_bots:
                if bot_id in subscriber_bots:
                    continue
                if len(self._queues[bot_id]) >= self._max_inbox_depth:
                    skipped_full.append(bot_id)
                    continue
                o_env = make_envelope(
                    cmd_id=cmd_id, source=source, target=bot_id, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=False, reply_to=reply_to, cc=None,
                    delivered_as="cc", dispatch_kind="broadcast",
                    in_reply_to=in_reply_to,
                    closing=False, priority=priority, deadline_ts=deadline_ts,
                )
                envs.append(o_env)
                self._queues[bot_id].append(o_env)
                self._last_dispatch_to[bot_id] = now
                self._wake(bot_id)
            self._message_source[cmd_id] = source
```

> 봇 envelope을 `envs`에 추가하면 기존 `_persist_dispatch_txn(cc_envs=envs, ...)`가 그대로 영속한다. 봇은 `_add_participant`로 추가하지 않으므로 broadcast의 `closing` 즉시-종결이 봇을 `closed_by`에 넣지 않는다 — 의도된 동작.

`broadcast`의 반환 dict `dispatched_to`를 교체:
```python
            "dispatched_to": [{"instance_id": t, "as": "primary"} for t in deliverable]
                + [{"instance_id": b, "as": "subscribed"} for b in subscriber_bots]
                + [{"instance_id": b, "as": "cc"} for b in observer_bots
                   if b not in subscriber_bots],
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_routing.py
git commit -m "feat: Dispatcher broadcast() bot fan-out"
```

---

## Task 9: Dispatcher — bot_emit()

> 봇이 처리 결과를 흘리는 전용 메서드(결정 25). `in_reply_to` 지정 시 원 메시지의 source로 라우팅, 미지정 시 payload msgtype 구독 봇에 schema-routed fan-out. 항상 observer cc.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_routing.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_routing.py`에 추가:

```python
def _bot_reply(result="ok"):
    return {"msgtype": "bot_reply", "from": "bot_a",
            "ts": "2026-01-01T00:00:00Z", "result": result}


@pytest.mark.asyncio
async def test_bot_emit_in_reply_to_routes_to_original_source(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    res = await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    cmd_id = res["command_id"]
    await dispatcher.bot_emit(source="bot_a", payload=_bot_reply(), in_reply_to=cmd_id)
    inst1 = await dispatcher.wait("Inst1", timeout_ms=200)
    assert len(inst1) == 1
    assert inst1[0]["payload"]["msgtype"] == "bot_reply"
    assert inst1[0]["in_reply_to"] == cmd_id


@pytest.mark.asyncio
async def test_bot_emit_without_in_reply_to_fans_out_to_subscribers(setup):
    registry, dispatcher = setup
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"type": "string", "const": "metric_log"}},
            "additionalProperties": True}
    dispatcher._schema_registry.register("metric_log", body, kind="bot-task", purpose="metric")
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_metric", description="d",
        bot_mode="handler", subscribe_schemas=["metric_log"])
    await dispatcher.bot_emit(source="bot_src", payload={"msgtype": "metric_log", "v": 1})
    got = await dispatcher.wait("bot_metric", timeout_ms=200)
    assert len(got) == 1 and got[0]["delivered_as"] == "subscribed"


@pytest.mark.asyncio
async def test_bot_emit_validates_payload(setup):
    registry, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.bot_emit(source="bot_a", payload={"no": "msgtype"})
    assert ei.value.code == "payload_missing_msgtype"


@pytest.mark.asyncio
async def test_bot_emit_in_reply_to_unknown_cmd_no_crash(setup):
    registry, dispatcher = setup
    # in_reply_to that maps to no known source — emit becomes observer-only (no reply_target)
    res = await dispatcher.bot_emit(source="bot_a", payload=_bot_reply(),
                                    in_reply_to="cmd-never-existed")
    assert res["dispatched_to"] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_routing.py -v -k bot_emit`
Expected: FAIL — `AttributeError: 'Dispatcher' object has no attribute 'bot_emit'`

- [ ] **Step 3: `bot_emit` 구현** — `dispatcher.py`의 `Dispatcher`에 메서드 추가(`broadcast` 다음):

```python
    async def bot_emit(
        self,
        source: str,
        payload: Any,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """봇 결과 emit (결정 25). in_reply_to 지정 시 원 메시지의 source로 라우팅,
        미지정 시 payload msgtype 구독 봇에 schema-routed fan-out. 항상 observer cc."""
        if self._closed:
            raise DispatcherClosed("Dispatcher is closed")
        msgtype = self._validate_payload(payload)
        payload_bytes = validate_payload_size(payload)
        priority_rank = validate_priority("normal")

        reply_target: str | None = None
        if in_reply_to is not None:
            reply_target = self._message_source.get(in_reply_to)
            if reply_target is None:
                reply_target = self._persistence.lookup_source_for(in_reply_to)
        subscriber_bots: list[str] = []
        if in_reply_to is None:
            subscriber_bots = sorted(self._bot_registry.subscribers_of(msgtype))
        observer_bots = sorted(self._bot_registry.observers())

        cmd_id = str(uuid.uuid4())
        now = _now_iso()
        conv_id, is_new_conv, substituted = self._resolve_conversation_id(None, in_reply_to)

        async with self._lock:
            if self._closed:
                raise DispatcherClosed("Dispatcher is closed")
            if is_new_conv or conv_id not in self._conversations:
                self._conversations[conv_id] = self._new_conversation_state(kind="direct")
            state = self._conversations[conv_id]
            self._add_participant(state, source, role="cc", delivered=True)
            state["last_message_at"] = now
            state["message_count"] += 1
            self._conversation_of[cmd_id] = conv_id
            self._message_source[cmd_id] = source

            envs: list[Envelope] = []
            delivered: list[dict[str, str]] = []
            skipped_full: list[str] = []

            def _enqueue(tid: str, das: str) -> None:
                if len(self._queues[tid]) >= self._max_inbox_depth:
                    skipped_full.append(tid)
                    return
                e = make_envelope(
                    cmd_id=cmd_id, source=source, target=tid, payload=payload,
                    created_at=now, conversation_id=conv_id,
                    expect_result=False, reply_to=None, cc=None,
                    delivered_as=das, dispatch_kind="direct",
                    in_reply_to=in_reply_to, closing=False,
                    priority="normal", deadline_ts=None,
                )
                envs.append(e)
                self._queues[tid].append(e)
                self._add_participant(
                    state, tid, role="primary" if das == "primary" else "cc", delivered=True)
                self._last_dispatch_to[tid] = now
                self._wake(tid)
                delivered.append({"instance_id": tid, "as": das})

            if reply_target is not None:
                _enqueue(reply_target, "primary")
            for bot_id in subscriber_bots:
                if bot_id == reply_target:
                    continue
                _enqueue(bot_id, "subscribed")
            for bot_id in observer_bots:
                if bot_id == reply_target or bot_id in subscriber_bots:
                    continue
                _enqueue(bot_id, "cc")

            await self._persist_dispatch_txn(
                state=state, conv_id=conv_id, is_new_conv=is_new_conv,
                env=None, cc_envs=envs, skipped_full=skipped_full,
                payload_bytes=payload_bytes, priority_rank=priority_rank,
            )
            print(
                f"[agora] {_colored(source)} bot_emit"
                + (f" -> {_colored(reply_target)}" if reply_target else " (schema-routed)")
                + f" : {_fmt_payload(payload)}",
                flush=True,
            )

        return {
            "command_id": cmd_id, "created_at": now, "conversation_id": conv_id,
            "conversation_id_substituted": substituted,
            "dispatched_to": delivered, "skipped_full": skipped_full,
        }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_routing.py
git commit -m "feat: Dispatcher.bot_emit — in_reply_to routing + schema-routed fan-out (결정 25)"
```

---

## Task 10: Dispatcher — wait() 봇 instance_id resolution

> 봇도 `agora.wait` long-poll client다. `wait`는 `instance_id`가 워커든 봇이든 해소해야 한다.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_routing.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_routing.py`에 추가:

```python
@pytest.mark.asyncio
async def test_bot_can_wait_even_though_not_in_instance_registry(setup):
    registry, dispatcher = setup
    payload = _register_pytest_schema(dispatcher)
    dispatcher._bot_registry.register(
        session_id="bs1", instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["pytest_run"])
    await dispatcher.dispatch(source="Inst1", target=None, payload=payload)
    # bot_a is NOT in InstanceRegistry — wait must still resolve it via BotRegistry
    got = await dispatcher.wait("bot_a", timeout_ms=200)
    assert len(got) == 1


@pytest.mark.asyncio
async def test_wait_unknown_id_still_raises(setup):
    registry, dispatcher = setup
    from agent_agora.registry import NotRegisteredError
    with pytest.raises(NotRegisteredError):
        await dispatcher.wait("ghost_nobody", timeout_ms=50)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_routing.py -v -k "bot_can_wait or wait_unknown"`
Expected: `test_bot_can_wait...` FAIL — `NotRegisteredError: Instance 'bot_a' is not registered`.

- [ ] **Step 3: `wait` 수정**

`wait` 메서드 초반의 줄을 교체:
```python
        # before
        self._registry.resolve_instance_id(instance_id)
        # after — instance_id는 worker 또는 bot일 수 있다 (봇도 wait long-poll client)
        if not self._bot_registry.is_bot(instance_id):
            self._registry.resolve_instance_id(instance_id)
```

`wait` 메서드에는 `self._registry.touch_last_seen(instance_id)` 호출이 2곳(timeout 분기 + 정상 분기) 있다. 각각을 다음 헬퍼 호출로 바꾼다. 먼저 `Dispatcher`에 헬퍼 메서드를 추가(`wait` 메서드 위):
```python
    def _touch_last_seen(self, instance_id: str) -> None:
        if self._bot_registry.is_bot(instance_id):
            self._bot_registry.touch_last_seen(instance_id)
        else:
            self._registry.touch_last_seen(instance_id)
```
그리고 `wait` 안의 `self._registry.touch_last_seen(instance_id)` 2곳을 모두 `self._touch_last_seen(instance_id)`로 교체.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_routing.py
git commit -m "feat: Dispatcher.wait resolves bot instance_ids via BotRegistry"
```

---

## Task 11: server.py — agora.register_bot 도구 + schema diff preflight

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v4_bots.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_bots.py`:

```python
import json
import pytest
from agent_agora.server import create_agora_app
from agent_agora.registry import InstanceRegistry
from agent_agora.bot_registry import BotRegistry
from agent_agora.dispatcher import Dispatcher
from agent_agora.persistence import Persistence, AsyncWriteQueue
from _helpers import make_schema_registry


class FakeCtx:
    """_session_id_from_ctx가 읽는 ctx.request_context.request.headers를 흉내낸다."""
    def __init__(self, session_id):
        self.request_context = type("RC", (), {"request": type("R", (), {
            "headers": {"mcp-session-id": session_id}})()})()


def _tool(mcp, name):
    return mcp._tool_manager.get_tool(name).fn


@pytest.fixture
async def app(tmp_path):
    instance_registry = InstanceRegistry()
    bot_registry = BotRegistry()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(
            instance_registry, persistence, queue,
            schema_registry=schema_registry, bot_registry=bot_registry,
            default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, bot_registry=bot_registry,
            persistence=persistence, dispatcher=dispatcher, port=0)
        yield mcp, instance_registry, bot_registry, schema_registry


@pytest.mark.asyncio
async def test_register_bot_handler_succeeds(app):
    mcp, _, bot_registry, schema_reg = app
    schema_reg.register(
        "pytest_run",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "pytest_run"}}},
        kind="bot-task", purpose="pytest")
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a",
        description="run pytest", bot_mode="handler",
        subscribe_schemas=["pytest_run"]))
    assert res["status"] == "ok"
    assert bot_registry.resolve_instance_id("bot_a").description == "run pytest"


@pytest.mark.asyncio
async def test_register_bot_missing_description_rejected(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="",
        bot_mode="handler", subscribe_schemas=["x"]))
    assert "description이 필수" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_handler_empty_subscribe_rejected(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=[]))
    assert "구독 schema가 비어" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_subscribing_conversation_kind_rejected(app):
    mcp, *_ = app
    # worker_freeform is conversation kind
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["worker_freeform"]))
    assert "conversation kind" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_with_inline_schemas(app):
    mcp, _, _, schema_reg = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["build_run"],
        schemas={"build_run": {
            "kind": "bot-task", "purpose": "빌드 실행",
            "body": {"type": "object", "required": ["msgtype"],
                     "properties": {"msgtype": {"const": "build_run"}}}}}))
    assert res["status"] == "ok"
    assert schema_reg.get("build_run").kind == "bot-task"


@pytest.mark.asyncio
async def test_register_bot_schema_diff_preflight_blocks(app):
    mcp, _, _, schema_reg = app
    body_v1 = {"type": "object", "required": ["msgtype"],
               "properties": {"msgtype": {"const": "build_run"}}}
    schema_reg.register("build_run", body_v1, kind="bot-task", purpose="v1")
    body_v2 = dict(body_v1, required=["msgtype", "extra"])
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-1"), instance_id="bot_a", description="d",
        bot_mode="handler", subscribe_schemas=["build_run"],
        schemas={"build_run": {"kind": "bot-task", "purpose": "v2", "body": body_v2}}))
    assert "이미 등록됨" in res["error"]


@pytest.mark.asyncio
async def test_register_bot_observer_mode(app):
    mcp, _, bot_registry, _ = app
    res = json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx("bot-sess-obs"), instance_id="bot_obs", description="archiver",
        bot_mode="observer"))
    assert res["status"] == "ok"
    assert bot_registry.observers() == {"bot_obs"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_bots.py -v`
Expected: FAIL — `agora.register_bot` 도구 없음.

- [ ] **Step 3: server.py에 register_bot 추가**

import 추가(기존 import 블록에 `Literal`은 이미 있음 — 확인):
```python
from agent_agora.bot_registry import BotRegistry  # 이미 Task 6에서 추가됨 — 확인만
```

`agora.register` 도구 정의 *다음*에 추가:
```python
    @mcp.tool(name="agora.register_bot")
    async def agora_register_bot(
        ctx: Context,
        instance_id: str,
        description: str,
        bot_mode: Literal["handler", "observer"] = "handler",
        subscribe_schemas: list[str] | None = None,
        emit_schemas: list[str] | None = None,
        schemas: dict[str, dict] | None = None,
    ) -> str:
        """Register this session as a bot (schema subscriber). 결정 16·25.

        bot_mode='handler': subscribe_schemas (모두 bot-task kind) 필수.
        bot_mode='observer': schema 무관 전체 메시지를 cc로 수신.
        schemas: 신규 schema 동시 등록. {name: {kind, purpose, body}} (kind는 'bot-task').
        """
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        subscribe = list(subscribe_schemas or [])
        emit = list(emit_schemas or [])
        schemas = schemas or {}
        try:
            if not description:
                raise AgoraError("description_required")
            if bot_mode == "handler" and not subscribe:
                raise AgoraError("subscribe_required")

            # (1) inline schemas 사전 검증 — diff preflight (§3.3, §9.6)
            for name, defn in schemas.items():
                if defn.get("kind") != "bot-task":
                    raise AgoraError("schema_kind_not_bot_task", name=name)
                existing = schema_registry.get(name)
                if existing is not None and existing.body != defn.get("body"):
                    raise AgoraError("schema_immutable", name=name)
            # (2) 일괄 등록 — 모두 검증 통과 후
            for name, defn in schemas.items():
                schema_registry.register(
                    name, defn["body"], kind="bot-task",
                    purpose=defn.get("purpose", ""), registered_by=instance_id)
                persistence.save_schema(
                    name, defn["body"], kind="bot-task",
                    purpose=defn.get("purpose", ""), registered_by=instance_id)
            # (3) 구독 schema 검증 — 존재 + bot-task kind
            if bot_mode == "handler":
                for s in subscribe:
                    entry = schema_registry.get(s)
                    if entry is None:
                        raise AgoraError("unknown_msgtype", msgtype=s)
                    if entry.kind != "bot-task":
                        raise AgoraError("cannot_subscribe_conversation", name=s)

            info = bot_registry.register(
                session_id=session_id, instance_id=instance_id,
                description=description, bot_mode=bot_mode,
                subscribe_schemas=subscribe if bot_mode == "handler" else (),
                emit_schemas=emit if bot_mode == "handler" else ())
            persistence.save_bot_subscriptions(
                instance_id, subscribe=list(info.subscribe_schemas),
                emit=list(info.emit_schemas))
        except AgoraError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({
            "status": "ok", "instance_id": info.instance_id,
            "bot_mode": info.bot_mode,
            "subscribe_schemas": list(info.subscribe_schemas),
            "emit_schemas": list(info.emit_schemas),
            "registered_at": info.registered_at,
        })
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_bots.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 회귀 확인**

Run: `pytest tests/ -v`
Expected: PASS (전체)

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_bots.py
git commit -m "feat: agora.register_bot tool + schema diff preflight (§3.3)"
```

---

## Task 12: server.py — bots / find / bot_emit / dispatch·broadcast·wait 봇 대응

> 봇 발견·결과 emit 도구를 추가하고, 기존 도구를 봇 인지하도록 보강한다 — `agora.dispatch`는 `target` 선택적 + 봇 호출 차단, `agora.broadcast`는 봇 호출 차단, `agora.wait`는 봇 세션 resolution.

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v4_bots.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_bots.py`에 추가:

```python
@pytest.mark.asyncio
async def test_bots_lists_only_bots_instances_lists_only_workers(app):
    mcp, instance_registry, bot_registry, schema_reg = app
    instance_registry.register("ws1", "worker_x")
    schema_reg.register("x_task",
        {"type": "object", "properties": {"msgtype": {"const": "x_task"}}},
        kind="bot-task", purpose="p")
    bot_registry.register(session_id="bs1", instance_id="bot_x", description="d",
                          bot_mode="handler", subscribe_schemas=["x_task"])
    bots = json.loads(await _tool(mcp, "agora.bots")())["bots"]
    instances = json.loads(await _tool(mcp, "agora.instances")())["instances"]
    assert {b["instance_id"] for b in bots} == {"bot_x"}
    assert {i["instance_id"] for i in instances} == {"worker_x"}


@pytest.mark.asyncio
async def test_find_returns_workers_and_bots_with_kind(app):
    mcp, instance_registry, bot_registry, schema_reg = app
    instance_registry.register("ws1", "worker_build", description="build helper")
    schema_reg.register("build_task",
        {"type": "object", "properties": {"msgtype": {"const": "build_task"}}},
        kind="bot-task", purpose="p")
    bot_registry.register(session_id="bs1", instance_id="bot_build",
                          description="build bot", bot_mode="handler",
                          subscribe_schemas=["build_task"])
    found = json.loads(await _tool(mcp, "agora.find")("build"))["results"]
    kinds = {r["instance_id"]: r["kind"] for r in found}
    assert kinds == {"worker_build": "worker", "bot_build": "bot"}


@pytest.mark.asyncio
async def test_bot_emit_requires_bot_caller(app):
    mcp, instance_registry, *_ = app
    instance_registry.register("ws1", "worker_x")
    res = json.loads(await _tool(mcp, "agora.bot_emit")(
        FakeCtx("ws1"),
        payload={"msgtype": "bot_reply", "from": "worker_x",
                 "ts": "2026-01-01T00:00:00Z", "result": "x"}))
    assert "봇만 호출" in res["error"]


@pytest.mark.asyncio
async def test_worker_dispatch_to_bot_then_bot_emit_chain(app):
    mcp, instance_registry, bot_registry, schema_reg = app
    schema_reg.register("ping_task",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "ping_task"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    instance_registry.register("ws1", "worker_x")
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("bs1"), instance_id="bot_p", description="d",
        bot_mode="handler", subscribe_schemas=["ping_task"])
    # worker dispatches with target omitted -> schema-routed to bot
    disp = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "ping_task", "v": 1}))
    assert disp["status"] == "ok"
    got = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("bs1"), timeout_ms=200))
    assert len(got["commands"]) == 1
    cmd_id = got["commands"][0]["id"]
    # bot emits a result back to the original caller
    await _tool(mcp, "agora.bot_emit")(
        FakeCtx("bs1"),
        payload={"msgtype": "bot_reply", "from": "bot_p",
                 "ts": "2026-01-01T00:00:00Z", "result": {"pong": 1}},
        in_reply_to=cmd_id)
    reply = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("ws1"), timeout_ms=200))
    assert reply["commands"][0]["payload"]["result"] == {"pong": 1}


@pytest.mark.asyncio
async def test_bot_cannot_call_dispatch(app):
    mcp, _, bot_registry, schema_reg = app
    schema_reg.register("t1",
        {"type": "object", "properties": {"msgtype": {"const": "t1"}}},
        kind="bot-task", purpose="p")
    await _tool(mcp, "agora.register_bot")(
        FakeCtx("bs1"), instance_id="bot_d", description="d",
        bot_mode="handler", subscribe_schemas=["t1"])
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("bs1"), payload={"msgtype": "t1"}, target="bot_d"))
    assert "봇은" in res["error"] and "bot_emit" in res["error"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_v4_bots.py -v -k "bots_lists or find_returns or bot_emit_requires or chain or bot_cannot"`
Expected: FAIL.

- [ ] **Step 3: server.py 수정**

**(a) module-level 헬퍼** — `server.py` 상단(함수 밖, `_session_id_from_ctx` 아래)에 추가:
```python
def _session_is_bot(bot_registry: BotRegistry, session_id: str) -> bool:
    try:
        bot_registry.resolve_session(session_id)
        return True
    except NotRegisteredError:
        return False
```

**(b) `agora.bots` 도구** — `agora.instances` 도구 *다음*에 추가:
```python
    @mcp.tool(name="agora.bots")
    async def agora_bots() -> str:
        """List registered bots only (결정 16 — workers excluded)."""
        items = [
            {
                "instance_id": b.instance_id, "description": b.description,
                "bot_mode": b.bot_mode,
                "subscribe_schemas": list(b.subscribe_schemas),
                "emit_schemas": list(b.emit_schemas),
                "registered_at": b.registered_at, "last_seen_at": b.last_seen_at,
            }
            for b in bot_registry.list_bots()
        ]
        return json.dumps({"bots": items}, ensure_ascii=False)
```

> `agora.bots`는 `inbox_depth`를 노출하지 않는다 — `dispatcher.peek`는 `InstanceRegistry` 기준이라 봇(별도 네임스페이스)의 큐 깊이를 못 준다. spec §3.9의 `agora.bots` 요구 필드(bot_mode·description·subscribe_schemas·emit_schemas)에 inbox_depth는 없다.

**(c) `agora.find` 교체** — 기존 `agora_find` 함수 전체를 교체(워커+봇 검색, 반환 키 `instances` → `results`):
```python
    @mcp.tool(name="agora.find")
    async def agora_find(query: str) -> str:
        """Search workers AND bots. Each result tagged kind: 'worker' | 'bot'."""
        if not query:
            return json.dumps({"results": []})
        q = query.lower()
        results = []
        for i in instance_registry.list_instances():
            if q in i.instance_id.lower() or q in i.role.lower() or q in i.description.lower():
                results.append({
                    "kind": "worker", "instance_id": i.instance_id,
                    "role": i.role, "description": i.description,
                    "registered_at": i.registered_at,
                })
        for b in bot_registry.list_bots():
            hay = (b.instance_id + " " + b.description + " "
                   + " ".join(b.subscribe_schemas)).lower()
            if q in hay:
                results.append({
                    "kind": "bot", "instance_id": b.instance_id,
                    "description": b.description, "bot_mode": b.bot_mode,
                    "subscribe_schemas": list(b.subscribe_schemas),
                    "registered_at": b.registered_at,
                })
        return json.dumps({"results": results}, ensure_ascii=False)
```

**(d) `agora.dispatch` 수정** — `target`을 optional로. `target`에 기본값을 주려면 기본값 없는 `payload`가 뒤에 올 수 없으므로 `payload`를 `target`보다 앞으로 옮긴다(MCP·테스트 모두 keyword 호출이라 안전). `agora_dispatch` 시그니처를 교체:
```python
    @mcp.tool(name="agora.dispatch")
    async def agora_dispatch(
        ctx: Context,
        payload: Any,
        target: str | None = None,
        expect_result: bool = False,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        in_reply_to: str | None = None,
        conversation_id: str | None = None,
        closing: bool = False,
        priority: Literal["low", "normal", "high"] = "normal",
        deadline_ts: str | None = None,
    ) -> str:
```
`agora_dispatch` 본문의 source 해석부를 교체(두 단계로 풀고 봇 차단 삽입):
```python
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        if _session_is_bot(bot_registry, session_id):
            return json.dumps({"error": "[agora] 봇은 agora.dispatch를 호출할 수 없습니다. agora.bot_emit을 쓰세요."})
        try:
            source = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
```
나머지 본문(`dispatcher.dispatch(source=source, target=target, payload=payload, ...)`)은 keyword 호출이라 그대로 둔다.

**(e) `agora.broadcast` 수정** — `agora_broadcast` 본문의 source 해석부도 동일하게 두 단계로 풀고 봇 차단 삽입:
```python
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        if _session_is_bot(bot_registry, session_id):
            return json.dumps({"error": "[agora] 봇은 agora.broadcast를 호출할 수 없습니다. agora.bot_emit을 쓰세요."})
        try:
            source = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError as e:
            return json.dumps({"error": str(e)})
```

**(f) `agora.wait` 수정** — `agora_wait` 본문의 session 해석부를 교체(워커/봇 양쪽 시도):
```python
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        try:
            who = instance_registry.resolve_session(session_id).instance_id
        except NotRegisteredError:
            try:
                who = bot_registry.resolve_session(session_id).instance_id
            except NotRegisteredError as e:
                return json.dumps({"error": str(e)})
```
이후 `dispatcher.wait(instance_id=info.instance_id, ...)` 호출의 `info.instance_id`를 `who`로 교체. (기존 `agora_wait`는 `info`를 `instance_registry.resolve_session(...)` 결과로 잡았다 — 위 교체로 `info`가 사라지므로 `who`를 쓴다.)

**(g) `agora.bot_emit` 도구 추가** — `agora.close_thread` 도구 *다음*에 추가:
```python
    @mcp.tool(name="agora.bot_emit")
    async def agora_bot_emit(
        ctx: Context,
        payload: dict,
        in_reply_to: str | None = None,
    ) -> str:
        """Emit a bot result. Bots only. in_reply_to 지정 시 원 caller로,
        미지정 시 payload msgtype 구독 봇에 fan-out (결정 25)."""
        try:
            session_id = _session_id_from_ctx(ctx)
        except RuntimeError as e:
            return json.dumps({"error": f"Session context unavailable: {e}"})
        try:
            bot = bot_registry.resolve_session(session_id)
        except NotRegisteredError:
            return json.dumps({"error": str(AgoraError("bot_emit_not_a_bot"))})
        try:
            result = await dispatcher.bot_emit(
                source=bot.instance_id, payload=payload, in_reply_to=in_reply_to)
            return json.dumps({"status": "ok", **result}, ensure_ascii=False)
        except (ValueError, NotRegisteredError) as e:
            return json.dumps({"error": str(e)})
        except DispatcherClosed:
            return json.dumps({"error": "server is shutting down"})
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_v4_bots.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 회귀 확인 — agora.find 반환 키 변경 대응**

Run: `pytest tests/ -v`
`agora.find`의 반환 키가 `instances` → `results`로 바뀌었다. 기존 테스트(`test_main.py`/`test_integration.py` 등)가 `agora.find` 결과에서 `["instances"]`를 읽으면 깨진다 — 깨지는 테스트의 해당 부분을 `["results"]`로 수정한다. 결과 항목이 이제 `kind` 필드를 갖지만 instance_id만 보는 assert는 그대로 통과한다.
Expected (수정 후): PASS (전체)

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py tests/
git commit -m "feat: agora.bots/bot_emit tools, find worker+bot search, dispatch target-optional + bot blocking"
```

---

## Task 13: §8.8 통합 테스트 + backlog 갱신

**Files:**
- Modify: `tests/test_v4_bots.py` (추가)
- Modify: `docs/backlog.md`

- [ ] **Step 1: 통합 테스트 작성** — `tests/test_v4_bots.py`에 추가:

```python
async def _register_bot(mcp, sess, iid, subscribe, mode="handler"):
    return json.loads(await _tool(mcp, "agora.register_bot")(
        FakeCtx(sess), instance_id=iid, description="d",
        bot_mode=mode, subscribe_schemas=subscribe))


@pytest.mark.asyncio
async def test_multi_bot_subscription_fan_out(app):
    """같은 schema를 N봇이 구독하면 한 메시지가 N봇 모두에 fan-out (결정 25)."""
    mcp, instance_registry, _, schema_reg = app
    schema_reg.register("pytest_run",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "pytest_run"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    await _register_bot(mcp, "bs1", "bot_a", ["pytest_run"])
    await _register_bot(mcp, "bs2", "bot_b", ["pytest_run"])
    instance_registry.register("ws1", "worker_x")
    await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "pytest_run", "scenario": "s"})
    a = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("bs1"), timeout_ms=200))
    b = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("bs2"), timeout_ms=200))
    assert len(a["commands"]) == 1 and len(b["commands"]) == 1


@pytest.mark.asyncio
async def test_observer_receives_all_messages(app):
    """observer는 schema 무관 모든 메시지를 cc로 받는다."""
    mcp, instance_registry, _, _ = app
    await _register_bot(mcp, "bo1", "bot_obs", [], mode="observer")
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    await _tool(mcp, "agora.dispatch")(FakeCtx("ws1"), target="worker_y",
        payload={"msgtype": "worker_freeform", "type": "task",
                 "from": "worker_x", "ts": "2026-01-01T00:00:00Z", "message": "hi"})
    obs = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("bo1"), timeout_ms=200))
    assert len(obs["commands"]) == 1
    assert obs["commands"][0]["delivered_as"] == "cc"


@pytest.mark.asyncio
async def test_no_route_when_no_subscriber_and_no_target(app):
    """target 생략 + 구독 봇 없음 → no_route 에러."""
    mcp, instance_registry, _, schema_reg = app
    schema_reg.register("orphan_task",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "orphan_task"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    instance_registry.register("ws1", "worker_x")
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "orphan_task"}))
    assert "구독하는 봇이 없고" in res["error"]


@pytest.mark.asyncio
async def test_worker_freeform_regression_through_broker(app):
    """v3 워커 payload(worker_freeform + 보조필드)가 broker를 통과한다 (§9.1)."""
    mcp, instance_registry, _, _ = app
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y",
        payload={"msgtype": "worker_freeform", "type": "reply", "from": "worker_x",
                 "ts": "2026-01-01T00:00:00Z", "message": "자유 텍스트",
                 "in_reply_to": "abc", "subject": "보조필드"}))
    assert res["status"] == "ok"


@pytest.mark.asyncio
async def test_bot_error_emit_reaches_caller(app):
    """봇이 bot_error를 in_reply_to로 emit하면 원 caller가 받는다 (§3.7)."""
    mcp, instance_registry, _, schema_reg = app
    schema_reg.register("job",
        {"type": "object", "required": ["msgtype"],
         "properties": {"msgtype": {"const": "job"}}, "additionalProperties": True},
        kind="bot-task", purpose="p")
    instance_registry.register("ws1", "worker_x")
    await _register_bot(mcp, "bs1", "bot_j", ["job"])
    disp = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), payload={"msgtype": "job"}))
    cmd_id = disp["command_id"]
    await _tool(mcp, "agora.bot_emit")(
        FakeCtx("bs1"),
        payload={"msgtype": "bot_error", "from": "bot_j",
                 "ts": "2026-01-01T00:00:00Z",
                 "error_code": "boom", "error_message": "handler failed"},
        in_reply_to=cmd_id)
    reply = json.loads(await _tool(mcp, "agora.wait")(FakeCtx("ws1"), timeout_ms=200))
    assert reply["commands"][0]["payload"]["error_code"] == "boom"
```

- [ ] **Step 2: 통합 테스트 통과 확인**

Run: `pytest tests/test_v4_bots.py -v`
Expected: PASS (전체)

- [ ] **Step 3: 전체 테스트 + 부팅 스모크**

Run: `pytest tests/ -v` — 전체 통과, 회귀 0.

Boot smoke (임시 dir, Bash timeout ~8000ms):
`& 'C:\Users\Jooyo\AppData\Roaming\uv\tools\agent-agora\Scripts\python.exe' -m agent_agora --dir $env:TEMP\agora_smoke_p2t13 --port 8772 --no-tls --no-timeout`
Expected: `AgentAgora starting on ...`, traceback 없음. 이후 임시 dir 삭제.

- [ ] **Step 4: backlog 갱신** — `docs/backlog.md`의 "cc-agora bots" 항목을 갱신: Plan 1·Plan 2 모두 **구현 완료**. 남은 후속은 plugin v2.2 / 기존 워커·echo_bot의 `msgtype` 주입(클라이언트 측, Plan 1·2 doc "범위 밖" 참조). 간결하게, backlog.md 스타일(한국어·terse) 유지.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_v4_bots.py docs/backlog.md
git commit -m "test: §8.8 integration — multi-bot fan-out, observer, bot_emit chain, no_route"
```

---

## Plan 2 완료 기준

- [ ] `pytest tests/ -v` 전체 통과 (회귀 0).
- [ ] 서버 부팅 정상 (schema 6종 로드 + BotRegistry 빈 상태).
- [ ] 봇이 `agora.register_bot`으로 등록·구독하고, broker가 `msgtype` 매칭으로 `dispatch`/`broadcast`를 구독 봇에 `subscribed` fan-out, observer에 `cc` fan-out.
- [ ] `target` 생략 dispatch가 schema-routed로 동작, 구독 봇 없으면 `no_route`.
- [ ] `agora.bot_emit`이 `in_reply_to`로 원 caller에 라우팅, 미지정 시 구독 봇에 fan-out.
- [ ] `agora.bots`/`agora.find`로 봇 발견, 봇은 `dispatch`/`broadcast` 호출 차단.

## 범위 밖 (후속)

- plugin v2.2 — `/cc-agora:agora-spawn-bot`, `agora_bot_sdk`, `bot.py.template` (별도 spec, §3.11·§8 item 9).
- 기존 cc-agora 워커 슬래시 스킬 + `examples/echo_bot`의 `msgtype` 주입 — Plan 1 "범위 밖" 참조. broker 배포 전 필요한 클라이언트 측 작업.
- spec §7 후속: schema versioning(BACKWARD-compatible additive evolution), competing-consumer `load_balance`, observer backpressure, streaming progress, schema 등록 RBAC, 봇 다운 감지.
