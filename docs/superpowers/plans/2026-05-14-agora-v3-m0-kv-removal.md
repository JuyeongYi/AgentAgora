# Agora v3 M0 — KV Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora의 KV 기능(JSON Schema 저장소)을 완전 제거하여 메시지 채널 단일 책임 서버로 전환.

**Architecture:** 1라운드 자유대화 실험·모든 워커 deep dive·정체성 결정 라운드에서 KV 사용 0회 확인. v3 메이저 변경. 외부 사용자 0명이라 backward compat 부담 없음. `schema.py`·`store.py` 통째 제거, `agora.set/get/append/delete/list` 5개 도구 제거, `_RESERVED_SCHEMA_NAMES`·`schemas.json` 의존 제거. `AsyncWriteQueue` 패턴은 후속 M1 plan에서 `persistence.py`로 이전되므로 본 M0에서는 stub 모듈만 만들거나 store.py와 함께 제거.

**Tech Stack:** Python 3.13, FastMCP, jsonschema (제거 대상), pytest, MCP Streamable HTTP.

**Reference spec:** `docs/superpowers/specs/2026-05-14-agora-coordination-v3-design.md` §1 (배경), §2 (목표/non-goals), §16 M0, §15.8 (KV 제거 테스트).

**PR 전략:** Inst2 권장에 따라 본 M0는 단독 PR. 머지 후 안정화 → M1 plan 시작. M0와 M1 동시 진행 시 server.py·envelope/persistence 모듈 머지 충돌 위험.

**예상 시간:** T+30~60분 (Inst8 추정).

---

## File Structure

| 파일 | 동작 | 책임 |
|---|---|---|
| `src/agent_agora/schema.py` | **삭제** | KV 스키마 검증, `_BUILTIN_SCHEMAS` |
| `src/agent_agora/store.py` | **삭제** | KV JSON 영속화, `AsyncWriteQueue` (M1에서 별 모듈로 재작성) |
| `src/agent_agora/server.py` | 수정 | KV 도구 5개 제거, `_RESERVED_SCHEMA_NAMES` 제거, `SchemaRegistry`/`AgoraStore` import 제거, `agora.list`의 KV 분기 제거 |
| `src/agent_agora/__main__.py` | 수정 | `schemas.json` 로드 제거, `SchemaRegistry.load(...)` 호출 제거, `AgoraStore` 초기화 제거 |
| `tests/` 디렉토리 | 수정 | KV 관련 테스트 파일·케이스 제거 + `test_v1_kv_tools_removed` 회귀 신규 + `test_legacy_schemas_json_present_warned_but_ignored` 회귀 신규 |
| `README.md` | 수정 | KV 섹션 제거, "공유 상태" 표현 정리, 정체성 한 줄을 메시지 채널 중심으로 |
| `.agentagora/schemas.json` (런타임) | 무시 | 있어도 startup warning 후 무시 |

---

## Task 1: 베이스라인 확보 — 현 테스트 통과 확인

**Files:**
- Reference only: `tests/`, `pytest.ini` or `pyproject.toml`

- [ ] **Step 1: 작업 디렉토리 확인**

```bash
cd C:\Users\Jooyo\AgoraTest\Inst1\AgentAgora
git status
```

Expected: `working tree clean` 또는 사용자가 의도한 변경만.

- [ ] **Step 2: 현 테스트 전수 실행**

```bash
pytest -v
```

Expected: 모든 테스트 PASS. 실패 있으면 본 plan 진행 전 fix.

- [ ] **Step 3: 베이스라인 commit 마킹 (optional, working tree clean이면 skip)**

```bash
git log -1 --oneline
```

Expected: 현 HEAD commit ID 기록 — 본 plan 진행 중 revert 기준점.

---

## Task 2: KV 관련 테스트 파일 식별

**Files:**
- Inspect: `tests/`

- [ ] **Step 1: KV 도구 사용 테스트 grep**

```bash
grep -rn "agora\.\(set\|get\|append\|delete\|list\)" tests/
grep -rn "SchemaRegistry\|AgoraStore" tests/
grep -rn "schemas\.json" tests/
```

Expected: 매칭된 파일 list. 일반적으로 `tests/test_server.py`, `tests/test_integration.py`, `tests/test_store.py` (있다면), `tests/test_schema.py` (있다면) 등.

- [ ] **Step 2: 매칭 파일 list 작성 (메모)**

작업 메모용. 다음 task에서 case-by-case 제거.

---

## Task 3: KV 관련 테스트 케이스 제거 (TDD 역방향 — 테스트 먼저)

**Files:**
- Modify: `tests/test_*.py` (Task 2에서 식별된 파일들)
- Delete: `tests/test_schema.py`, `tests/test_store.py` (있다면)

- [ ] **Step 1: KV 전용 테스트 파일 삭제**

```bash
# 있다면
rm tests/test_schema.py tests/test_store.py
```

Expected: 파일 없음.

- [ ] **Step 2: 혼합 테스트 파일에서 KV 케이스 제거**

`tests/test_server.py`·`tests/test_integration.py`의 `def test_*` 중 `agora.set/get/...`나 `SchemaRegistry`를 쓰는 함수 제거. 한 파일 안에 메시지 채널과 KV가 섞여 있으면 KV 부분만 잘라낸다.

남기는 import: `from agent_agora.dispatcher`, `from agent_agora.registry`, FastMCP 관련.
제거하는 import: `from agent_agora.schema import SchemaRegistry`, `from agent_agora.store import AgoraStore, AsyncWriteQueue`.

- [ ] **Step 3: pytest collect-only 확인**

```bash
pytest --collect-only
```

Expected: KV 관련 테스트가 list에서 사라짐. ImportError 없음(다음 step에서 검출).

- [ ] **Step 4: 잔존 KV 참조 확인**

```bash
grep -rn "SchemaRegistry\|AgoraStore\|schemas\.json\|agora\.\(set\|get\|append\|delete\)" tests/
```

Expected: 매칭 0건 (이상적). 일부 남았으면 Step 2로 돌아가 추가 제거.

- [ ] **Step 5: 테스트 통과 확인 (제거 후)**

```bash
pytest -v
```

Expected: 남은 테스트(메시지 채널) 전수 PASS. v1 KV 도구가 서버에는 아직 있으므로 import 안 됐어도 동작 OK.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test: remove KV-related test cases (v3 M0 phase)"
```

---

## Task 4: 신규 회귀 테스트 추가 — `test_v1_kv_tools_removed`

**Files:**
- Create: `tests/test_v3_kv_removal.py`

- [ ] **Step 1: 신규 테스트 파일 작성**

`tests/test_v3_kv_removal.py`:
```python
"""Regression tests for v3 KV removal (M0 phase)."""
import pytest
import asyncio
import json
import tempfile
from pathlib import Path


async def _list_tool_names(mcp):
    tools = await mcp.list_tools()
    return [t.name for t in tools]


@pytest.mark.asyncio
async def test_v1_kv_tools_removed(agora_app):
    """v3에서 agora.set/get/append/delete/list 도구가 등록되어 있지 않아야 함."""
    mcp, _ = agora_app
    names = await _list_tool_names(mcp)
    for removed in ("agora.set", "agora.get", "agora.append", "agora.delete"):
        assert removed not in names, f"Expected '{removed}' removed in v3, but still registered"
    # agora.list는 KV용으로만 의미가 있었으므로 v3에서 제거. (KV 외 다른 list 의미가 있다면 spec 갱신 필요)
    assert "agora.list" not in names, "agora.list (KV) should be removed in v3"


@pytest.mark.asyncio
async def test_legacy_schemas_json_present_warned_but_ignored(tmp_path, capsys):
    """기존 schemas.json이 있어도 v3 서버는 warning 출력 후 무시. 시작 실패하지 않음."""
    # Arrange — 가짜 schemas.json 생성
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    legacy_schema = agora_dir / "schemas.json"
    legacy_schema.write_text(json.dumps({"notes": {"type": "object"}}), encoding="utf-8")

    # Act — 서버 시작 (Application factory에서 schemas.json을 감지하면 warning만 출력)
    from agent_agora.__main__ import _build_app  # 신규 함수, M0 Task 6에서 추가
    app = _build_app(agora_dir=tmp_path, port=8421, no_tls=True)

    # Assert — 서버 객체 생성 성공
    assert app is not None
    captured = capsys.readouterr()
    assert "schemas.json" in captured.err or "schemas.json" in captured.out, \
        "Server must warn about legacy schemas.json on startup"
```

`conftest.py`에 `agora_app` fixture가 없다면 다음 추가:
```python
# tests/conftest.py에 추가 (있는 부분 있으면 skip)
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
async def agora_app(tmp_path):
    """Build a FastMCP app with empty registry/dispatcher for tool-existence tests."""
    from agent_agora.__main__ import _build_app
    app = _build_app(agora_dir=tmp_path, port=0, no_tls=True)
    yield app
```

- [ ] **Step 2: 테스트 실행 (실패 예상)**

```bash
pytest tests/test_v3_kv_removal.py -v
```

Expected: FAIL — `_build_app` 함수 부재 (Task 6에서 추가). 또는 KV 도구가 아직 등록되어 있어 첫 테스트 실패.

이 실패는 의도된 것 (TDD 역방향). 다음 Task에서 KV 제거 + `_build_app` 추가로 PASS 만든다.

- [ ] **Step 3: Commit (실패 테스트)**

```bash
git add tests/test_v3_kv_removal.py tests/conftest.py
git commit -m "test: add v3 KV removal regression tests (expected to fail until Task 5-7)"
```

---

## Task 5: `server.py`에서 KV 도구·예약명 제거

**Files:**
- Modify: `src/agent_agora/server.py` (L24~28, L93~144, L137~144 등)

- [ ] **Step 1: import 정리**

`src/agent_agora/server.py` 상단 import 블록에서 다음 제거:
```python
# 제거
from agent_agora.schema import SchemaRegistry
from agent_agora.store import AgoraStore, AsyncWriteQueue
```

함수 시그니처 `create_agora_app(agora_dir, store, registry, instance_registry, dispatcher, port)`에서 `store`, `registry` 인자 제거 → `create_agora_app(agora_dir, instance_registry, dispatcher, port)`.

함수 본문에서 `queue = AsyncWriteQueue(store)`, `start_time = time.time()`은 유지하되 `queue` 라인 제거.

- [ ] **Step 2: `_RESERVED_SCHEMA_NAMES` 상수 제거**

L24~28의 상수 블록 통째 삭제 (5줄):
```python
_RESERVED_SCHEMA_NAMES = frozenset({"instances", "commands", "results"})
```

- [ ] **Step 3: KV 도구 5개 제거**

다음 함수 통째 삭제 (각 ~10~15줄):
- `agora_set` (L93~102)
- `agora_get` (L104~111)
- `agora_append` (L113~122)
- `agora_delete` (L124~133)
- `agora_list` (L135~144)

`@mcp.tool(name="agora.info")` 다음 바로 `@mcp.tool(name="agora.register")` 또는 다음 메시지 채널 도구가 오게 정리.

- [ ] **Step 4: `agora.info` 도구의 schemas 노출 제거**

기존:
```python
@mcp.tool(name="agora.info")
async def agora_info() -> str:
    return json.dumps({
        "path": str(agora_dir),
        "port": port,
        "schemas": sorted(registry.names()),
        "uptime": int(time.time() - start_time),
    }, ensure_ascii=False)
```

변경:
```python
@mcp.tool(name="agora.info")
async def agora_info() -> str:
    """Return server metadata: data dir, port, uptime."""
    return json.dumps({
        "path": str(agora_dir),
        "port": port,
        "uptime": int(time.time() - start_time),
    }, ensure_ascii=False)
```

- [ ] **Step 5: return 값 정리**

함수 끝의 `return mcp, queue`를 `return mcp`로 변경 (queue 없으므로). 호출처(`__main__.py`)도 같이 갱신 — Task 6에서.

- [ ] **Step 6: 모듈 import 가능 확인**

```bash
python -c "from agent_agora.server import create_agora_app; print('OK')"
```

Expected: OK 출력. 단 `__main__.py`가 아직 옛 시그니처로 부르면 깨질 수 있음 — Task 6에서 fix.

---

## Task 6: `__main__.py`에서 SchemaRegistry/AgoraStore 의존 제거 + `_build_app` 헬퍼 추가

**Files:**
- Modify: `src/agent_agora/__main__.py`

- [ ] **Step 1: 현 `__main__.py` 읽기 (의존 구조 파악)**

```bash
cat src/agent_agora/__main__.py
```

(처음 작업 시) 식별: argparse 블록, `SchemaRegistry.load(agora_dir)` 호출, `AgoraStore(...)` 초기화, `create_agora_app(...)` 호출, uvicorn 실행.

- [ ] **Step 2: KV 의존 제거 + `_build_app` 헬퍼 추출**

다음과 같이 재작성 (실제 파일에 맞게 조정):
```python
# src/agent_agora/__main__.py
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import uvicorn

from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.server import create_agora_app


def _warn_legacy_schemas_json(agora_dir: Path) -> None:
    """Detect leftover v1 schemas.json and warn (it is ignored in v3)."""
    legacy = agora_dir / ".agentagora" / "schemas.json"
    if legacy.exists():
        print(
            f"[agora] WARNING: detected legacy v1 schemas.json at {legacy} — "
            f"v3 ignores it (KV removed). You may delete or rename this file.",
            file=sys.stderr,
        )


def _build_app(agora_dir: Path, port: int, no_tls: bool, default_wait_timeout_ms: int = 60000):
    """Construct the FastMCP app + supporting state. Used by both CLI and tests."""
    _warn_legacy_schemas_json(agora_dir)
    instance_registry = InstanceRegistry()
    dispatcher = Dispatcher(instance_registry, default_timeout_ms=default_wait_timeout_ms)
    mcp = create_agora_app(
        agora_dir=agora_dir,
        instance_registry=instance_registry,
        dispatcher=dispatcher,
        port=port,
    )
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-agora")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--dir", type=Path, default=Path("."))
    parser.add_argument("--no-tls", action="store_true")
    parser.add_argument("--default-wait-timeout-ms", type=int, default=60000)
    # (cert 관련 옵션은 기존 그대로 유지)
    args = parser.parse_args()

    mcp = _build_app(
        agora_dir=args.dir,
        port=args.port,
        no_tls=args.no_tls,
        default_wait_timeout_ms=args.default_wait_timeout_ms,
    )
    # uvicorn 실행 부분은 기존 코드 그대로 유지 (mcp.streamable_http_app() 등)
    # 본 plan에서는 핵심 흐름만 보여줌 — 실제 작업 시 기존 TLS·cert 로직 보존


if __name__ == "__main__":
    main()
```

주의: 기존 cert 디렉토리·TLS 옵션·uvicorn config는 plan에 단순화되어 있음. 실제 `__main__.py`의 그 부분은 그대로 두고 KV 로딩 라인만 제거.

- [ ] **Step 3: 잔존 KV import grep**

```bash
grep -rn "SchemaRegistry\|AgoraStore\|schemas\.json" src/agent_agora/
```

Expected: 0건. (단 `schemas.json`은 `_warn_legacy_schemas_json` 한 곳만 등장 — OK).

- [ ] **Step 4: 실행 가능 검증 — `--help`**

```bash
python -m agent_agora --help
```

Expected: argparse usage 출력. KV 관련 옵션이 없으면 OK.

- [ ] **Step 5: 실제 startup 한 번 (테스트 디렉토리)**

```bash
mkdir -p /tmp/agora_v3_smoke && python -m agent_agora --dir /tmp/agora_v3_smoke --port 8421 --no-tls &
sleep 2
curl -sS http://127.0.0.1:8421/mcp -o /dev/null -w "%{http_code}\n" || true
kill %1
```

Expected: HTTP 405 또는 404 (MCP는 POST). 서버가 죽지 않고 응답하는 것만 확인. (Windows에서는 PowerShell start/stop 사용)

PowerShell 버전:
```powershell
mkdir $env:TEMP\agora_v3_smoke -Force | Out-Null
$proc = Start-Process python -ArgumentList "-m","agent_agora","--dir",$env:TEMP\agora_v3_smoke,"--port","8421","--no-tls" -PassThru
Start-Sleep -Seconds 2
try { Invoke-WebRequest -Uri "http://127.0.0.1:8421/mcp" -Method Get -ErrorAction SilentlyContinue } catch {}
Stop-Process -Id $proc.Id -Force
```

---

## Task 7: `schema.py`·`store.py` 파일 삭제

**Files:**
- Delete: `src/agent_agora/schema.py`
- Delete: `src/agent_agora/store.py`

- [ ] **Step 1: 파일 삭제**

```bash
rm src/agent_agora/schema.py src/agent_agora/store.py
```

- [ ] **Step 2: 잔존 import 최종 확인**

```bash
grep -rn "from agent_agora.schema\|from agent_agora.store\|import schema\|import store" src/ tests/
```

Expected: 0건.

- [ ] **Step 3: 패키지 import 가능 확인**

```bash
python -c "import agent_agora; print('OK')"
```

Expected: OK.

- [ ] **Step 4: 전수 테스트 실행**

```bash
pytest -v
```

Expected: 모든 테스트 PASS. Task 4의 v3 회귀 테스트(`test_v1_kv_tools_removed`, `test_legacy_schemas_json_present_warned_but_ignored`)가 비로소 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/server.py src/agent_agora/__main__.py
git rm src/agent_agora/schema.py src/agent_agora/store.py
git commit -m "refactor: remove KV subsystem (schema.py, store.py, 5 tools) for v3 messaging-only identity

- Drop SchemaRegistry, AgoraStore, AsyncWriteQueue (v1 KV pattern)
- Drop agora.set/get/append/delete/list MCP tools
- Drop _RESERVED_SCHEMA_NAMES guard
- Drop schemas.json loading; v3 ignores it with warning
- Add v3 regression tests (test_v1_kv_tools_removed, test_legacy_schemas_json_present_warned_but_ignored)

Refs: spec docs/superpowers/specs/2026-05-14-agora-coordination-v3-design.md §16 M0
"
```

---

## Task 8: README의 KV 섹션 제거 + 정체성 한 줄 재작성 (최소 변경)

**Files:**
- Modify: `README.md`

> Note: README 전면 재작성은 M4 plan(별 plan)에서 처리. M0에서는 **사용자가 곧장 깨지지 않게** 최소 정리만.

- [ ] **Step 1: KV 관련 섹션 식별**

```bash
grep -n "agora\.set\|agora\.get\|agora\.append\|agora\.delete\|schemas\.json\|JSON Schema" README.md
```

매칭 라인 list 작성.

- [ ] **Step 2: 도입부 한 줄 정체성 갱신**

기존:
```markdown
# AgentAgora

여러 개의 자율 에이전트(예: 다중 Claude Code 인스턴스)가 **하나의 공유 상태
저장소 + 인스턴스 간 명령 채널**을 통해 협업할 수 있게 해주는 MCP 서버.
```

변경:
```markdown
# AgentAgora

여러 개의 자율 에이전트(예: 다중 Claude Code 인스턴스)가 **이름 있는 인스턴스로
서로를 발견하고 메시지를 주고받는** MCP 서버. v3에서 메시지 채널 단일 책임으로
재정의됨 (v1 KV 기능은 제거).
```

- [ ] **Step 3: KV CRUD 섹션 통째 제거**

`## MCP 도구 레퍼런스`의 다음 sub-section 제거:
- `### CRUD (사용자 스키마 전용)` — `agora.set/get/append/delete/list` 5개 도구 설명
- `### 1) 데이터 디렉터리 준비` 의 `schemas.json` 예시 단락 (Quick Start 섹션) — 메시지 채널만 쓸 때는 데이터 디렉토리 없이도 동작 가능하지만, 본 plan에서는 기존 디렉토리 컨셉 유지하므로 schemas.json 예시 단락만 삭제하고 디렉토리 생성 부분은 남김.

`예약 스키마(instances / commands / results)는 모든 쓰기가 거부된다.` 같은 라인도 제거.

- [ ] **Step 4: history note 한 단락 (Inst6 W3)**

README 맨 아래 (라이선스 직전) 또는 도입부 아래에 한 단락:
```markdown
## v1 → v3 변경

v1은 "공유 상태 저장소(JSON Schema KV) + 명령 채널" 양립이었으나, 실측 사용 결과
KV 기능 호출이 0회로 확인되어 v3에서 제거됨. KV 같은 요구가 필요해지면 별 패키지로
도입 예정 (현재 계획 없음).
```

- [ ] **Step 5: markdown 렌더 확인 (시각 검증)**

```bash
# Windows에서 vscode 또는 다른 마크다운 뷰어로 열기
code README.md
```

또는 grep으로 잔존 KV 참조 확인:
```bash
grep -n "schemas\.json\|agora\.\(set\|get\|append\|delete\)" README.md
```

Expected: history 단락의 한 줄(있다면)만 매칭, 도구 설명은 0건.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: prune KV references from README (v3 M0)

- Replace v1 identity (KV + channel) with v3 messaging-only
- Drop CRUD tool reference section
- Drop schemas.json quick-start example
- Add v1 → v3 history note

Full README rewrite deferred to M4 plan.
"
```

---

## Task 9: 통합 smoke test — v3 M0 완료 검증

**Files:**
- Inspect only

- [ ] **Step 1: 전수 테스트 통과 확인**

```bash
pytest -v
```

Expected: 모든 테스트 PASS. KV 관련 테스트는 모두 제거되어 list에서 사라짐. v3 회귀 테스트 2개 PASS.

- [ ] **Step 2: 실제 서버 startup smoke**

PowerShell:
```powershell
$tmp = "$env:TEMP\agora_v3_smoke_final"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$proc = Start-Process python -ArgumentList "-m","agent_agora","--dir",$tmp,"--port","8421","--no-tls" -PassThru -RedirectStandardError "$tmp\err.log"
Start-Sleep -Seconds 2

# 헬스 체크 — MCP는 POST만 받으므로 GET은 405 또는 404 정상
try { Invoke-WebRequest -Uri "http://127.0.0.1:8421/mcp" -Method Get -TimeoutSec 3 } catch { Write-Host "HTTP check (expected error): $($_.Exception.Message)" }

Stop-Process -Id $proc.Id -Force
Get-Content "$tmp\err.log"
```

Expected: 서버 startup 성공, schemas.json 없으면 warning 출력 없음(legacy가 없으므로). 종료 정상.

- [ ] **Step 3: legacy schemas.json 시나리오 smoke**

```powershell
$tmp = "$env:TEMP\agora_v3_legacy_smoke"
New-Item -ItemType Directory -Path "$tmp\.agentagora" -Force | Out-Null
'{"notes":{"type":"object"}}' | Out-File "$tmp\.agentagora\schemas.json" -Encoding utf8

$proc = Start-Process python -ArgumentList "-m","agent_agora","--dir",$tmp,"--port","8422","--no-tls" -PassThru -RedirectStandardError "$tmp\err.log"
Start-Sleep -Seconds 2
Stop-Process -Id $proc.Id -Force
Get-Content "$tmp\err.log"
```

Expected: err.log에 `WARNING: detected legacy v1 schemas.json` 한 줄 포함.

- [ ] **Step 4: KV 도구 부재 확인 (수동 MCP request — optional)**

가능하면 MCP 클라이언트로 `tools/list` 호출해 `agora.set` 등 5개 도구가 없음을 시각 확인. 또는 Task 4의 회귀 테스트 PASS로 갈음.

- [ ] **Step 5: Commit (smoke 통과만 — 코드 변경 없으면 skip)**

코드 변경 없으면 commit 안 함. 변경 있으면 fix commit.

---

## Task 10: PR 준비

**Files:**
- N/A

- [ ] **Step 1: 변경 요약 작성 (git log 기반)**

```bash
git log --oneline main..HEAD
```

Expected: 본 plan의 commit 5~6개 list.

- [ ] **Step 2: PR description 초안 — Inst2 권장 분리 형식**

```markdown
## v3 M0: KV Removal

본 PR은 v3 spec의 M0 단계만 처리. v3 메시지 채널 변경(M1+)은 후속 PR에서.

### 변경 사항
- `schema.py`, `store.py` 통째 제거
- `agora.set/get/append/delete/list` 5개 MCP 도구 제거
- `_RESERVED_SCHEMA_NAMES` 가드 제거
- `__main__.py`의 `schemas.json` 로딩 제거, legacy 파일 감지 시 warning 출력
- README의 KV 섹션 제거, v1 → v3 history note 추가
- 회귀 테스트 2건 신규: `test_v1_kv_tools_removed`, `test_legacy_schemas_json_present_warned_but_ignored`

### 검증
- `pytest -v` 전수 통과
- `schemas.json` 부재 startup smoke 통과
- `schemas.json` legacy 감지 warning smoke 통과

### Refs
- Spec: `docs/superpowers/specs/2026-05-14-agora-coordination-v3-design.md` §16 M0
- 정체성 결정 라운드: 워커 6/7 옵션 C 추천 + 사용자 확정
- 후속 PR: v3 M1+ 메시지 채널 (별 plan `2026-05-14-agora-v3-messaging.md`)
```

- [ ] **Step 3: 사용자에게 PR 생성 의사 확인 후 진행**

본 plan은 PR 생성·머지는 자동화하지 않는다. 사용자가 명시 요청 시 별 단계로 처리.

---

## 완료 조건

- [ ] 모든 Task 1~10 체크박스 완료
- [ ] `pytest -v` 전수 PASS
- [ ] `grep -rn "SchemaRegistry\|AgoraStore\|schemas\.json"` 결과: `_warn_legacy_schemas_json` 한 곳만 매칭, 나머지 0건
- [ ] M0 단독 PR 준비 완료 (사용자 머지 의사 결정 대기)
- [ ] 후속: M1 plan(`2026-05-14-agora-v3-messaging.md`) 시작 가능
