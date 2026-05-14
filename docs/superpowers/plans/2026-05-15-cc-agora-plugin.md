# cc-agora Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 운영 보조 Claude Code 플러그인 `cc-agora` 구현 — `/agora-spawn` 한 줄 워커 셋업 + 5개 통신 슬래시 + role-policy 명시 상수 파일.

**Architecture:** Python core(`scripts/role_policy.py`, `scripts/spawn.py`) + Markdown 자산(`commands/`, `templates/`) 분리. Python은 pytest로 TDD, markdown 자산은 형식·내용 검증 테스트. `plugin/cc-agora/`는 AgentAgora monorepo 안에서 독립 단위로 자체 `tests/` 보유.

**Tech Stack:** Python 3.13 (stdlib only), pytest, jsonschema (이미 의존), Claude Code 플러그인 컨벤션(`commands/*.md` frontmatter + body).

**Reference spec:** `docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md`.

**예상 시간:** T+4~6시간 sequential.

---

## File Structure

| 파일 | 동작 | 책임 |
|---|---|---|
| `plugin/cc-agora/package.json` | 신규 | 플러그인 메타(이름·버전·main) |
| `plugin/cc-agora/README.md` | 신규 | 사용 가이드(슬래시 5개 + spawn) |
| `plugin/cc-agora/config/roles.json` | 신규 | role → `{hook, preset}` single source of truth |
| `plugin/cc-agora/scripts/__init__.py` | 신규 | Python 패키지 마커 |
| `plugin/cc-agora/scripts/role_policy.py` | 신규 | roles.json 로더, 미정의 role 경고 |
| `plugin/cc-agora/scripts/spawn.py` | 신규 | 디렉토리·4파일 생성 + CLI 진입점 |
| `plugin/cc-agora/templates/CLAUDE.md.template` | 신규 | preset 본문 + description 헤더 합성 |
| `plugin/cc-agora/templates/mcp.json.template` | 신규 | `.mcp.json` 자리표시자 |
| `plugin/cc-agora/templates/settings.local.json.template` | 신규 | `stop-auto-wait` 정책의 Stop hook |
| `plugin/cc-agora/templates/presets/orchestrator.md` | 신규 | orchestrator 페르소나 |
| `plugin/cc-agora/templates/presets/coder.md` | 신규 | coder 페르소나 + 공통 단락 |
| `plugin/cc-agora/templates/presets/reviewer.md` | 신규 | reviewer 페르소나 + 공통 단락 |
| `plugin/cc-agora/templates/presets/tester.md` | 신규 | tester 페르소나 + 공통 단락 |
| `plugin/cc-agora/templates/presets/writer.md` | 신규 | writer 페르소나 + 공통 단락 |
| `plugin/cc-agora/templates/presets/planner.md` | 신규 | planner 페르소나 + 공통 단락 |
| `plugin/cc-agora/templates/presets/general.md` | 신규 | general 페르소나 + 공통 단락 |
| `plugin/cc-agora/commands/agora-spawn.md` | 신규 | `/agora-spawn` slash 정의 (scripts/spawn.py 호출) |
| `plugin/cc-agora/commands/invoke.md` | 신규 | `/invoke` thin wrapper |
| `plugin/cc-agora/commands/broadcast.md` | 신규 | `/broadcast` thin wrapper |
| `plugin/cc-agora/commands/agora-wait.md` | 신규 | `/agora-wait` thin wrapper |
| `plugin/cc-agora/commands/agora-unwait.md` | 신규 | `/agora-unwait` (settings.local.json 백업·hooks 제거) |
| `plugin/cc-agora/commands/agora-target.md` | 신규 | `/agora-target` (LLM 매칭 + /invoke prefill chaining) |
| `plugin/cc-agora/tests/__init__.py` | 신규 | |
| `plugin/cc-agora/tests/conftest.py` | 신규 | sys.path 추가, tmp dir fixture |
| `plugin/cc-agora/tests/test_role_policy.py` | 신규 | role_policy 단위 |
| `plugin/cc-agora/tests/test_spawn.py` | 신규 | spawn 단위·통합 |
| `plugin/cc-agora/tests/test_templates.py` | 신규 | 템플릿·preset 형식 검증 |
| `plugin/cc-agora/tests/test_commands.py` | 신규 | commands/*.md 형식 검증 |
| `pyproject.toml` | 수정 | `testpaths`에 `plugin/cc-agora/tests` 추가 |

---

## Task 1: 패키지 스켈레톤 + package.json + pyproject testpaths 확장

**Files:**
- Create: `plugin/cc-agora/package.json`
- Create: `plugin/cc-agora/README.md` (스텁만)
- Modify: `pyproject.toml`

- [ ] **Step 1: 디렉토리 + 빈 자식 생성**

```bash
mkdir -p plugin/cc-agora/{commands,config,scripts,templates/presets,tests}
```

- [ ] **Step 2: `plugin/cc-agora/package.json` 작성**

```json
{
  "name": "cc-agora",
  "version": "0.1.0",
  "description": "Claude Code plugin to automate AgentAgora operator workflow",
  "type": "module"
}
```

- [ ] **Step 3: `plugin/cc-agora/README.md` 스텁**

```markdown
# cc-agora

Claude Code plugin for AgentAgora operator workflow. See [design spec](../../docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md).

(Detailed usage guide added in final task.)
```

- [ ] **Step 4: `pyproject.toml` testpaths 확장**

기존:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

수정:
```toml
[tool.pytest.ini_options]
testpaths = ["tests", "plugin/cc-agora/tests"]
asyncio_mode = "auto"
```

- [ ] **Step 5: pytest 수집 확인 (실패하지 않게 빈 tests 디렉토리 처리)**

`plugin/cc-agora/tests/__init__.py` 빈 파일 작성.

Run: `pytest --collect-only -q`
Expected: 기존 테스트 collect, 새 디렉토리는 0 tests collected (에러 없음).

- [ ] **Step 6: Commit**

```bash
git add plugin/cc-agora/package.json plugin/cc-agora/README.md plugin/cc-agora/tests/__init__.py pyproject.toml
git commit -m "feat(cc-agora): package skeleton + pyproject testpaths"
```

---

## Task 2: 테스트 conftest — sys.path 조작, tmp dir fixture

**Files:**
- Create: `plugin/cc-agora/tests/conftest.py`

- [ ] **Step 1: conftest.py 작성**

```python
"""Test fixtures for cc-agora plugin tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

# scripts/ 를 import path 에 추가하여 role_policy, spawn 모듈 직접 import 가능
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def plugin_root() -> Path:
    """cc-agora 플러그인 루트 디렉토리."""
    return PLUGIN_ROOT


@pytest.fixture
def tmp_spawn_dir(tmp_path: Path) -> Path:
    """spawn 출력 디렉토리로 쓸 임시 디렉토리."""
    out = tmp_path / "spawn_out"
    out.mkdir()
    return out
```

- [ ] **Step 2: conftest 자체 sanity 확인 (trivial pytest 실행)**

`plugin/cc-agora/tests/test_smoke.py` 임시 작성 (다음 task에서 삭제):
```python
def test_smoke():
    assert True
```

Run: `pytest plugin/cc-agora/tests/test_smoke.py -v`
Expected: PASS

삭제: `rm plugin/cc-agora/tests/test_smoke.py`

- [ ] **Step 3: Commit**

```bash
git add plugin/cc-agora/tests/conftest.py
git commit -m "test(cc-agora): conftest with sys.path injection and tmp_spawn_dir"
```

---

## Task 3: `config/roles.json` + 형식 검증 테스트

**Files:**
- Create: `plugin/cc-agora/config/roles.json`
- Create: `plugin/cc-agora/tests/test_templates.py` (이 task에서 첫 추가)

- [ ] **Step 1: 실패 테스트 작성**

`plugin/cc-agora/tests/test_templates.py`:
```python
"""Asset format validation tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


ROLES_PATH = Path(__file__).resolve().parent.parent / "config" / "roles.json"

VALID_HOOK_POLICIES = {"none", "stop-auto-wait"}
REQUIRED_ROLES = {
    "orchestrator", "coder", "reviewer", "tester",
    "writer", "planner", "general",
}


def test_roles_json_exists():
    assert ROLES_PATH.exists(), f"roles.json missing at {ROLES_PATH}"


def test_roles_json_has_all_required_roles():
    data = json.loads(ROLES_PATH.read_text(encoding="utf-8"))
    assert set(data.keys()) >= REQUIRED_ROLES, (
        f"missing roles: {REQUIRED_ROLES - set(data.keys())}"
    )


def test_roles_json_entries_have_hook_and_preset():
    data = json.loads(ROLES_PATH.read_text(encoding="utf-8"))
    for role, entry in data.items():
        assert "hook" in entry, f"{role}: missing 'hook'"
        assert "preset" in entry, f"{role}: missing 'preset'"


def test_roles_json_hook_values_in_enum():
    data = json.loads(ROLES_PATH.read_text(encoding="utf-8"))
    for role, entry in data.items():
        assert entry["hook"] in VALID_HOOK_POLICIES, (
            f"{role}: invalid hook value {entry['hook']!r}"
        )


def test_orchestrator_has_no_hook():
    data = json.loads(ROLES_PATH.read_text(encoding="utf-8"))
    assert data["orchestrator"]["hook"] == "none"


def test_workers_have_stop_auto_wait_hook():
    data = json.loads(ROLES_PATH.read_text(encoding="utf-8"))
    workers = REQUIRED_ROLES - {"orchestrator"}
    for role in workers:
        assert data[role]["hook"] == "stop-auto-wait", (
            f"{role} should have stop-auto-wait hook"
        )
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_templates.py -v`
Expected: FAIL with `roles.json missing`

- [ ] **Step 3: `config/roles.json` 작성**

```json
{
  "orchestrator": { "hook": "none",           "preset": "orchestrator" },
  "coder":        { "hook": "stop-auto-wait", "preset": "coder" },
  "reviewer":     { "hook": "stop-auto-wait", "preset": "reviewer" },
  "tester":       { "hook": "stop-auto-wait", "preset": "tester" },
  "writer":       { "hook": "stop-auto-wait", "preset": "writer" },
  "planner":      { "hook": "stop-auto-wait", "preset": "planner" },
  "general":      { "hook": "stop-auto-wait", "preset": "general" }
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_templates.py -v`
Expected: 6개 PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora/config/roles.json plugin/cc-agora/tests/test_templates.py
git commit -m "feat(cc-agora): roles.json single source of truth with validation tests"
```

---

## Task 4: `scripts/role_policy.py` — 로더 + 미정의 role 경고

**Files:**
- Create: `plugin/cc-agora/scripts/__init__.py`
- Create: `plugin/cc-agora/scripts/role_policy.py`
- Create: `plugin/cc-agora/tests/test_role_policy.py`

- [ ] **Step 1: 실패 테스트 작성**

`plugin/cc-agora/tests/test_role_policy.py`:
```python
"""Unit tests for role_policy module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_load_default_returns_required_roles():
    from role_policy import load_default
    data = load_default()
    assert "orchestrator" in data
    assert "coder" in data
    assert data["orchestrator"]["hook"] == "none"
    assert data["coder"]["hook"] == "stop-auto-wait"


def test_load_from_path_reads_custom_file(tmp_path: Path):
    from role_policy import load_from_path
    custom = tmp_path / "roles.json"
    custom.write_text(
        json.dumps({"custom-role": {"hook": "none", "preset": "general"}}),
        encoding="utf-8",
    )
    data = load_from_path(custom)
    assert data == {"custom-role": {"hook": "none", "preset": "general"}}


def test_resolve_known_role_returns_entry():
    from role_policy import resolve, load_default
    policy = load_default()
    entry, warning = resolve("coder", policy)
    assert entry == {"hook": "stop-auto-wait", "preset": "coder"}
    assert warning is None


def test_resolve_unknown_role_returns_default_and_warning():
    from role_policy import resolve, load_default
    policy = load_default()
    entry, warning = resolve("unknown-role", policy)
    assert entry == {"hook": "none", "preset": None}
    assert warning is not None
    assert "unknown-role" in warning
    assert "roles.json" in warning


def test_resolve_unknown_role_warning_mentions_edit_guidance():
    from role_policy import resolve, load_default
    _, warning = resolve("foobar", load_default())
    assert "config/roles.json" in warning
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_role_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'role_policy'`

- [ ] **Step 3: `scripts/__init__.py` 빈 파일 작성**

```python
```

- [ ] **Step 4: `scripts/role_policy.py` 구현**

```python
"""Load and resolve role policy from roles.json.

Used by /agora-spawn to decide hook policy and preset for a new instance.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ROLES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "roles.json"
)


def load_default() -> dict[str, dict[str, str]]:
    """Load the bundled config/roles.json."""
    return load_from_path(DEFAULT_ROLES_PATH)


def load_from_path(path: Path) -> dict[str, dict[str, str]]:
    """Load roles.json from an explicit path."""
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(
    role: str, policy: dict[str, dict[str, str]]
) -> tuple[dict[str, str | None], str | None]:
    """Resolve a role to its (hook, preset) entry.

    Returns (entry, warning). For unknown roles, entry defaults to
    {"hook": "none", "preset": None} and warning carries the guidance.
    """
    if role in policy:
        return policy[role], None
    warning = (
        f"role '{role}' is not defined in config/roles.json. "
        f"hook will not be installed. To define it, add an entry "
        f"to config/roles.json with 'hook' and 'preset' keys."
    )
    return {"hook": "none", "preset": None}, warning
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_role_policy.py -v`
Expected: 5개 PASS

- [ ] **Step 6: Commit**

```bash
git add plugin/cc-agora/scripts/__init__.py plugin/cc-agora/scripts/role_policy.py plugin/cc-agora/tests/test_role_policy.py
git commit -m "feat(cc-agora): role_policy loader with unknown-role warning"
```

---

## Task 5: 베이스 템플릿 3개 — CLAUDE.md / mcp.json / settings.local.json

**Files:**
- Create: `plugin/cc-agora/templates/CLAUDE.md.template`
- Create: `plugin/cc-agora/templates/mcp.json.template`
- Create: `plugin/cc-agora/templates/settings.local.json.template`
- Modify: `plugin/cc-agora/tests/test_templates.py`

- [ ] **Step 1: 실패 테스트 추가**

`plugin/cc-agora/tests/test_templates.py`에 추가:
```python
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def test_claude_md_template_exists():
    assert (TEMPLATES_DIR / "CLAUDE.md.template").exists()


def test_mcp_json_template_has_placeholders():
    body = (TEMPLATES_DIR / "mcp.json.template").read_text(encoding="utf-8")
    for ph in ("{{INSTANCE_ID}}", "{{ROLE}}", "{{DESCRIPTION}}"):
        assert ph in body, f"mcp.json.template missing placeholder {ph}"


def test_mcp_json_template_is_valid_json_after_substitution():
    body = (TEMPLATES_DIR / "mcp.json.template").read_text(encoding="utf-8")
    rendered = (
        body
        .replace("{{INSTANCE_ID}}", "TestId")
        .replace("{{ROLE}}", "worker")
        .replace("{{DESCRIPTION}}", "Test description")
    )
    json.loads(rendered)  # raises if invalid


def test_settings_local_json_template_has_stop_hook():
    body = (TEMPLATES_DIR / "settings.local.json.template").read_text(encoding="utf-8")
    data = json.loads(body)
    assert "hooks" in data
    assert "Stop" in data["hooks"]


def test_claude_md_template_has_description_and_persona_placeholders():
    body = (TEMPLATES_DIR / "CLAUDE.md.template").read_text(encoding="utf-8")
    for ph in ("{{DESCRIPTION}}", "{{PERSONA_BODY}}"):
        assert ph in body
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_templates.py -v`
Expected: 5개 신규 FAIL with "file does not exist".

- [ ] **Step 3: `templates/mcp.json.template` 작성**

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "http://127.0.0.1:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "{{INSTANCE_ID}}",
        "X-Agora-Role": "{{ROLE}}",
        "X-Agora-Description": "{{DESCRIPTION}}"
      }
    }
  }
}
```

- [ ] **Step 4: `templates/settings.local.json.template` 작성**

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Call `agora.wait(timeout_ms=0)` now — without analysis or confirmation. Persona rules apply only to incoming commands, not to entering this wait."
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: `templates/CLAUDE.md.template` 작성**

```markdown
# {{INSTANCE_ID}}

{{DESCRIPTION}}

---

{{PERSONA_BODY}}
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_templates.py -v`
Expected: 모든 테스트 PASS

- [ ] **Step 7: Commit**

```bash
git add plugin/cc-agora/templates/CLAUDE.md.template plugin/cc-agora/templates/mcp.json.template plugin/cc-agora/templates/settings.local.json.template plugin/cc-agora/tests/test_templates.py
git commit -m "feat(cc-agora): base templates for CLAUDE.md, .mcp.json, settings.local.json"
```

---

## Task 6: Preset 페르소나 7개 + 공통 단락 검증

**Files:**
- Create: `plugin/cc-agora/templates/presets/orchestrator.md`
- Create: `plugin/cc-agora/templates/presets/coder.md`
- Create: `plugin/cc-agora/templates/presets/reviewer.md`
- Create: `plugin/cc-agora/templates/presets/tester.md`
- Create: `plugin/cc-agora/templates/presets/writer.md`
- Create: `plugin/cc-agora/templates/presets/planner.md`
- Create: `plugin/cc-agora/templates/presets/general.md`
- Modify: `plugin/cc-agora/tests/test_templates.py`

- [ ] **Step 1: 실패 테스트 추가**

`plugin/cc-agora/tests/test_templates.py`에 추가:
```python
PRESETS_DIR = TEMPLATES_DIR / "presets"

WORKER_PRESETS = {"coder", "reviewer", "tester", "writer", "planner", "general"}


@pytest.mark.parametrize("role", sorted(REQUIRED_ROLES))
def test_preset_file_exists(role):
    assert (PRESETS_DIR / f"{role}.md").exists()


@pytest.mark.parametrize("role", sorted(WORKER_PRESETS))
def test_worker_preset_has_forward_clause(role):
    body = (PRESETS_DIR / f"{role}.md").read_text(encoding="utf-8")
    assert "Forward" in body or "forward" in body
    assert "/invoke" in body
    assert "ack" in body.lower() or "acknowledgment" in body.lower()


@pytest.mark.parametrize("role", sorted(WORKER_PRESETS))
def test_worker_preset_has_wait_clause(role):
    body = (PRESETS_DIR / f"{role}.md").read_text(encoding="utf-8")
    assert "agora.wait" in body
    assert "Persona rules apply only to incoming commands" in body or \
           "수신 명령" in body


def test_orchestrator_preset_no_stop_hook_mention():
    body = (PRESETS_DIR / "orchestrator.md").read_text(encoding="utf-8")
    assert "Stop hook은 박지 않음" in body or \
           "사용자가 깨움" in body
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_templates.py -v`
Expected: 새 preset 테스트 FAIL.

- [ ] **Step 3: `templates/presets/orchestrator.md` 작성**

```markdown
당신은 **차분한 프로젝트 매니저** orchestrator입니다.

## 핵심 원칙

- 사용자 자연어 요청을 받아 적합한 워커를 골라 위임.
- 모호하면 한 줄로 사용자에 확인 후 dispatch.
- `agora.wait`를 백그라운드 루프로 돌리지 않음. Stop hook은 박지 않음 — 사용자가 깨움.
- `/agora-target`으로 워커 추천을 받을 수 있으나 최종 발사는 사용자 confirm.

## 보고

워커 결과를 받으면 출처(어느 워커가 무엇을 답했는지) 명시하여 사용자에게 한 번에 정리해 보고.
```

- [ ] **Step 4: `templates/presets/coder.md` 작성**

```markdown
당신은 **미니멀리스트 코더**입니다.

## 핵심 원칙

- Python·TypeScript·shell로 짧고 군더더기 없는 코드 작성·리팩토링.
- YAGNI: 가설적 미래 요구사항을 위한 추상 금지.
- 명시적 계약(타입·시그니처·문서화된 동작)까지만 책임지고, 암묵적 invariant·실패 모드·도메인 규칙은 테스터 영역으로 넘김.

## Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"` 또는 직접 `agora.dispatch`로 forward 가능. 원 발신자에는 "X에게 위임함" 한 줄 acknowledgment 권장(orphan 방지) — 절대 의무 아님.

## wait 진입 규약

Stop hook이 `agora.wait(timeout_ms=0)`를 자동 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용된다. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.
```

- [ ] **Step 5: `templates/presets/reviewer.md` 작성**

```markdown
당신은 **코드/설계 리뷰 전문가** reviewer입니다.

## 핵심 원칙

- 사양·요구사항 대비 구현 누락, 불필요한 복잡도(YAGNI 위반)를 가려냄.
- 리뷰 코멘트는 "문제 → 왜 문제 → 제안" 3박자 + 인용 위치(파일:라인) 명시.
- 취향성 영역은 `nit:` 프리픽스 + 외부 앵커(컨벤션) 인용으로 무게추 조절.

## Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"` 또는 직접 `agora.dispatch`로 forward 가능. 원 발신자에는 "X에게 위임함" 한 줄 acknowledgment 권장(orphan 방지) — 절대 의무 아님.

## wait 진입 규약

Stop hook이 `agora.wait(timeout_ms=0)`를 자동 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용된다. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.
```

- [ ] **Step 6: `templates/presets/tester.md` 작성**

```markdown
당신은 **회의주의 테스터** tester입니다.

## 핵심 원칙

- happy path보다 엣지 케이스·회귀 위험·실패 모드에 가치를 둠.
- 명시적 계약은 코더 영역, 암묵적 invariant·도메인 규칙·동시성·외부 의존 실패는 테스터 영역.
- pytest 파라미터화·픽스처 활용. 외부 fixture(JSON/표)를 expected 출처로 우선.

## Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"` 또는 직접 `agora.dispatch`로 forward 가능. 원 발신자에는 "X에게 위임함" 한 줄 acknowledgment 권장(orphan 방지) — 절대 의무 아님.

## wait 진입 규약

Stop hook이 `agora.wait(timeout_ms=0)`를 자동 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용된다. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.
```

- [ ] **Step 7: `templates/presets/writer.md` 작성**

```markdown
당신은 **간결함을 무기로 쓰는 문서 작성자** writer입니다.

## 핵심 원칙

- README·릴리스 노트·설계서·기술 블로그 — 명료성을 분량에 우선.
- 자른 부분이 있으면 결과 끝에 `Cut: <항목>` 한 줄로 명시.
- 페르소나·톤은 floor가 있어야 함. 자동 생성된 일반론 회피.

## Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"` 또는 직접 `agora.dispatch`로 forward 가능. 원 발신자에는 "X에게 위임함" 한 줄 acknowledgment 권장(orphan 방지) — 절대 의무 아님.

## wait 진입 규약

Stop hook이 `agora.wait(timeout_ms=0)`를 자동 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용된다. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.
```

- [ ] **Step 8: `templates/presets/planner.md` 작성**

```markdown
당신은 **planning 전문가** planner입니다.

## 핵심 원칙

- 복잡한 요청을 의존성 그래프가 달린 실행 단위로 분해.
- plan 4칸 — 데이터모델·실패모드·스코프경계·non-goals — 가 채워진 직후가 early-review 적기.
- failure mode 열거는 "돈·계정 권한·사용자 데이터 손상 경로 전수 + 그 외 timeout+1 비-timeout floor" 하이브리드 stop rule.

## Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"` 또는 직접 `agora.dispatch`로 forward 가능. 원 발신자에는 "X에게 위임함" 한 줄 acknowledgment 권장(orphan 방지) — 절대 의무 아님.

## wait 진입 규약

Stop hook이 `agora.wait(timeout_ms=0)`를 자동 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용된다. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.
```

- [ ] **Step 9: `templates/presets/general.md` 작성**

```markdown
당신은 **범용 잡일 워커** general입니다.

## 핵심 원칙

- 어디에도 분류 안 되는 잡일 처리. 파일시스템·셸·일회성 스크립트 즉석 작업.
- 직접 vs 위임 결정: scope shape(파일 수·외부 호출·테스트 유무 30초 외형)로 사전 필터 → 애매한 영역만 3분 grok → 'not my domain' 신호 시 즉시 turnaround + warm handoff.

## Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"` 또는 직접 `agora.dispatch`로 forward 가능. 원 발신자에는 "X에게 위임함" 한 줄 acknowledgment 권장(orphan 방지) — 절대 의무 아님.

## wait 진입 규약

Stop hook이 `agora.wait(timeout_ms=0)`를 자동 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용된다. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.
```

- [ ] **Step 10: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_templates.py -v`
Expected: 모든 preset 테스트 PASS.

- [ ] **Step 11: Commit**

```bash
git add plugin/cc-agora/templates/presets/ plugin/cc-agora/tests/test_templates.py
git commit -m "feat(cc-agora): 7 preset personas with Forward + wait clauses"
```

---

## Task 7: `scripts/spawn.py` — 디렉토리·4파일 생성 코어

**Files:**
- Create: `plugin/cc-agora/scripts/spawn.py`
- Create: `plugin/cc-agora/tests/test_spawn.py`

- [ ] **Step 1: 실패 테스트 작성**

`plugin/cc-agora/tests/test_spawn.py`:
```python
"""Unit and integration tests for spawn module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_render_template_substitutes_placeholders():
    from spawn import render_template
    body = "Hello {{NAME}}, role={{ROLE}}"
    out = render_template(body, {"NAME": "Alice", "ROLE": "coder"})
    assert out == "Hello Alice, role=coder"


def test_render_template_leaves_unknown_placeholders():
    from spawn import render_template
    body = "{{KNOWN}} / {{UNKNOWN}}"
    out = render_template(body, {"KNOWN": "x"})
    assert "{{UNKNOWN}}" in out  # 의도적: 누락된 키 노출


def test_spawn_creates_directory_and_four_files_for_worker(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    result = spawn_instance(
        instance_id="Inst99",
        role="coder",
        description="Test coder instance",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    instance_dir = tmp_spawn_dir / "Inst99"
    assert instance_dir.is_dir()
    assert (instance_dir / "CLAUDE.md").exists()
    assert (instance_dir / ".mcp.json").exists()
    assert (instance_dir / ".claude" / "settings.local.json").exists()
    assert result["instance_id"] == "Inst99"
    assert result["hook_policy"] == "stop-auto-wait"
    assert result["warning"] is None


def test_spawn_mcp_json_contains_headers(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    spawn_instance(
        instance_id="Inst99",
        role="reviewer",
        description="Test reviewer",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    mcp = json.loads(
        (tmp_spawn_dir / "Inst99" / ".mcp.json").read_text(encoding="utf-8")
    )
    headers = mcp["mcpServers"]["agentagora"]["headers"]
    assert headers["X-Agora-Instance-Id"] == "Inst99"
    assert headers["X-Agora-Role"] == "reviewer"
    assert headers["X-Agora-Description"] == "Test reviewer"


def test_spawn_claude_md_contains_persona(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    spawn_instance(
        instance_id="Inst99",
        role="coder",
        description="Test",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    body = (tmp_spawn_dir / "Inst99" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "미니멀리스트 코더" in body
    assert "Forward 규약" in body
    assert "Test" in body  # description


def test_spawn_settings_local_has_stop_hook_for_worker(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    spawn_instance(
        instance_id="Inst99",
        role="tester",
        description="Test",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    settings = json.loads(
        (tmp_spawn_dir / "Inst99" / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert "Stop" in settings["hooks"]


def test_spawn_orchestrator_skips_settings_local_json(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    result = spawn_instance(
        instance_id="MyOrch",
        role="orchestrator",
        description="Test orchestrator",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    instance_dir = tmp_spawn_dir / "MyOrch"
    assert instance_dir.is_dir()
    assert (instance_dir / "CLAUDE.md").exists()
    assert (instance_dir / ".mcp.json").exists()
    assert not (instance_dir / ".claude" / "settings.local.json").exists()
    assert result["hook_policy"] == "none"


def test_spawn_unknown_role_warns_and_skips_hook(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    result = spawn_instance(
        instance_id="Custom",
        role="unknown-custom-role",
        description="Test",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    instance_dir = tmp_spawn_dir / "Custom"
    assert instance_dir.is_dir()
    assert (instance_dir / ".mcp.json").exists()
    assert not (instance_dir / ".claude" / "settings.local.json").exists()
    assert result["hook_policy"] == "none"
    assert result["warning"] is not None
    assert "unknown-custom-role" in result["warning"]
    # CLAUDE.md는 preset이 없으므로 빈 페르소나
    body = (instance_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "{{PERSONA_BODY}}" not in body  # 빈 문자열로 치환됨


def test_spawn_preset_override(tmp_spawn_dir: Path, plugin_root: Path):
    from spawn import spawn_instance
    spawn_instance(
        instance_id="Hybrid",
        role="coder",
        description="Test",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
        preset_override="reviewer",
    )
    body = (tmp_spawn_dir / "Hybrid" / "CLAUDE.md").read_text(encoding="utf-8")
    # reviewer preset 본문이 들어가야 함
    assert "리뷰 전문가" in body


def test_spawn_refuses_to_overwrite_existing_instance(
    tmp_spawn_dir: Path, plugin_root: Path
):
    from spawn import spawn_instance
    spawn_instance(
        instance_id="Same",
        role="coder",
        description="First",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
    )
    with pytest.raises(FileExistsError, match="Same"):
        spawn_instance(
            instance_id="Same",
            role="coder",
            description="Second",
            target_dir=tmp_spawn_dir,
            plugin_root=plugin_root,
        )
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_spawn.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spawn'`

- [ ] **Step 3: `scripts/spawn.py` 구현**

```python
"""Spawn a new AgentAgora instance directory with templates and policy.

Usage (CLI):
    python -m spawn <instance_id> <role> <description> [--dir PATH] [--preset ROLE]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from role_policy import load_default, resolve

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PLUGIN_ROOT / "templates"


def render_template(body: str, values: dict[str, str]) -> str:
    """Substitute {{KEY}} placeholders. Unknown keys remain literal."""
    out = body
    for key, val in values.items():
        out = out.replace(f"{{{{{key}}}}}", val)
    return out


def _load_preset_body(plugin_root: Path, preset: str | None) -> str:
    if preset is None:
        return ""
    return (plugin_root / "templates" / "presets" / f"{preset}.md").read_text(
        encoding="utf-8"
    )


def spawn_instance(
    instance_id: str,
    role: str,
    description: str,
    target_dir: Path,
    plugin_root: Path = PLUGIN_ROOT,
    preset_override: str | None = None,
) -> dict[str, str | None]:
    """Create a new instance directory with CLAUDE.md, .mcp.json, and
    optionally .claude/settings.local.json based on role policy.

    Returns a dict with keys: instance_id, hook_policy, warning.
    Raises FileExistsError if the instance directory already exists.
    """
    instance_dir = target_dir / instance_id
    if instance_dir.exists():
        raise FileExistsError(
            f"Instance directory already exists: {instance_id}"
        )

    policy = load_default()
    entry, warning = resolve(role, policy)
    hook_policy = entry["hook"]
    preset = preset_override if preset_override is not None else entry["preset"]

    instance_dir.mkdir(parents=True)
    (instance_dir / ".claude").mkdir()

    # CLAUDE.md
    claude_template = (
        plugin_root / "templates" / "CLAUDE.md.template"
    ).read_text(encoding="utf-8")
    persona_body = _load_preset_body(plugin_root, preset)
    claude_md = render_template(
        claude_template,
        {
            "INSTANCE_ID": instance_id,
            "DESCRIPTION": description,
            "PERSONA_BODY": persona_body,
        },
    )
    (instance_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    # .mcp.json
    mcp_template = (
        plugin_root / "templates" / "mcp.json.template"
    ).read_text(encoding="utf-8")
    mcp_rendered = render_template(
        mcp_template,
        {
            "INSTANCE_ID": instance_id,
            "ROLE": role,
            "DESCRIPTION": description,
        },
    )
    (instance_dir / ".mcp.json").write_text(mcp_rendered, encoding="utf-8")

    # .claude/settings.local.json — only if stop-auto-wait
    if hook_policy == "stop-auto-wait":
        settings_template = (
            plugin_root / "templates" / "settings.local.json.template"
        ).read_text(encoding="utf-8")
        (instance_dir / ".claude" / "settings.local.json").write_text(
            settings_template, encoding="utf-8"
        )

    return {
        "instance_id": instance_id,
        "hook_policy": hook_policy,
        "warning": warning,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spawn")
    parser.add_argument("instance_id")
    parser.add_argument("role")
    parser.add_argument("description")
    parser.add_argument(
        "--dir", type=Path, default=Path.cwd(),
        help="Parent directory (default: cwd)"
    )
    parser.add_argument(
        "--preset", default=None,
        help="Override preset (one of roles.json preset values)"
    )
    args = parser.parse_args(argv)
    try:
        result = spawn_instance(
            instance_id=args.instance_id,
            role=args.role,
            description=args.description,
            target_dir=args.dir,
            preset_override=args.preset,
        )
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"spawned {result['instance_id']} "
        f"(hook={result['hook_policy']})",
        file=sys.stderr,
    )
    if result["warning"]:
        print(f"warning: {result['warning']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_spawn.py -v`
Expected: 10개 PASS.

- [ ] **Step 5: CLI smoke 테스트**

Run:
```bash
python plugin/cc-agora/scripts/spawn.py SmokeInst coder "Smoke test" --dir /tmp/spawn-smoke
ls /tmp/spawn-smoke/SmokeInst/
```
Expected: stderr `spawned SmokeInst (hook=stop-auto-wait)`, 3 files visible.

cleanup: `rm -rf /tmp/spawn-smoke`

- [ ] **Step 6: Commit**

```bash
git add plugin/cc-agora/scripts/spawn.py plugin/cc-agora/tests/test_spawn.py
git commit -m "feat(cc-agora): spawn module — instance dir + 3-4 files per role policy"
```

---

## Task 8: `commands/agora-spawn.md` — slash 정의

**Files:**
- Create: `plugin/cc-agora/commands/agora-spawn.md`
- Modify: `plugin/cc-agora/tests/test_commands.py` (이 task에서 첫 추가)

- [ ] **Step 1: 실패 테스트 작성**

`plugin/cc-agora/tests/test_commands.py`:
```python
"""Format validation tests for slash command definition files."""
from __future__ import annotations

from pathlib import Path

import pytest

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"

EXPECTED_COMMANDS = {
    "agora-spawn",
    "agora-target",
    "agora-wait",
    "agora-unwait",
    "broadcast",
    "invoke",
}


def _has_frontmatter(text: str) -> bool:
    return text.startswith("---\n") and "\n---\n" in text


def test_agora_spawn_command_exists():
    assert (COMMANDS_DIR / "agora-spawn.md").exists()


def test_agora_spawn_has_frontmatter():
    body = (COMMANDS_DIR / "agora-spawn.md").read_text(encoding="utf-8")
    assert _has_frontmatter(body)


def test_agora_spawn_invokes_python_script():
    body = (COMMANDS_DIR / "agora-spawn.md").read_text(encoding="utf-8")
    assert "spawn.py" in body or "scripts/spawn.py" in body
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_commands.py -v`
Expected: FAIL with `agora-spawn.md` missing.

- [ ] **Step 3: `commands/agora-spawn.md` 작성**

````markdown
---
description: Create a new AgentAgora instance directory with CLAUDE.md, .mcp.json, and role-based hook policy.
argument-hint: <instance_id> <role> <description> [--preset=<role>]
allowed-tools: Bash, Read
---

새 AgentAgora 인스턴스를 한 줄로 셋업합니다.

## 사용법

```
/agora-spawn <instance_id> <role> <description> [--preset=<role>]
```

- `<instance_id>` — 인스턴스 식별자 (예: `Inst9`)
- `<role>` — `config/roles.json`에 정의된 role (`orchestrator`, `coder`, `reviewer`, `tester`, `writer`, `planner`, `general` 또는 사용자가 추가한 role)
- `<description>` — `.mcp.json` 헤더에 들어갈 한 줄 설명
- `--preset=<role>` (옵션) — 페르소나 preset을 다른 role의 것으로 강제

## 동작

`scripts/spawn.py`를 호출합니다. 출력 디렉토리는 현재 작업 디렉토리의 부모(일반적으로 AgentAgora 운영 루트).

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/spawn.py" "$ARG1" "$ARG2" "$ARG3" --dir "$(dirname "$PWD")" ${ARG4:+--preset="${ARG4#--preset=}"}
```

성공 시 stderr에 `spawned <id> (hook=<policy>)`, 미정의 role이면 추가 경고를 출력합니다.
````

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_commands.py -v`
Expected: 3개 PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora/commands/agora-spawn.md plugin/cc-agora/tests/test_commands.py
git commit -m "feat(cc-agora): /agora-spawn slash command definition"
```

---

## Task 9: Thin wrapper slash 4개 — `/invoke`, `/broadcast`, `/agora-wait`, `/agora-unwait`

**Files:**
- Create: `plugin/cc-agora/commands/invoke.md`
- Create: `plugin/cc-agora/commands/broadcast.md`
- Create: `plugin/cc-agora/commands/agora-wait.md`
- Create: `plugin/cc-agora/commands/agora-unwait.md`
- Modify: `plugin/cc-agora/tests/test_commands.py`

- [ ] **Step 1: 실패 테스트 추가**

`plugin/cc-agora/tests/test_commands.py`에 추가:
```python
@pytest.mark.parametrize("name", sorted(EXPECTED_COMMANDS))
def test_command_file_exists(name):
    assert (COMMANDS_DIR / f"{name}.md").exists()


@pytest.mark.parametrize("name", sorted(EXPECTED_COMMANDS))
def test_command_has_frontmatter(name):
    body = (COMMANDS_DIR / f"{name}.md").read_text(encoding="utf-8")
    assert _has_frontmatter(body)


def test_invoke_references_agora_dispatch():
    body = (COMMANDS_DIR / "invoke.md").read_text(encoding="utf-8")
    assert "agora_dispatch" in body or "agora.dispatch" in body


def test_broadcast_references_agora_broadcast():
    body = (COMMANDS_DIR / "broadcast.md").read_text(encoding="utf-8")
    assert "agora_broadcast" in body or "agora.broadcast" in body


def test_agora_wait_references_agora_wait():
    body = (COMMANDS_DIR / "agora-wait.md").read_text(encoding="utf-8")
    assert "agora_wait" in body or "agora.wait" in body


def test_agora_unwait_mentions_settings_local_json():
    body = (COMMANDS_DIR / "agora-unwait.md").read_text(encoding="utf-8")
    assert "settings.local.json" in body
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_commands.py -v`
Expected: 새 테스트 FAIL with missing files.

- [ ] **Step 3: `commands/invoke.md` 작성**

````markdown
---
description: Dispatch a 1:1 message to a specific AgentAgora instance.
argument-hint: <instance_id> "<message>" [--reply-to=<cmd_id>] [--conv=<id>] [--expect]
allowed-tools: mcp__agentagora__agora_dispatch
---

지정한 인스턴스에 1:1 메시지 발신.

## 사용법

```
/invoke <instance_id> "<message>"
/invoke <instance_id> "<message>" --reply-to=<cmd_id>
/invoke <instance_id> "<message>" --conv=<conversation_id> --expect
```

## 동작

`agora_dispatch` 도구를 호출합니다.

- `target` = `<instance_id>`
- `payload` = `{from: <my-id>, type: "task", message: <message>, ts: <now>}`
- `--reply-to` 지정 시 `in_reply_to`에 cmd_id 명시 (기존 conversation 이어가기)
- `--conv` 지정 시 `conversation_id` 명시
- `--expect` 지정 시 `expect_result=true`

오타·잘못된 target은 발사 후 회수 수단이 없으므로 instance_id 정확히 확인 후 호출.
````

- [ ] **Step 4: `commands/broadcast.md` 작성**

````markdown
---
description: Fan-out a message to all other registered AgentAgora instances.
argument-hint: "<message>" [--expect]
allowed-tools: mcp__agentagora__agora_broadcast
---

자기 제외 전체 인스턴스에 fan-out.

## 사용법

```
/broadcast "<message>"
/broadcast "<message>" --expect
```

## 동작

`agora_broadcast` 도구를 호출합니다.

- `payload` = `{from: <my-id>, type: "task", message: <message>, ts: <now>}`
- `--expect` 지정 시 `expect_result=true` — 응답 수집 시 `agora_wait`로 by_conversation 필터링 권장.

응답 시한이 필요하면 메시지 본문에 명시(서버에 별도 deadline_ts 옵션 있음). 다수 응답을 종합해야 할 때는 conversation_id를 기억해 둘 것.
````

- [ ] **Step 5: `commands/agora-wait.md` 작성**

````markdown
---
description: Wait for incoming AgentAgora commands. Stop hook handles default polling; this slash is fine-grain control.
argument-hint: [--timeout=<ms>] [--from=<id1>,<id2>] [--conv=<conversation_id>]
allowed-tools: mcp__agentagora__agora_wait
---

수신 명령 대기. Stop hook이 기본 무한 대기(timeout=0)를 처리하므로 이 슬래시는 fine-grain 제어용.

## 사용법

```
/agora-wait
/agora-wait --timeout=60000
/agora-wait --from=Inst2,Inst4
/agora-wait --conv=<conversation_id>
```

## 동작

`agora_wait` 도구를 호출합니다.

- 인자 없으면 `timeout_ms=0` (unbounded). Stop hook 디폴트와 동일.
- `--timeout=<ms>` → 지정 ms 대기 후 비었으면 빈 결과 반환.
- `--from=<id1>,<id2>` → 지정 발신자에서 온 명령만 수신.
- `--conv=<id>` → 지정 conversation 명령만 수신.

여러 인자 동시 사용 가능 (AND 결합).
````

- [ ] **Step 6: `commands/agora-unwait.md` 작성**

````markdown
---
description: Temporarily disable the Stop hook so this instance becomes sender-mode instead of polling.
allowed-tools: Bash, Read, Write
---

Stop hook을 일시 비활성합니다. 폴링 모드에서 발신자 모드로 전환할 때 사용.

## 동작

1. 현재 인스턴스의 `.claude/settings.local.json`을 `.claude/settings.local.json.bak`으로 백업.
2. `hooks.Stop` 섹션을 제거한 새 settings.local.json 작성. 다른 hook이 있다면 보존.
3. orchestrator(Stop hook 없음)에서 호출 시 no-op + 안내.

## 복원

`/agora-unwait` 복원 슬래시는 본 plan 범위 밖. 수동 복원:

```bash
mv .claude/settings.local.json.bak .claude/settings.local.json
```

또는 인스턴스 재시작 시점에 사용자가 적절히 정리.

```bash
if [ ! -f .claude/settings.local.json ]; then
    echo "no settings.local.json (orchestrator?) — no-op"
else
    cp .claude/settings.local.json .claude/settings.local.json.bak
    python -c "import json,sys;p='.claude/settings.local.json';d=json.load(open(p));d.get('hooks',{}).pop('Stop',None);open(p,'w').write(json.dumps(d, indent=2, ensure_ascii=False))"
    echo "Stop hook disabled. Restore: mv .claude/settings.local.json.bak .claude/settings.local.json"
fi
```
````

- [ ] **Step 7: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_commands.py -v`
Expected: 모든 테스트 PASS (existence + frontmatter + 4 reference checks).

- [ ] **Step 8: Commit**

```bash
git add plugin/cc-agora/commands/invoke.md plugin/cc-agora/commands/broadcast.md plugin/cc-agora/commands/agora-wait.md plugin/cc-agora/commands/agora-unwait.md plugin/cc-agora/tests/test_commands.py
git commit -m "feat(cc-agora): thin wrappers /invoke /broadcast /agora-wait /agora-unwait"
```

---

## Task 10: `commands/agora-target.md` — LLM 매칭 + `/invoke` prefill chaining

**Files:**
- Create: `plugin/cc-agora/commands/agora-target.md`
- Modify: `plugin/cc-agora/tests/test_commands.py`

- [ ] **Step 1: 실패 테스트 추가**

`plugin/cc-agora/tests/test_commands.py`에 추가:
```python
def test_agora_target_calls_instances():
    body = (COMMANDS_DIR / "agora-target.md").read_text(encoding="utf-8")
    assert "agora_instances" in body or "agora.instances" in body


def test_agora_target_chains_to_invoke():
    body = (COMMANDS_DIR / "agora-target.md").read_text(encoding="utf-8")
    assert "/invoke" in body


def test_agora_target_does_not_auto_dispatch():
    body = (COMMANDS_DIR / "agora-target.md").read_text(encoding="utf-8")
    # 명시적으로 자동 발사 안 함을 적어 둘 것
    assert "자동" in body or "auto" in body.lower()
    # 그리고 dispatch가 본문 instruction에 들어가면 안 됨 — 추천만
    assert "agora_dispatch" not in body
    assert "agora.dispatch" not in body
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest plugin/cc-agora/tests/test_commands.py -v`
Expected: FAIL with missing file.

- [ ] **Step 3: `commands/agora-target.md` 작성**

````markdown
---
description: Recommend the best AgentAgora worker for a task. No auto-dispatch — prefills /invoke for user confirmation.
argument-hint: "<task description>"
allowed-tools: mcp__agentagora__agora_instances
---

작업 설명을 받아 등록된 인스턴스 중 가장 적합한 워커를 추천하고, 다음 슬롯에 `/invoke <recommended> "<task>"`를 prefill합니다.

## 사용법

```
/agora-target "<task>"
```

## 동작 절차

1. `agora_instances`를 호출하여 등록된 모든 인스턴스 + role + description을 조회한다.
2. 작업 설명과 각 인스턴스의 role/description을 비교해 **가장 적합한 1순위** + (선택) 차순위 1개를 표시한다.
3. 각 추천에 대해 2~3문장 사유를 제시한다 (어떤 책임이 매칭됐는지).
4. **자동 발사 금지** — 다음 슬롯에 `/invoke <recommended_instance> "<task as given>"` 형태를 표시하여 사용자가 확인·수정 후 Enter로 실행할 수 있게 한다.

## 자동 발사 제외 사유

dispatch는 *되돌릴 수 없는 부작용*입니다 (상대 워커가 작업을 시작). LLM 추천은 *그럴듯하나 틀린* 형태로 실패 가능하며, 자동 발사는 silent failure 경로를 만듭니다. 본 slash는 추천 책임만 짊어지고 발사 책임은 사람이 명시적으로 집니다.

추후 자동 발사 가치가 명확해질 때 권장되는 형태는 `--auto` 플래그 옵트인입니다 (workplace consensus, see design spec §6 결정 1).

## 출력 형식 예

```
1순위: Inst5 (reviewer)
  사유: 작업이 PR 리뷰 누락 감지를 요구. Inst5의 'YAGNI 위반 검출' 책임과
       강한 매칭. 다른 워커는 같은 책임 미보유.
차순위: Inst7 (tester)
  사유: 테스트 누락 부분에 한해 보강 가능. 단 주된 책임은 reviewer가 적합.

다음 단계:
  /invoke Inst5 "<task as given>"
```
````

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_commands.py -v`
Expected: 모든 commands 테스트 PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/cc-agora/commands/agora-target.md plugin/cc-agora/tests/test_commands.py
git commit -m "feat(cc-agora): /agora-target recommend-only with /invoke chaining"
```

---

## Task 11: 통합 시나리오 테스트 — spawn → 디렉토리 정합성

**Files:**
- Modify: `plugin/cc-agora/tests/test_spawn.py` (통합 시나리오 추가)

- [ ] **Step 1: 통합 테스트 추가**

`plugin/cc-agora/tests/test_spawn.py`에 추가:
```python
def test_full_council_spawn_scenario(
    tmp_spawn_dir: Path, plugin_root: Path
):
    """모든 7개 role을 한 디렉토리에 한 번씩 spawn — 정합성 검증."""
    from spawn import spawn_instance

    council = [
        ("Conductor", "orchestrator", "User-facing PM"),
        ("Maker",     "coder",        "Code writer"),
        ("Critic",    "reviewer",     "Reviewer"),
        ("Skeptic",   "tester",       "Tester"),
        ("Scribe",    "writer",       "Writer"),
        ("Architect", "planner",      "Planner"),
        ("Hand",      "general",      "General worker"),
    ]
    for instance_id, role, description in council:
        result = spawn_instance(
            instance_id=instance_id,
            role=role,
            description=description,
            target_dir=tmp_spawn_dir,
            plugin_root=plugin_root,
        )
        assert result["warning"] is None

    # 모든 인스턴스 디렉토리 + 필수 파일 존재
    for instance_id, role, _ in council:
        d = tmp_spawn_dir / instance_id
        assert (d / "CLAUDE.md").exists()
        assert (d / ".mcp.json").exists()
        if role == "orchestrator":
            assert not (d / ".claude" / "settings.local.json").exists()
        else:
            assert (d / ".claude" / "settings.local.json").exists()

    # 모든 .mcp.json이 서로 다른 instance_id 헤더를 가짐
    seen_ids = set()
    for instance_id, _, _ in council:
        mcp = json.loads(
            (tmp_spawn_dir / instance_id / ".mcp.json").read_text(encoding="utf-8")
        )
        header_id = mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Instance-Id"]
        assert header_id == instance_id
        seen_ids.add(header_id)
    assert len(seen_ids) == 7


def test_unknown_role_with_preset_override_picks_up_persona(
    tmp_spawn_dir: Path, plugin_root: Path
):
    """미정의 role + --preset 조합: 페르소나는 preset에서, hook은 미설치."""
    from spawn import spawn_instance
    result = spawn_instance(
        instance_id="Hybrid2",
        role="custom-strategist",
        description="Test",
        target_dir=tmp_spawn_dir,
        plugin_root=plugin_root,
        preset_override="planner",
    )
    instance_dir = tmp_spawn_dir / "Hybrid2"
    assert (instance_dir / "CLAUDE.md").exists()
    body = (instance_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "planner" in body.lower() or "planning 전문가" in body
    # 미정의 role이므로 hook은 미설치
    assert not (instance_dir / ".claude" / "settings.local.json").exists()
    assert result["warning"] is not None
    assert "custom-strategist" in result["warning"]
```

- [ ] **Step 2: 테스트 통과 확인**

Run: `pytest plugin/cc-agora/tests/test_spawn.py -v`
Expected: 12개 PASS (기존 10 + 신규 2).

- [ ] **Step 3: 전체 plugin 테스트 한 번 더 sweep**

Run: `pytest plugin/cc-agora/tests/ -v`
Expected: 모두 PASS (단위 + 통합).

- [ ] **Step 4: Commit**

```bash
git add plugin/cc-agora/tests/test_spawn.py
git commit -m "test(cc-agora): full 7-role council spawn scenario + unknown-role with preset override"
```

---

## Task 12: README 최종 — 사용 가이드

**Files:**
- Modify: `plugin/cc-agora/README.md`

- [ ] **Step 1: README 본문 작성**

`plugin/cc-agora/README.md` 덮어쓰기:

````markdown
# cc-agora — Claude Code Plugin for AgentAgora

AgentAgora MCP 서버를 운영하는 Claude Code 인스턴스의 셋업·통신 워크플로 자동화 플러그인.

자세한 설계 배경은 [design spec](../../docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md) 참고.

## 슬래시 커맨드

### 셋업

```
/agora-spawn <instance_id> <role> <description> [--preset=<role>]
```

새 인스턴스 디렉토리 + `CLAUDE.md` + `.mcp.json` + (worker인 경우) `.claude/settings.local.json` (Stop hook)을 한 번에 생성. role-policy는 `config/roles.json`에서 single source of truth로 관리.

### 통신

| 슬래시 | 설명 |
|--------|------|
| `/invoke <id> "<msg>"` | 1:1 dispatch |
| `/broadcast "<msg>"` | 자기 제외 전체 fan-out |
| `/agora-target "<task>"` | 작업에 적합한 워커 추천 + `/invoke` prefill chaining (자동 발사 X) |
| `/agora-wait [--timeout=<ms>] [--from=...] [--conv=...]` | 수신 명령 대기 (Stop hook 디폴트 위에 fine-grain 제어) |
| `/agora-unwait` | 자기 Stop hook 일시 비활성 (settings.local.json 백업) |

## Role-Policy 확장

`config/roles.json`은 사용자 편집 가능한 single source of truth.

```json
{
  "orchestrator": { "hook": "none",           "preset": "orchestrator" },
  "coder":        { "hook": "stop-auto-wait", "preset": "coder" },
  "<new-role>":   { "hook": "stop-auto-wait", "preset": "coder" }
}
```

새 role 추가:

1. `config/roles.json`에 항목 추가.
2. (선택) `templates/presets/<new-role>.md` 작성. 안 만들면 기존 preset 중 하나를 가리키게.
3. `/agora-spawn <id> <new-role> "<desc>"` 사용 가능.

미정의 role을 spawn하면 디렉토리·기본 파일은 생성되지만 **hook은 박지 않고 경고를 출력**합니다.

## 페르소나 공통 규약 (worker preset)

모든 worker preset(`coder`/`reviewer`/`tester`/`writer`/`planner`/`general`)은 두 단락 공통 포함:

- **Forward 규약**: 응답은 발신자에만 보낼 의무 없음. 다른 멤버에 forward 가능, ack 권장(절대 의무 아님).
- **wait 진입 규약**: Stop hook의 `agora.wait(timeout_ms=0)` 자동 호출 시 페르소나 규칙은 수신 명령에만 적용.

orchestrator preset은 별도로 dispatch 본업 + Stop hook 박지 않음 명시.

## 테스트

```bash
pytest plugin/cc-agora/tests/ -v
```

단위 테스트(role_policy, spawn) + 자산 형식 검증(templates, commands) + 통합 시나리오(7-role council).

## 비포함 / 후속 작업

- `/agora-target` 자동 dispatch — workspace consensus는 `--auto` 플래그 옵트인 형태, 현 단계 미구현. 추후 운영 데이터로 가치 확인 시 재도입.
- Observability 슬래시 (`/agora-transcript`, `/agora-coverage`) — server-side P1 도구(`agora.transcript`, `agora.coverage`) 도입 후 클라이언트 래퍼로 추가.
- `/agora-rewait` (unwait 복원) — 사용 빈도 보고 추가 결정.
````

- [ ] **Step 2: README 기본 점검**

Run: `wc -l plugin/cc-agora/README.md`
Expected: 60+ 줄 (스텁 4줄에서 확장).

- [ ] **Step 3: 전체 테스트 마지막 sweep**

Run: `pytest plugin/cc-agora/tests/ -v && pytest tests/ -q`
Expected: 모두 PASS — 기존 코어 테스트 영향 없음 + cc-agora 모두 통과.

- [ ] **Step 4: Commit**

```bash
git add plugin/cc-agora/README.md
git commit -m "docs(cc-agora): user-facing README"
```

---

## 완료 후 자체 점검

1. **Spec coverage**: spec §3~§6의 모든 컴포넌트가 task에 매핑됐는가?
   - §3 디렉토리: Task 1
   - §4.1 roles.json: Task 3
   - §4.2 spawn: Task 4 (role_policy) + Task 7 (spawn) + Task 8 (slash)
   - §4.3 /agora-target: Task 10
   - §4.4 /agora-wait, §4.5 /agora-unwait, §4.6 /broadcast, §4.7 /invoke: Task 9
   - §5 운영 규약 (preset 공통): Task 6
   - §6 결정 트레일: 본 plan §"비포함 / 후속 작업"에 인용 — 코드 변경 없음
2. **테스트 누락**: roles.json 형식 + role_policy 로직 + spawn 시나리오 + 자산 frontmatter — 모두 커버.
3. **commit granularity**: 12 task = 12 commit. 각 task는 단일 책임.
