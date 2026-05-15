# cc-agora Bots — Plan 1: 스키마 강제 기반 (서버 사이드)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 서버의 모든 메시지가 `msgtype`을 필수로 가지고 runtime-mutable JSON Schema 카탈로그로 검증되도록 만든다.

**Architecture:** 새 `SchemaRegistry`(스레드 안전, validator 컴파일 캐시)를 추가하고 `_build_app` → `create_agora_app` → `Dispatcher`로 배선한다. 배선은 *동작 변경 없는 리팩터*로 먼저 끝낸 뒤, 별도 task에서 `Dispatcher.dispatch`/`broadcast`에 payload 검증을 켠다. schema 카탈로그는 `.agentagora/schemas.jsonl`에서 로드하고 SQLite에 영속한다.

**Tech Stack:** Python 3.13, FastMCP, jsonschema(Draft202012Validator — 이미 의존성), SQLite(WAL), pytest + pytest-asyncio.

**범위:** 본 plan은 spec [`2026-05-15-cc-agora-bots-design.md`](../specs/2026-05-15-cc-agora-bots-design.md) v4의 **2개 분할 plan 중 1번**이다.

- **Plan 1 (본 문서)** — Schema Registry + msgtype 강제. 봇 없이도 "모든 메시지 schema 검증"이 완성되는 독립 제품 증분.
- **Plan 2** — `2026-05-16-cc-agora-bots-2-routing.md`. BotRegistry, broker fan-out 라우팅, `register_bot`/`bot_emit` 등. Plan 1 위에 얹는다.

plugin v2.2 / `agora_bot_sdk`(§3.11, §8 item 9)는 양쪽 plan 모두에서 제외 — 별도 spec.

**왜 2개로 나눴나:** Dispatcher 생성자에 registry를 주입하는 변경은 cross-cutting이라 모든 생성 지점이 같은 커밋에서 바뀌어야 한다. Plan 1에서 `schema_registry` 배선을, Plan 2에서 `bot_registry` 배선을 각각 한 task로 격리해, 매 task가 green 테스트로 끝나게 한다.

---

## Spec 정합 보정 (Plan 1 해당분)

1. **`default_schemas.jsonl` 묶음 = schema 6개 전부.** 결정 21은 bare-minimum을 4개로 적었으나 결정 25가 결정 B를 확정해 `bot_reply`/`bot_error`가 포함된다. §5.2·§8 트리대로 묶음은 `default, worker_freeform, bot_reply, bot_error, closing, ack` **6개**다.
2. **`SchemaRegistry.register` / `agora.register_schema`는 `kind`·`purpose`를 받는다.** §3.2 핵심 함수·§3.9 시그니처는 결정 23(모든 schema는 `kind`+`purpose` 메타) 이전 표현이다. 결정 23이 우선한다.

---

## File Structure

### 신규 파일
- `src/agent_agora/errors.py` — agora 에러 코드 + 한국어 메시지(§4.5 schema 관련분). `AgoraError`.
- `src/agent_agora/schemas.py` — `SchemaRegistry`, `SchemaEntry`, jsonl 로더.
- `src/agent_agora/default_schemas.jsonl` — repo 동봉 기본 schema 6종(패키지 포함).
- `tests/_helpers.py` — 테스트 공용 헬퍼(payload 빌더, registry 팩토리).
- `tests/test_v4_schemas.py` — SchemaRegistry + jsonl 로더 단위 테스트.
- `tests/test_v4_schema_enforcement.py` — Plan 1 통합 테스트.

### 수정 파일
- `src/agent_agora/persistence.py` — SQLite `schemas` 테이블, save/restore 메서드.
- `src/agent_agora/dispatcher.py` — `schema_registry` 주입, `_validate_payload`, `close_thread` payload.
- `src/agent_agora/server.py` — `create_agora_app` 시그니처, `register_schema`/`schemas`/`schemas_list` 도구.
- `src/agent_agora/__main__.py` — `_build_app`에 SchemaRegistry 배선 + 시작 시 schema 로드.
- `pyproject.toml` — 패키지 데이터(`default_schemas.jsonl`).
- `tests/conftest.py` — `schema_registry` fixture + `tests/` sys.path.
- `tests/test_v3_dispatcher.py` · `test_v3_recovery.py` · `test_v3_ttl_gc.py` · `test_integration.py` · `test_main.py` — Dispatcher 생성 시그니처 + msgtype-bearing payload 마이그레이션.

### 책임 경계
- `errors.py` — 에러 코드 ↔ 한국어 메시지 단일 소스.
- `schemas.py` — schema body 저장·불변성·검증기 컴파일. 라우팅 모름.
- `dispatcher.py` — `schema_registry`를 *소비*만 한다.
- `server.py` — MCP 도구 표면.

---

## Task 1: errors.py — 에러 코드 + 한국어 메시지

**Files:**
- Create: `src/agent_agora/errors.py`
- Create: `tests/test_v4_schemas.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_schemas.py`:

```python
import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES


def test_agora_error_carries_code_and_korean_message():
    e = AgoraError("payload_missing_msgtype")
    assert e.code == "payload_missing_msgtype"
    assert str(e) == "[agora] payload에 msgtype이 없습니다. 모든 메시지는 msgtype이 필수입니다."


def test_agora_error_formats_detail():
    e = AgoraError("unknown_msgtype", msgtype="foo")
    assert str(e) == "[agora] msgtype 'foo'는 registry에 없습니다."


def test_plan1_schema_codes_present():
    expected = {
        "payload_missing_msgtype", "unknown_msgtype", "schema_violation",
        "schema_immutable", "schema_missing_msgtype",
    }
    assert expected <= set(ERROR_MESSAGES)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.errors'`

- [ ] **Step 3: errors.py 구현** — `src/agent_agora/errors.py`:

```python
"""v4 agora error codes + Korean messages (spec §4.5)."""
from __future__ import annotations


# code -> str.format template. {placeholders} filled by AgoraError kwargs.
# Plan 1: schema 관련 코드. 봇 관련 코드는 Plan 2에서 추가된다.
ERROR_MESSAGES: dict[str, str] = {
    "payload_missing_msgtype": "[agora] payload에 msgtype이 없습니다. 모든 메시지는 msgtype이 필수입니다.",
    "unknown_msgtype": "[agora] msgtype '{msgtype}'는 registry에 없습니다.",
    "schema_violation": "[agora] schema_violation: {detail}",
    "schema_immutable": "[agora] schema '{name}'는 다른 body로 이미 등록됨.",
    "schema_missing_msgtype": "[agora] schema '{name}' body에 msgtype property가 없습니다. (결정 20)",
}


class AgoraError(ValueError):
    """agora 도메인 에러. .code로 에러 코드를, str()로 한국어 메시지를 노출한다.

    ValueError 서브클래스 — server.py의 기존 ``except (NotRegisteredError, ValueError)``
    경로가 그대로 잡아 ``{"error": str(e)}``로 직렬화한다.
    """

    def __init__(self, code: str, **fmt: object) -> None:
        self.code = code
        template = ERROR_MESSAGES.get(code, "[agora] {code}")
        try:
            message = template.format(code=code, **fmt)
        except (KeyError, IndexError):
            message = template
        super().__init__(message)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/errors.py tests/test_v4_schemas.py
git commit -m "feat: agora error codes + Korean messages (schema subset, §4.5)"
```

---

## Task 2: SchemaRegistry 코어 (register / get / validator)

**Files:**
- Create: `src/agent_agora/schemas.py`
- Test: `tests/test_v4_schemas.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_schemas.py`에 추가:

```python
from agent_agora.schemas import SchemaRegistry, SchemaEntry

_WF_BODY = {
    "type": "object",
    "required": ["msgtype", "message"],
    "properties": {
        "msgtype": {"type": "string", "const": "wf"},
        "message": {"type": "string"},
    },
    "additionalProperties": True,
}
_NO_MSGTYPE_BODY = {
    "type": "object",
    "required": ["x"],
    "properties": {"x": {"type": "string"}},
    "additionalProperties": False,
}


def test_register_returns_entry_with_kind_and_purpose():
    reg = SchemaRegistry()
    entry = reg.register("wf", _WF_BODY, kind="conversation", purpose="자유 통신")
    assert isinstance(entry, SchemaEntry)
    assert entry.name == "wf" and entry.kind == "conversation"
    assert entry.purpose == "자유 통신"
    assert reg.get("wf").body == _WF_BODY


def test_register_rejects_body_without_msgtype_property():
    reg = SchemaRegistry()
    with pytest.raises(AgoraError) as ei:
        reg.register("bad", _NO_MSGTYPE_BODY, kind="conversation", purpose="p")
    assert ei.value.code == "schema_missing_msgtype"


def test_register_same_body_is_idempotent():
    reg = SchemaRegistry()
    a = reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    b = reg.register("wf", dict(_WF_BODY), kind="conversation", purpose="p")
    assert a == b


def test_register_different_body_raises_schema_immutable():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    other = dict(_WF_BODY, required=["msgtype"])
    with pytest.raises(AgoraError) as ei:
        reg.register("wf", other, kind="conversation", purpose="p")
    assert ei.value.code == "schema_immutable"


def test_validator_validates_and_caches():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    v1 = reg.validator("wf")
    v2 = reg.validator("wf")
    assert v1 is v2  # cached, not recompiled
    assert list(v1.iter_errors({"msgtype": "wf", "message": "hi"})) == []
    assert list(v1.iter_errors({"msgtype": "wf"})) != []  # missing required


def test_get_and_validator_return_none_for_unknown():
    reg = SchemaRegistry()
    assert reg.get("nope") is None
    assert reg.validator("nope") is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v -k "register or validator or get_and"`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.schemas'`

- [ ] **Step 3: schemas.py 구현** — `src/agent_agora/schemas.py`:

```python
"""v4 Schema Registry — runtime-mutable JSON Schema catalog (bots design)."""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import Draft202012Validator

from agent_agora.errors import AgoraError

SchemaKind = Literal["conversation", "bot-task"]


@dataclass(frozen=True)
class SchemaEntry:
    name: str
    body: dict[str, Any]
    kind: SchemaKind
    purpose: str
    registered_at: str
    registered_by: str | None = None


def _has_msgtype_property(body: Any) -> bool:
    props = body.get("properties") if isinstance(body, dict) else None
    return isinstance(props, dict) and "msgtype" in props


class SchemaRegistry:
    """name -> SchemaEntry. Thread-safe. Compiled validators cached per schema."""

    def __init__(self) -> None:
        self._entries: dict[str, SchemaEntry] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        body: dict[str, Any],
        kind: SchemaKind,
        purpose: str,
        registered_by: str | None = None,
    ) -> SchemaEntry:
        """결정 20: body에 msgtype property 필수. 동일 이름 + 다른 body → schema_immutable.
        동일 이름 + 동일 body → idempotent (기존 entry 반환)."""
        if not _has_msgtype_property(body):
            raise AgoraError("schema_missing_msgtype", name=name)
        with self._lock:
            existing = self._entries.get(name)
            if existing is not None:
                if existing.body == body:
                    return existing
                raise AgoraError("schema_immutable", name=name)
            entry = SchemaEntry(
                name=name, body=body, kind=kind, purpose=purpose,
                registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                registered_by=registered_by,
            )
            self._entries[name] = entry
            self._validators[name] = Draft202012Validator(body)
            return entry

    def get(self, name: str) -> SchemaEntry | None:
        with self._lock:
            return self._entries.get(name)

    def validator(self, name: str) -> Draft202012Validator | None:
        with self._lock:
            return self._validators.get(name)
```

> `Draft202012Validator(body)`는 format checker 없이 생성한다 — `format: "date-time"`은 annotation-only(advisory). LLM 워커의 느슨한 ts 표기를 깨지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v -k "register or validator or get_and"`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/schemas.py tests/test_v4_schemas.py
git commit -m "feat: SchemaRegistry core — register/get/validator with msgtype + immutability"
```

---

## Task 3: SchemaRegistry — list_meta / list_all

**Files:**
- Modify: `src/agent_agora/schemas.py`
- Test: `tests/test_v4_schemas.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_schemas.py`에 추가:

```python
def test_list_meta_exposes_kind_and_purpose_no_body():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="자유 통신")
    meta = reg.list_meta()
    assert len(meta) == 1
    assert meta[0]["name"] == "wf"
    assert meta[0]["kind"] == "conversation"
    assert meta[0]["purpose"] == "자유 통신"
    assert "body" not in meta[0]


def test_list_all_returns_entries_with_body():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    entries = reg.list_all()
    assert len(entries) == 1 and entries[0].body == _WF_BODY
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v -k "list_meta or list_all"`
Expected: FAIL — `AttributeError: 'SchemaRegistry' object has no attribute 'list_meta'`

- [ ] **Step 3: 구현** — `schemas.py`의 `SchemaRegistry`에 메서드 추가:

```python
    def list_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": e.name, "kind": e.kind, "purpose": e.purpose,
                    "registered_at": e.registered_at, "registered_by": e.registered_by,
                }
                for e in self._entries.values()
            ]

    def list_all(self) -> list[SchemaEntry]:
        with self._lock:
            return list(self._entries.values())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/schemas.py tests/test_v4_schemas.py
git commit -m "feat: SchemaRegistry list_meta/list_all"
```

---

## Task 4: default_schemas.jsonl + jsonl 로더

**Files:**
- Create: `src/agent_agora/default_schemas.jsonl`
- Modify: `src/agent_agora/schemas.py`, `pyproject.toml`
- Test: `tests/test_v4_schemas.py` (추가)

- [ ] **Step 1: default_schemas.jsonl 작성**

`src/agent_agora/default_schemas.jsonl` — 정확히 6줄, 각 줄이 line-delimited JSON. spec §3.2 body 그대로:

```jsonl
{"name":"default","kind":"conversation","purpose":"로그 엔트리 표준 형식. 구조화 로그 메시지에 사용.","body":{"type":"object","required":["msgtype","timestamp","level","msg","category"],"properties":{"msgtype":{"type":"string","const":"default"},"timestamp":{"type":"string","format":"date-time"},"level":{"type":"string","enum":["debug","info","warn","error"]},"msg":{"type":"string"},"category":{"type":"string"}},"additionalProperties":false}}
{"name":"worker_freeform","kind":"conversation","purpose":"LLM 워커 간 자연어 free-form 통신. message 필드가 자유 텍스트.","body":{"type":"object","required":["msgtype","type","from","ts","message"],"properties":{"msgtype":{"type":"string","const":"worker_freeform"},"type":{"type":"string","enum":["task","reply","closing","ack"]},"from":{"type":"string"},"ts":{"type":"string","format":"date-time"},"message":{"type":"string"}},"additionalProperties":true}}
{"name":"bot_reply","kind":"bot-task","purpose":"봇 처리 결과 표준. bot_emit 정상 결과 payload.","body":{"type":"object","required":["msgtype","from","ts","result"],"properties":{"msgtype":{"type":"string","const":"bot_reply"},"from":{"type":"string"},"ts":{"type":"string","format":"date-time"},"result":{}},"additionalProperties":false}}
{"name":"bot_error","kind":"bot-task","purpose":"봇 handler 실패 표준. bot_emit 에러 payload.","body":{"type":"object","required":["msgtype","from","ts","error_code","error_message"],"properties":{"msgtype":{"type":"string","const":"bot_error"},"from":{"type":"string"},"ts":{"type":"string","format":"date-time"},"error_code":{"type":"string"},"error_message":{"type":"string"},"traceback":{"type":"string"}},"additionalProperties":false}}
{"name":"closing","kind":"conversation","purpose":"대화 종결 통지.","body":{"type":"object","required":["msgtype","from","ts"],"properties":{"msgtype":{"type":"string","const":"closing"},"from":{"type":"string"},"ts":{"type":"string","format":"date-time"},"reason":{"type":"string"}},"additionalProperties":false}}
{"name":"ack","kind":"conversation","purpose":"forward 통지.","body":{"type":"object","required":["msgtype","from","ts","ack_for"],"properties":{"msgtype":{"type":"string","const":"ack"},"from":{"type":"string"},"ts":{"type":"string","format":"date-time"},"ack_for":{"type":"string"}},"additionalProperties":false}}
```

- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_v4_schemas.py`에 추가:

```python
from agent_agora.schemas import (
    parse_schema_lines, ensure_schemas_file, load_schemas_into,
    BUNDLED_DEFAULT_SCHEMAS,
)


def test_bundled_default_schemas_file_exists_and_has_six():
    assert BUNDLED_DEFAULT_SCHEMAS.is_file()
    lines = [l for l in BUNDLED_DEFAULT_SCHEMAS.read_text("utf-8").splitlines() if l.strip()]
    assert len(lines) == 6


def test_parse_schema_lines_yields_name_kind_purpose_body():
    parsed = parse_schema_lines(BUNDLED_DEFAULT_SCHEMAS.read_text("utf-8"))
    names = {p["name"] for p in parsed}
    assert names == {"default", "worker_freeform", "bot_reply", "bot_error", "closing", "ack"}
    for p in parsed:
        assert "properties" in p["body"] and "msgtype" in p["body"]["properties"]


def test_ensure_schemas_file_copies_bundle_when_absent(tmp_path):
    target = tmp_path / "schemas.jsonl"
    assert not target.exists()
    ensure_schemas_file(target)
    assert target.is_file()
    assert len([l for l in target.read_text("utf-8").splitlines() if l.strip()]) == 6


def test_ensure_schemas_file_keeps_existing(tmp_path):
    target = tmp_path / "schemas.jsonl"
    target.write_text("", encoding="utf-8")
    ensure_schemas_file(target)
    assert target.read_text("utf-8") == ""  # not overwritten


def test_load_schemas_into_registers_all_six():
    reg = SchemaRegistry()
    count = load_schemas_into(reg, BUNDLED_DEFAULT_SCHEMAS)
    assert count == 6
    assert reg.get("worker_freeform").kind == "conversation"
    assert reg.get("bot_reply").kind == "bot-task"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v -k "bundled or parse_schema or ensure_schemas or load_schemas"`
Expected: FAIL — `ImportError: cannot import name 'parse_schema_lines'`

- [ ] **Step 4: 로더 구현** — `schemas.py` 상단 import에 추가하고 파일 끝에 함수 추가:

```python
import json
import shutil
from pathlib import Path

BUNDLED_DEFAULT_SCHEMAS = Path(__file__).with_name("default_schemas.jsonl")


def parse_schema_lines(text: str) -> list[dict[str, Any]]:
    """jsonl 텍스트를 {name, kind, purpose, body} dict 리스트로 파싱. 빈 줄 무시."""
    out: list[dict[str, Any]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"schemas.jsonl line {lineno}: invalid JSON ({e})") from e
        for key in ("name", "kind", "purpose", "body"):
            if key not in obj:
                raise ValueError(f"schemas.jsonl line {lineno}: missing '{key}'")
        out.append(obj)
    return out


def ensure_schemas_file(target: Path) -> Path:
    """target이 없으면 repo 동봉 default_schemas.jsonl을 복사한다 (결정 21).
    이미 있으면 손대지 않는다 (사용자 편집 보존)."""
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUNDLED_DEFAULT_SCHEMAS, target)
    return target


def load_schemas_into(registry: SchemaRegistry, path: Path) -> int:
    """path의 jsonl을 registry에 등록한다. 등록된 schema 개수를 반환."""
    parsed = parse_schema_lines(path.read_text("utf-8"))
    for p in parsed:
        registry.register(p["name"], p["body"], kind=p["kind"], purpose=p["purpose"])
    return len(parsed)
```

- [ ] **Step 5: pyproject.toml에 패키지 데이터 포함** — `[tool.setuptools.packages.find]` 섹션 아래에 추가:

```toml
[tool.setuptools.package-data]
agent_agora = ["default_schemas.jsonl"]
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_schemas.py -v`
Expected: PASS (전체)

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/default_schemas.jsonl src/agent_agora/schemas.py pyproject.toml tests/test_v4_schemas.py
git commit -m "feat: default_schemas.jsonl bundle + jsonl loader (결정 21)"
```

---

## Task 5: SQLite migration — schemas 테이블

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v3_persistence.py`에 추가:

```python
def test_migrate_creates_schemas_table(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "schemas" in names


def test_schemas_table_has_kind_and_purpose_columns(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    cols = [r[1] for r in p.conn.execute("PRAGMA table_info(schemas)").fetchall()]
    assert {"name", "body", "kind", "purpose", "registered_at", "registered_by"} <= set(cols)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v3_persistence.py -v -k "schemas_table or creates_schemas"`
Expected: FAIL — `schemas` 테이블 없음

- [ ] **Step 3: persistence.py 수정** — `_SCHEMA_V1` 문자열 끝(`schema_version` 테이블 정의 뒤)에 추가:

```python
CREATE TABLE IF NOT EXISTS schemas (
  name TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('conversation','bot-task')),
  purpose TEXT NOT NULL DEFAULT '',
  registered_at TEXT NOT NULL,
  registered_by TEXT
);
```

`migrate()` 본문은 변경 불필요 — `executescript(_SCHEMA_V1)`이 `CREATE TABLE IF NOT EXISTS`로 신규 테이블을 만든다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v3_persistence.py -v`
Expected: PASS (전체 — 기존 테스트 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat: SQLite schemas table"
```

---

## Task 6: Persistence — schema save·restore 메서드

**Files:**
- Modify: `src/agent_agora/persistence.py`
- Test: `tests/test_v3_persistence.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v3_persistence.py`에 추가:

```python
def test_save_and_restore_schemas(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    body = {"type": "object", "properties": {"msgtype": {"type": "string"}}}
    p.save_schema("foo", body, kind="bot-task", purpose="테스트", registered_by="bot_x")
    rows = p.restore_schemas()
    assert len(rows) == 1
    assert rows[0]["name"] == "foo"
    assert rows[0]["kind"] == "bot-task"
    assert rows[0]["body"] == body
    assert rows[0]["purpose"] == "테스트"
    assert rows[0]["registered_by"] == "bot_x"


def test_save_schema_idempotent_on_same_name(tmp_path):
    db = tmp_path / "agora.db"
    p = Persistence(db)
    p.migrate()
    body = {"properties": {"msgtype": {}}}
    p.save_schema("foo", body, kind="bot-task", purpose="p")
    p.save_schema("foo", body, kind="bot-task", purpose="p")  # no PK violation
    assert len(p.restore_schemas()) == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v3_persistence.py -v -k "save_and_restore_schemas or save_schema_idem"`
Expected: FAIL — `AttributeError: 'Persistence' object has no attribute 'save_schema'`

- [ ] **Step 3: 구현** — `persistence.py` 상단 import에 `import json` 추가(없으면). `Persistence` 클래스에 메서드 추가(`lookup_conversation_for` 아래):

```python
    def save_schema(
        self, name: str, body: dict, kind: str, purpose: str,
        registered_by: str | None = None,
    ) -> None:
        """schema를 동기 영속화한다. 동일 이름 재저장은 무시 (registry가 불변성 강제)."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO schemas (name, body, kind, purpose, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, json.dumps(body, ensure_ascii=False), kind, purpose, now, registered_by),
        )

    def restore_schemas(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT name, body, kind, purpose, registered_at, registered_by FROM schemas"
        ).fetchall()
        return [
            {"name": r[0], "body": json.loads(r[1]), "kind": r[2],
             "purpose": r[3], "registered_at": r[4], "registered_by": r[5]}
            for r in rows
        ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v3_persistence.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/persistence.py tests/test_v3_persistence.py
git commit -m "feat: persist + restore schemas"
```

---

## Task 7: tests/_helpers.py + conftest fixture

> 이후 task가 `Dispatcher`를 `schema_registry`와 함께 생성하려면 테스트 인프라가 먼저 있어야 한다. 이 task는 production 코드를 건드리지 않으므로 기존 테스트에 영향이 없다(green).

**Files:**
- Create: `tests/_helpers.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: tests/_helpers.py 생성**

`_`로 시작하는 모듈명이라 pytest가 테스트로 수집하지 않는다. `tests/_helpers.py`:

```python
"""v4 테스트 공용 헬퍼 — payload 빌더 + registry 팩토리."""
from agent_agora.schemas import SchemaRegistry, load_schemas_into, BUNDLED_DEFAULT_SCHEMAS

# 기존 v3 테스트가 임의 dict payload를 보내던 것을 흡수하는 느슨한 테스트 schema.
TEST_ANY_BODY = {
    "type": "object",
    "required": ["msgtype"],
    "properties": {"msgtype": {"type": "string", "const": "test_any"}},
    "additionalProperties": True,
}


def make_schema_registry() -> SchemaRegistry:
    """기본 schema 6종 + test_any가 등록된 SchemaRegistry."""
    reg = SchemaRegistry()
    load_schemas_into(reg, BUNDLED_DEFAULT_SCHEMAS)
    reg.register("test_any", TEST_ANY_BODY, kind="conversation",
                 purpose="테스트 전용 느슨한 schema")
    return reg


def tany(**fields) -> dict:
    """test_any payload 헬퍼. 기존 임의 dict payload 자리에 쓴다."""
    return {"msgtype": "test_any", **fields}


def wf(message: str = "hi", type_: str = "task", **extra) -> dict:
    """worker_freeform payload 헬퍼."""
    return {
        "msgtype": "worker_freeform", "type": type_,
        "from": "tester", "ts": "2026-01-01T00:00:00Z",
        "message": message, **extra,
    }
```

- [ ] **Step 2: conftest.py 수정**

`tests/conftest.py`의 `_PLUGIN_SCRIPTS` 블록 *다음*에 추가 — `tests/` 자체를 `sys.path`에 넣어 `from _helpers import ...`가 top-level import로 동작하게 한다(`tests/__init__.py`가 있어도 디렉토리를 직접 sys.path에 넣으면 `_helpers`를 top-level 모듈로 import 가능):

```python
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
```

`conftest.py` 끝에 fixture 추가(`_helpers` import는 `_TESTS_DIR`가 sys.path에 들어간 *뒤*여야 하므로 끝부분):

```python
from _helpers import make_schema_registry  # noqa: E402


@pytest.fixture
def schema_registry():
    return make_schema_registry()
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체 — 회귀 0. 헬퍼는 아직 아무도 안 쓴다.)

- [ ] **Step 4: 커밋**

```bash
git add tests/_helpers.py tests/conftest.py
git commit -m "test: add v4 test helpers (_helpers.py) + schema_registry fixture"
```

---

## Task 8: SchemaRegistry 배선 — 동작 변경 없는 리팩터

> **이 task가 ordering 핵심이다.** `Dispatcher` 생성자에 `schema_registry`를 주입하고 `_build_app`/`create_agora_app`/모든 테스트 fixture를 같은 커밋에서 갱신한다. `Dispatcher`는 `schema_registry`를 *저장만* 하고 아직 쓰지 않는다 — 동작은 완전히 동일하다. 시작 시 schema 카탈로그를 로드한다.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`, `src/agent_agora/server.py`, `src/agent_agora/__main__.py`
- Modify: `tests/test_v3_dispatcher.py`, `test_v3_recovery.py`, `test_v3_ttl_gc.py`, `test_integration.py`
- Test: `tests/test_main.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_main.py`에 추가:

```python
def test_build_app_wires_schema_registry(tmp_path):
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp = _build_app(agora_dir=agora_dir, port=0)
    schema_registry = mcp._agora_schema_registry
    # 기본 schema 6종이 시작 시 로드됨
    assert schema_registry.get("worker_freeform") is not None
    assert schema_registry.get("bot_reply") is not None
    # .agentagora/schemas.jsonl이 동봉본에서 복사됨
    assert (agora_dir / "schemas.jsonl").is_file()
    # SQLite에도 영속됨
    assert len(mcp._agora_persistence.restore_schemas()) >= 6
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_main.py -v -k wires_schema`
Expected: FAIL — `AttributeError: ... _agora_schema_registry`

- [ ] **Step 3: Dispatcher 생성자 수정** — `dispatcher.py` import에 추가:

```python
from agent_agora.schemas import SchemaRegistry
```

`Dispatcher.__init__` 시그니처를 교체(`write_queue` 다음 keyword-only로 `schema_registry` 필수):

```python
    def __init__(
        self,
        registry: InstanceRegistry,
        persistence: Persistence,
        write_queue: AsyncWriteQueue,
        *,
        schema_registry: SchemaRegistry,
        default_timeout_ms: int = 60000,
        max_inbox_depth: int = 100,
        close_timeout_ms: int = 300_000,
        dead_session_timeout_ms: int = 1_800_000,
        gc_retention_days: int = 90,
    ) -> None:
```

`__init__` 본문, 기존 state 초기화부에 추가:

```python
        self._schema_registry = schema_registry
```

(이 task에서 `_schema_registry`는 저장만 한다. Task 10에서 검증에 쓴다.)

- [ ] **Step 4: create_agora_app 시그니처 수정** — `server.py`:

import 추가:

```python
from agent_agora.schemas import SchemaRegistry
from agent_agora.persistence import Persistence
```

`create_agora_app` 시그니처에 `schema_registry`·`persistence` 추가(Task 11의 schema 도구가 쓴다 — 지금 미리 배선):

```python
def create_agora_app(
    agora_dir: Path,
    instance_registry: InstanceRegistry,
    schema_registry: SchemaRegistry,
    persistence: Persistence,
    dispatcher: Dispatcher,
    port: int,
) -> FastMCP:
```

본문은 변경하지 않는다 — 두 인자는 Task 11까지 미사용(Python은 미사용 인자를 허용).

- [ ] **Step 5: __main__.py `_build_app` 수정** — import 블록 + 객체 생성을 교체:

```python
    from agent_agora.dispatcher import Dispatcher
    from agent_agora.persistence import AsyncWriteQueue, Persistence
    from agent_agora.registry import InstanceRegistry
    from agent_agora.schemas import SchemaRegistry, ensure_schemas_file, load_schemas_into
    from agent_agora.server import create_agora_app

    _warn_legacy_schemas_json(agora_dir)

    instance_registry = InstanceRegistry()
    persistence = Persistence(db_path or (agora_dir / "agora.db"))
    persistence.migrate()

    # Schema 로드: (1) SQLite의 등록 schema 복원, (2) .agentagora/schemas.jsonl 로드.
    # 둘 다 idempotent — 동일 body는 무시. 충돌 시 startup 경고 후 SQLite본 유지.
    schema_registry = SchemaRegistry()
    for row in persistence.restore_schemas():
        try:
            schema_registry.register(
                row["name"], row["body"], kind=row["kind"],
                purpose=row["purpose"], registered_by=row["registered_by"])
        except Exception as e:  # noqa: BLE001 — startup 복원은 best-effort
            print(f"[agora] WARNING: schema '{row['name']}' 복원 실패: {e}", file=sys.stderr)
    schemas_file = ensure_schemas_file(agora_dir / "schemas.jsonl")
    try:
        load_schemas_into(schema_registry, schemas_file)
    except Exception as e:  # noqa: BLE001
        print(f"[agora] WARNING: {schemas_file} 로드 중 일부 schema 충돌: {e}", file=sys.stderr)
    # jsonl로 새로 등록된 기본 schema를 SQLite에도 영속 (idempotent)
    for entry in schema_registry.list_all():
        persistence.save_schema(entry.name, entry.body, kind=entry.kind,
                                purpose=entry.purpose, registered_by=entry.registered_by)

    write_queue = AsyncWriteQueue(persistence)
    dispatcher = Dispatcher(
        registry=instance_registry,
        persistence=persistence,
        write_queue=write_queue,
        schema_registry=schema_registry,
        default_timeout_ms=default_wait_timeout_ms,
        max_inbox_depth=max_inbox_depth if max_inbox_depth > 0 else 10**9,
        close_timeout_ms=close_timeout_ms,
        dead_session_timeout_ms=dead_session_timeout_ms,
        gc_retention_days=gc_retention_days,
    )
    mcp = create_agora_app(
        agora_dir=agora_dir,
        instance_registry=instance_registry,
        schema_registry=schema_registry,
        persistence=persistence,
        dispatcher=dispatcher,
        port=port,
    )
    mcp._agora_instance_registry = instance_registry  # type: ignore[attr-defined]
    mcp._agora_schema_registry = schema_registry  # type: ignore[attr-defined]
    mcp._agora_dispatcher = dispatcher  # type: ignore[attr-defined]
    mcp._agora_persistence = persistence  # type: ignore[attr-defined]
    mcp._agora_write_queue = write_queue  # type: ignore[attr-defined]
    return mcp
```

- [ ] **Step 6: 기존 Dispatcher 생성 fixture 수정**

`grep -rn "Dispatcher(" tests/`로 모든 생성 지점을 찾는다(`test_v3_dispatcher.py`, `test_v3_recovery.py`, `test_v3_ttl_gc.py`, `test_integration.py`). 각 fixture에 `schema_registry` 인자를 추가한다. 예 — `test_v3_dispatcher.py:18`:

```python
# before
dispatcher = Dispatcher(registry, persistence, queue, default_timeout_ms=500)
# after — 파일 상단에 import 추가:
#   from _helpers import make_schema_registry
dispatcher = Dispatcher(registry, persistence, queue,
                        schema_registry=make_schema_registry(),
                        default_timeout_ms=500)
```

`create_agora_app(`를 직접 호출하는 테스트가 있으면(`grep -rn "create_agora_app(" tests/`) `schema_registry`·`persistence` 인자도 추가한다.

- [ ] **Step 7: 전체 테스트 + 부팅 스모크**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체 — 동작 변경이 없으므로 회귀 0)

Run: `python -m agent_agora --port 8765 --no-tls --no-timeout` (수동, 5초 후 Ctrl+C)
Expected: 정상 부팅, `.agentagora/schemas.jsonl` 생성됨.

- [ ] **Step 8: 커밋**

```bash
git add src/agent_agora/dispatcher.py src/agent_agora/server.py src/agent_agora/__main__.py tests/
git commit -m "refactor: wire SchemaRegistry through build_app/create_agora_app/Dispatcher (no behavior change)"
```

---

## Task 9: 기존 v3 테스트 payload를 msgtype-bearing으로 마이그레이션

> Task 10에서 검증이 켜지기 *전에* 기존 테스트 payload에 `msgtype`을 심는다. `Dispatcher`는 아직 검증하지 않으므로 — payload에 키 하나가 추가될 뿐 동작은 동일하다(green).

**Files:**
- Modify: `tests/test_v3_dispatcher.py`, `test_v3_recovery.py`, `test_v3_ttl_gc.py`, `test_integration.py`

- [ ] **Step 1: 마이그레이션 패턴**

각 테스트 파일 상단에 `from _helpers import tany, wf` 추가. `payload={...}`(임의 dict)를 `payload=tany(...)`로, payload 내용을 검사하는 대응 assert도 함께 교체한다. 예 — `test_v3_dispatcher.py`의 `test_dispatch_wait_unchanged_when_new_optional_fields_omitted`:

```python
# before
res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload={"m": "hi"})
...
assert drained[0]["payload"] == {"m": "hi"}
# after
res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(m="hi"))
...
assert drained[0]["payload"] == tany(m="hi")
```

- [ ] **Step 2: 전 테스트 파일 일괄 교체**

`grep -rn "payload=" tests/test_v3_dispatcher.py tests/test_v3_recovery.py tests/test_v3_ttl_gc.py tests/test_integration.py`로 모든 `payload=` 호출을 찾는다. 각 매치를 `tany(...)`로 교체(payload를 검사하지 않는 대부분). worker 간 자연어 대화 의미가 강한 곳은 `wf(...)`. payload를 검사하는 assert가 있으면 assert도 같이 교체.

> `close_thread`가 내부 dispatch하는 payload(`dispatcher.py`의 `{"type":"closing",...}`)는 Task 10에서 production 코드로 함께 고친다 — 이 task에서 손대지 않는다.

- [ ] **Step 3: 전체 테스트 통과 확인**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체 — 마이그레이션이 동작을 바꾸지 않았음)

- [ ] **Step 4: 커밋**

```bash
git add tests/
git commit -m "test: migrate v3 test payloads to msgtype-bearing form"
```

---

## Task 10: Dispatcher — payload msgtype 검증 (강제 ON)

> 이제 검증을 켠다. `dispatch`/`broadcast`의 payload는 `msgtype`이 필수이고 registry schema를 통과해야 한다(결정 18). `close_thread` 내부 dispatch payload도 `closing` schema에 맞춘다.

**Files:**
- Modify: `src/agent_agora/dispatcher.py`
- Test: `tests/test_v4_schema_enforcement.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_schema_enforcement.py`:

```python
import pytest
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.errors import AgoraError
from _helpers import make_schema_registry, tany, wf


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                default_timeout_ms=500)
        yield registry, dispatcher


@pytest.mark.asyncio
async def test_dispatch_rejects_payload_without_msgtype(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload={"m": "hi"})
    assert ei.value.code == "payload_missing_msgtype"


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_msgtype(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="Inst2",
                                  payload={"msgtype": "nonexistent"})
    assert ei.value.code == "unknown_msgtype"


@pytest.mark.asyncio
async def test_dispatch_rejects_schema_violation(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.dispatch(source="Inst1", target="Inst2",
                                  payload={"msgtype": "worker_freeform"})
    assert ei.value.code == "schema_violation"


@pytest.mark.asyncio
async def test_dispatch_accepts_valid_worker_freeform(setup):
    _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=wf("안녕"))
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    assert drained[0]["payload"]["message"] == "안녕"


@pytest.mark.asyncio
async def test_broadcast_rejects_payload_without_msgtype(setup):
    _, dispatcher = setup
    with pytest.raises(AgoraError) as ei:
        await dispatcher.broadcast(source="Inst1", payload={"m": "hi"})
    assert ei.value.code == "payload_missing_msgtype"


@pytest.mark.asyncio
async def test_close_thread_uses_closing_schema(setup):
    _, dispatcher = setup
    conv = "conv-close-x"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1),
                              conversation_id=conv)
    res = await dispatcher.close_thread("Inst1", conv, reason="끝")
    assert res["conversation_id"] == conv
    drained = await dispatcher.wait("Inst2", timeout_ms=200)
    closing_msgs = [d for d in drained if d["payload"].get("msgtype") == "closing"]
    assert len(closing_msgs) == 1
    assert closing_msgs[0]["payload"]["reason"] == "끝"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_schema_enforcement.py -v`
Expected: FAIL — payload가 그대로 통과(검증 미구현) 또는 `close_thread` payload가 `closing` schema 위반

- [ ] **Step 3: `_validate_payload` 헬퍼 추가** — `dispatcher.py` import에 추가:

```python
from agent_agora.errors import AgoraError
```

`Dispatcher`에 메서드 추가(`dispatch` 위):

```python
    def _validate_payload(self, payload: Any) -> str:
        """payload의 msgtype을 검증하고 schema validate. msgtype 문자열을 반환.
        실패 시 AgoraError(payload_missing_msgtype | unknown_msgtype | schema_violation)."""
        if not isinstance(payload, dict) or "msgtype" not in payload:
            raise AgoraError("payload_missing_msgtype")
        msgtype = payload["msgtype"]
        validator = self._schema_registry.validator(msgtype)
        if validator is None:
            raise AgoraError("unknown_msgtype", msgtype=msgtype)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
        if errors:
            detail = "; ".join(e.message for e in errors[:3])
            raise AgoraError("schema_violation", detail=detail)
        return msgtype
```

- [ ] **Step 4: dispatch / broadcast에 검증 호출 추가**

`dispatch` 본문의 `payload_bytes = validate_payload_size(payload)` 줄 *바로 위*에:

```python
        self._validate_payload(payload)
```

`broadcast` 본문도 동일하게 `payload_bytes = validate_payload_size(payload)` 위에:

```python
        self._validate_payload(payload)
```

- [ ] **Step 5: close_thread 내부 dispatch payload를 closing schema로 교체**

`close_thread`(dispatcher.py)의 내부 `dispatch` 호출 payload를 교체:

```python
                await self.dispatch(
                    source=caller, target=o,
                    payload={
                        "msgtype": "closing", "from": caller,
                        "ts": _now_iso(),
                        **({"reason": reason} if reason else {}),
                    },
                    conversation_id=conv_id, closing=True,
                )
```

`closing` schema는 `required: [msgtype, from, ts]`, `reason` optional, `additionalProperties: false`.

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체 — Task 9에서 v3 payload가 이미 msgtype-bearing)

- [ ] **Step 7: 커밋**

```bash
git add src/agent_agora/dispatcher.py tests/test_v4_schema_enforcement.py
git commit -m "feat: enforce payload msgtype validation in dispatch/broadcast (결정 18)"
```

---

## Task 11: server.py — register_schema / schemas / schemas_list 도구

**Files:**
- Modify: `src/agent_agora/server.py`
- Test: `tests/test_v4_schema_enforcement.py` (추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_v4_schema_enforcement.py`에 추가:

```python
import json
from agent_agora.server import create_agora_app


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
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(instance_registry, persistence, queue,
                                schema_registry=schema_registry, default_timeout_ms=300)
        mcp = create_agora_app(
            agora_dir=tmp_path, instance_registry=instance_registry,
            schema_registry=schema_registry, persistence=persistence,
            dispatcher=dispatcher, port=0)
        yield mcp, instance_registry, schema_registry


@pytest.mark.asyncio
async def test_register_schema_and_schemas_list(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        name="deploy_run", kind="bot-task", purpose="배포 실행",
        body={"type": "object", "required": ["msgtype"],
              "properties": {"msgtype": {"const": "deploy_run"}}}))
    assert res["status"] == "ok"
    meta = json.loads(await _tool(mcp, "agora.schemas_list")())["schemas"]
    names = {m["name"]: m for m in meta}
    assert names["deploy_run"]["kind"] == "bot-task"
    assert names["deploy_run"]["purpose"] == "배포 실행"


@pytest.mark.asyncio
async def test_register_schema_missing_msgtype_rejected(app):
    mcp, *_ = app
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        name="bad", kind="bot-task", purpose="p",
        body={"type": "object", "properties": {"x": {"type": "string"}}}))
    assert "msgtype property가 없습니다" in res["error"]


@pytest.mark.asyncio
async def test_register_schema_immutable(app):
    mcp, *_ = app
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"const": "t"}}}
    await _tool(mcp, "agora.register_schema")(name="t", kind="bot-task", purpose="v1", body=body)
    res = json.loads(await _tool(mcp, "agora.register_schema")(
        name="t", kind="bot-task", purpose="v2",
        body=dict(body, required=["msgtype", "x"])))
    assert "이미 등록됨" in res["error"]


@pytest.mark.asyncio
async def test_schemas_returns_full_body(app):
    mcp, *_ = app
    full = json.loads(await _tool(mcp, "agora.schemas")())["schemas"]
    wf = next(s for s in full if s["name"] == "worker_freeform")
    assert "body" in wf and "properties" in wf["body"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_v4_schema_enforcement.py -v -k "register_schema or schemas_"`
Expected: FAIL — `agora.register_schema` 도구 없음

- [ ] **Step 3: server.py에 도구 추가** — import에 `from agent_agora.errors import AgoraError` 추가. `agora.info` 도구 다음에 추가:

```python
    @mcp.tool(name="agora.register_schema")
    async def agora_register_schema(
        name: str,
        body: dict,
        kind: Literal["conversation", "bot-task"],
        purpose: str,
    ) -> str:
        """Register a schema. Immutable — 동일 이름 다른 body는 거부.
        body에 msgtype property 필수 (결정 20)."""
        try:
            schema_registry.register(name, body, kind=kind, purpose=purpose)
            persistence.save_schema(name, body, kind=kind, purpose=purpose)
        except AgoraError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "ok", "name": name, "kind": kind})

    @mcp.tool(name="agora.schemas")
    async def agora_schemas() -> str:
        """Full schema catalog — name, kind, purpose, body."""
        return json.dumps({"schemas": [
            {"name": e.name, "kind": e.kind, "purpose": e.purpose, "body": e.body}
            for e in schema_registry.list_all()
        ]}, ensure_ascii=False)

    @mcp.tool(name="agora.schemas_list")
    async def agora_schemas_list() -> str:
        """Schema metadata only — name, kind, purpose (body 제외)."""
        return json.dumps({"schemas": schema_registry.list_meta()}, ensure_ascii=False)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_schema_enforcement.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 회귀 확인**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체)

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/server.py tests/test_v4_schema_enforcement.py
git commit -m "feat: agora.register_schema / schemas / schemas_list tools"
```

---

## Task 12: Plan 1 통합 테스트 + backlog 갱신

**Files:**
- Modify: `tests/test_v4_schema_enforcement.py` (추가)
- Modify: `docs/backlog.md`

- [ ] **Step 1: 통합 테스트 작성** — `tests/test_v4_schema_enforcement.py`에 추가:

```python
@pytest.mark.asyncio
async def test_all_six_default_schemas_have_msgtype_property(app):
    """default 포함 기본 제공 schema 6종 모두 msgtype property를 가진다 (결정 20)."""
    _, _, schema_reg = app
    for name in ("default", "worker_freeform", "bot_reply", "bot_error", "closing", "ack"):
        entry = schema_reg.get(name)
        assert entry is not None, name
        assert "msgtype" in entry.body["properties"], name


@pytest.mark.asyncio
async def test_worker_freeform_regression(app):
    """v3 워커 payload({msgtype:worker_freeform, type, from, ts, message, +보조필드})가
    worker_freeform schema를 통과한다 (§9.1)."""
    mcp, instance_registry, _ = app
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    res = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y",
        payload={"msgtype": "worker_freeform", "type": "reply", "from": "worker_x",
                 "ts": "2026-01-01T00:00:00Z", "message": "자유 텍스트",
                 "in_reply_to": "abc", "subject": "보조필드"}))
    assert res["status"] == "ok"


@pytest.mark.asyncio
async def test_dispatch_msgtype_required_and_unknown_rejected(app):
    mcp, instance_registry, _ = app
    instance_registry.register("ws1", "worker_x")
    instance_registry.register("ws2", "worker_y")
    r1 = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y", payload={"no": "msgtype"}))
    assert "msgtype이 없습니다" in r1["error"]
    r2 = json.loads(await _tool(mcp, "agora.dispatch")(
        FakeCtx("ws1"), target="worker_y", payload={"msgtype": "ghost"}))
    assert "registry에 없습니다" in r2["error"]


@pytest.mark.asyncio
async def test_schema_persists_across_restart(tmp_path):
    """register_schema한 도메인 schema가 서버 재시작(=_build_app 재호출) 후에도 살아있다."""
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp1 = _build_app(agora_dir=agora_dir, port=0)
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"const": "domain_x"}}}
    # save_schema는 동기 쓰기(autocommit)라 flush 불필요
    mcp1._agora_persistence.save_schema("domain_x", body, kind="bot-task", purpose="p")
    # 재시작 — _build_app 재호출이 SQLite에서 schema를 복원해야 한다
    mcp2 = _build_app(agora_dir=agora_dir, port=0)
    assert mcp2._agora_schema_registry.get("domain_x") is not None
```

- [ ] **Step 2: 통합 테스트 통과 확인**

Run: `python -m pytest tests/test_v4_schema_enforcement.py -v`
Expected: PASS (전체)

- [ ] **Step 3: 전체 테스트 + 부팅 스모크**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체, 회귀 0)

Run: `python -m agent_agora --port 8765 --no-tls --no-timeout` (수동, Ctrl+C)
Expected: 정상 부팅.

- [ ] **Step 4: backlog 갱신** — `docs/backlog.md`의 "cc-agora bots" 항목을 갱신: Plan 1(스키마 강제) 완료, Plan 2(봇 라우팅 — `2026-05-16-cc-agora-bots-2-routing.md`)가 다음 작업임을 명시.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_v4_schema_enforcement.py docs/backlog.md
git commit -m "test: Plan 1 integration — msgtype enforcement, worker_freeform regression, schema persistence"
```

---

## Plan 1 완료 기준

- [ ] `python -m pytest tests/ -v` 전체 통과 (회귀 0).
- [ ] 서버 부팅 시 `.agentagora/schemas.jsonl` 생성, 기본 schema 6종 로드, 에러 없음.
- [ ] 모든 `agora.dispatch`/`agora.broadcast`가 payload `msgtype`을 강제하고 schema로 검증.
- [ ] `agora.register_schema`/`schemas`/`schemas_list`로 카탈로그 조회·확장 가능, 등록 schema가 재시작 후 유지.

## Plan 2 (다음 plan)

`2026-05-16-cc-agora-bots-2-routing.md` — BotRegistry + broker fan-out 라우팅. Plan 2가 Plan 1 위에 추가하는 것:

- `errors.py` — 봇 에러 코드(`no_route`, `unhandled_schema`, `bot_emit_not_a_bot`, `description_required`, `subscribe_required` 등).
- SQLite `bot_subscriptions` 테이블 + `messages.delivered_as` CHECK에 `'subscribed'`.
- `BotRegistry` + `BotInfo` — 봇 전용 네임스페이스 + subscribe schema 역인덱스.
- `Dispatcher`에 `bot_registry` 주입(cross-cutting 배선 — Plan 2의 한 task) + 봇 fan-out(`subscribed`/`cc`) + `target` 생략 dispatch + `bot_emit`.
- `agora.register_bot` / `agora.bot_emit` / `agora.bots` 도구 + `agora.find` 워커·봇 통합.
- §8.8 통합 테스트.

**Plan 2의 full TDD plan은 Plan 1 실행·검토 완료 후 실제 코드 상태 기준으로 작성한다** — Plan 1 진행 중 API가 미세 조정되면 Plan 2가 그 위에 정확히 얹히도록.

## 범위 밖 (양쪽 plan 공통 후속)

> **breaking change 경고.** Plan 1은 `msgtype`을 *모든* 메시지 송신자에 강제한다. 서버 사이드(본 plan)는 완결됐으나, `msgtype` 없이 dispatch하던 *기존 클라이언트는 전부 `payload_missing_msgtype`로 깨진다*. 따라서 Plan 1은 **서버 사이드 증분**으로서 완료지 — plugin/예제 사용자에게 배포 가능한 상태가 아니다. 아래 클라이언트 측 후속이 끝나야 deploy-ready가 된다.

- **기존 cc-agora 워커 슬래시 스킬** — `plugin/cc-agora/scripts/payload.py`의 `make_payload`가 `msgtype`을 넣지 않는다. `invoke`/`broadcast`/`agora-close` 등 워커 슬래시가 전부 `payload_missing_msgtype`로 깨진다. `msgtype: "worker_freeform"` 주입이 필요한 별도 plugin 작업(§5.3).
- **`examples/echo_bot/`** — `bot.py`가 `msgtype` 없는 payload를 dispatch하므로 Plan 1 서버에 대고 돌리면 깨진다. 모듈 docstring의 "v3 서버 도구만으로 동작한다"도 stale. echo_bot은 Plan 2에서 정식 schema-subscriber 봇으로 재작성될 예정 — 그때 함께 정리한다(지금 고치면 throwaway).
- plugin v2.2 — `/cc-agora:agora-spawn-bot`, `agora_bot_sdk`, `bot.py.template` (별도 spec, §3.11·§8 item 9).
- spec §7 후속: schema versioning, competing-consumer `load_balance`, observer backpressure, streaming progress, schema RBAC, 봇 다운 감지.
