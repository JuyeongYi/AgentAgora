# cc-agora-ops 운영자 플러그인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영자 콘텐츠를 신규 `cc-agora-ops` 플러그인으로 분리하고, spawn을 재설계(thin CLAUDE.md + `.claude/settings.local.json`)하며, 로컬 서버 런처와 `agora-comm-matrix` 스킬을 추가한다.

**Architecture:** `plugin/cc-agora/`의 운영자 스킬·스크립트·config·운영자 템플릿을 `git mv`로 `plugin/cc-agora-ops/`에 옮긴다. `spawn.py`는 더 이상 역할 페르소나를 `CLAUDE.md`에 stamp하지 않고 thin CLAUDE.md + 워커별 `.claude/settings.local.json`(페르소나 플러그인 활성화)을 쓴다. `roles.json`은 역할→페르소나 플러그인 이름 매핑이 된다. 페르소나 플러그인 자체는 Plan 3에서 만들지만, spawn은 플러그인 *이름 문자열*만 쓰므로 이 플랜이 먼저 머지돼도 된다.

**Tech Stack:** Python 3.13, pytest, Claude Code 플러그인. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 진단은 무시(pytest 정답).

**선행 의존:** Plan 1(`2026-05-17-cc-agora-core-plugin.md`)이 먼저 머지돼야 한다.

spec: `docs/superpowers/specs/2026-05-17-cc-agora-plugin-split-design.md` (§4·§8).

---

### Task 1: 운영자 콘텐츠를 `cc-agora-ops/`로 이동

운영자 스크립트·스킬·config·운영자 템플릿을 `git mv`로 옮긴다. 한 작업으로 묶어 중간 상태에서 테스트가 깨지지 않게 conftest·테스트 경로도 같은 작업에서 갱신한다. `payload.py`와 통신 4종 스킬은 `cc-agora`에 남는다(Plan 1 소관).

**Files:**
- Move: `plugin/cc-agora/scripts/{spawn.py,spawn_team.py,role_policy.py}` → `plugin/cc-agora-ops/scripts/`
- Move: `plugin/cc-agora/skills/{agora-spawn,agora-spawn-team}` → `plugin/cc-agora-ops/skills/`
- Move: `plugin/cc-agora/config/roles.json` → `plugin/cc-agora-ops/config/roles.json`
- Move: `plugin/cc-agora/templates/{mcp.json.template,team.json.example}` → `plugin/cc-agora-ops/templates/`
- Move: `plugin/cc-agora/templates/presets/` → `plugin/cc-agora-ops/templates/presets/` (임시 — Plan 3에서 페르소나 플러그인으로 해소)
- Modify: `tests/conftest.py`, `tests/test_plugin_role_policy.py`, `tests/test_plugin_spawn.py`, `tests/test_plugin_spawn_team.py`

- [ ] **Step 1: git mv로 파일 이동**

```bash
mkdir -p plugin/cc-agora-ops/scripts plugin/cc-agora-ops/skills plugin/cc-agora-ops/config plugin/cc-agora-ops/templates
git mv plugin/cc-agora/scripts/spawn.py plugin/cc-agora-ops/scripts/spawn.py
git mv plugin/cc-agora/scripts/spawn_team.py plugin/cc-agora-ops/scripts/spawn_team.py
git mv plugin/cc-agora/scripts/role_policy.py plugin/cc-agora-ops/scripts/role_policy.py
git mv plugin/cc-agora/skills/agora-spawn plugin/cc-agora-ops/skills/agora-spawn
git mv plugin/cc-agora/skills/agora-spawn-team plugin/cc-agora-ops/skills/agora-spawn-team
git mv plugin/cc-agora/config/roles.json plugin/cc-agora-ops/config/roles.json
git mv plugin/cc-agora/templates/mcp.json.template plugin/cc-agora-ops/templates/mcp.json.template
git mv plugin/cc-agora/templates/team.json.example plugin/cc-agora-ops/templates/team.json.example
git mv plugin/cc-agora/templates/presets plugin/cc-agora-ops/templates/presets
```

`plugin/cc-agora/scripts/`에는 `payload.py`만, `plugin/cc-agora/skills/`에는 통신 4종 + `agora-protocol`만 남아야 한다.

- [ ] **Step 2: conftest.py의 sys.path에 cc-agora-ops/scripts 추가**

`tests/conftest.py`에서 `_PLUGIN_SCRIPTS` 블록을 아래로 교체한다 (`payload.py`는 cc-agora에, 나머지는 cc-agora-ops에 있으므로 두 경로 모두 등록):

```python
# Make plugin script dirs importable for test_plugin_* modules.
# payload.py lives in cc-agora; spawn.py / spawn_team.py / role_policy.py / comm_matrix.py
# live in cc-agora-ops. Both dirs use a flat layout (no package), so each must be on
# sys.path before its modules can be imported.
for _rel in ("cc-agora/scripts", "cc-agora-ops/scripts"):
    _d = Path(__file__).resolve().parent.parent / "plugin" / _rel
    if _d.is_dir() and str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
```

- [ ] **Step 3: 테스트의 PLUGIN_ROOT 경로 갱신**

다음 3개 테스트 파일에서 `PLUGIN_ROOT` 정의를 `"cc-agora"` → `"cc-agora-ops"`로 바꾼다:

```python
PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora-ops"
```

- `tests/test_plugin_role_policy.py`
- `tests/test_plugin_spawn.py`
- `tests/test_plugin_spawn_team.py`

`tests/test_plugin_payload.py`는 `PLUGIN_ROOT`를 쓰지 않으므로(`payload`만 import) 변경하지 않는다.

- [ ] **Step 4: 테스트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_payload.py tests/test_plugin_role_policy.py tests/test_plugin_spawn.py tests/test_plugin_spawn_team.py -q`
Expected: 전부 PASS — 순수 이동이라 동작 불변.

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "refactor: 운영자 콘텐츠를 cc-agora-ops/로 이동"
```

---

### Task 2: `cc-agora-ops` plugin.json + README (양 플러그인)

**Files:**
- Create: `plugin/cc-agora-ops/.claude-plugin/plugin.json`
- Create: `plugin/cc-agora-ops/README.md`
- Modify: `plugin/cc-agora/README.md`

- [ ] **Step 1: plugin.json 생성**

`plugin/cc-agora-ops/.claude-plugin/plugin.json`:

```json
{
  "name": "cc-agora-ops",
  "description": "AgentAgora operator tooling — spawn workers, spawn teams from a manifest, manage the communication matrix, and launch a local server.",
  "version": "0.1.0"
}
```

- [ ] **Step 2: cc-agora-ops README.md 생성**

`plugin/cc-agora-ops/README.md`를 한국어로 작성한다(산출물 문서는 한국어 우선). 담을 내용: 플러그인 목적(운영자 도구), 슬래시 3종(`agora-spawn`·`agora-spawn-team`·`agora-comm-matrix`) 요약 표, `run-server.bat`으로 로컬 서버 띄우는 절차, spawn이 만드는 워커 산출물(thin CLAUDE.md + .mcp.json + run.bat + .claude/settings.local.json) 설명, `cc-agora`와 의존성이 없다는 점.

- [ ] **Step 3: cc-agora README.md 갱신**

`plugin/cc-agora/README.md`는 현재 단일 모놀리식 플러그인(슬래시 6개·spawn·presets)을 기술하는 stale 문서다. 통신 코어만 기술하도록 갱신한다(한국어): 플러그인 목적(워커 간 통신 코어), 슬래시 4종(`invoke`·`broadcast`·`agora-target`·`agora-close`) 요약 표, `agora-protocol` 운용 규칙 스킬, 운영자 셋업은 `cc-agora-ops`로, 역할 페르소나는 페르소나 플러그인으로 분리됐다는 점. spawn·presets·디렉토리 구조의 옛 기술은 제거한다.

- [ ] **Step 4: JSON 유효성 + 커밋**

Run: `.venv\Scripts\python.exe -c "import json; json.load(open('plugin/cc-agora-ops/.claude-plugin/plugin.json',encoding='utf-8')); print('ok')"`
Expected: `ok`

```bash
git add plugin/cc-agora-ops/.claude-plugin/plugin.json plugin/cc-agora-ops/README.md plugin/cc-agora/README.md
git commit -m "feat: cc-agora-ops plugin.json + README, cc-agora README 갱신"
```

---

### Task 3: `roles.json` — 역할 → 페르소나 플러그인 매핑

**Files:**
- Modify: `plugin/cc-agora-ops/config/roles.json`
- Modify: `plugin/cc-agora-ops/scripts/role_policy.py`
- Modify: `tests/test_plugin_role_policy.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_role_policy.py`에서 `preset_for`를 쓰는 기존 테스트를 `plugin_for`로 바꾼다. `from role_policy import (...)` 목록의 `preset_for`를 `plugin_for`로, `undefined_role_warning` 관련 테스트는 유지. 신규/수정 테스트:

```python
def test_plugin_for_defined_role():
    roles = load_roles(ROLES_PATH)
    assert plugin_for("coder", roles) == "cc-agora-coder"


def test_plugin_for_undefined_role_is_none():
    roles = load_roles(ROLES_PATH)
    assert plugin_for("phantom", roles) is None


def test_all_seven_roles_map_to_persona_plugins():
    roles = load_roles(ROLES_PATH)
    for role in ("orchestrator", "coder", "reviewer", "tester", "writer", "planner", "general"):
        assert plugin_for(role, roles) == f"cc-agora-{role}"
```

`import` 줄: `from role_policy import (is_defined, load_roles, plugin_for, undefined_role_warning, warn_undefined_role)`.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_role_policy.py -q`
Expected: FAIL — `plugin_for` 미정의.

- [ ] **Step 3: roles.json 교체**

`plugin/cc-agora-ops/config/roles.json`:

```json
{
  "orchestrator": { "plugin": "cc-agora-orchestrator" },
  "coder":        { "plugin": "cc-agora-coder" },
  "reviewer":     { "plugin": "cc-agora-reviewer" },
  "tester":       { "plugin": "cc-agora-tester" },
  "writer":       { "plugin": "cc-agora-writer" },
  "planner":      { "plugin": "cc-agora-planner" },
  "general":      { "plugin": "cc-agora-general" }
}
```

- [ ] **Step 4: role_policy.py의 `preset_for` → `plugin_for`**

`plugin/cc-agora-ops/scripts/role_policy.py`의 `preset_for` 함수를 `plugin_for`로 교체:

```python
def plugin_for(role: str, roles: dict[str, dict[str, str]]) -> str | None:
    """Return the persona plugin name declared for ``role``. ``None`` for
    undefined roles — caller falls back to the general persona plugin."""
    entry = roles.get(role)
    if entry is None:
        return None
    return entry.get("plugin")
```

`undefined_role_warning`의 메시지 본문에서 `{{"{role}": {{"preset":"general"}}}}` 예시를 `{{"{role}": {{"plugin":"cc-agora-general"}}}}`로 바꾼다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_role_policy.py -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add plugin/cc-agora-ops/config/roles.json plugin/cc-agora-ops/scripts/role_policy.py tests/test_plugin_role_policy.py
git commit -m "feat: roles.json — 역할→페르소나 플러그인 매핑"
```

---

### Task 4: spawn 재설계 — thin CLAUDE.md + `.claude/settings.local.json`

`do_spawn`을 재설계한다. 더 이상 preset 본문을 `CLAUDE.md`에 stamp하지 않는다. 생성 산출물: thin `CLAUDE.md`, `.mcp.json`(불변), `run.bat`(불변), 신규 `.claude/settings.local.json`.

**Files:**
- Modify: `plugin/cc-agora-ops/scripts/spawn.py`
- Modify: `tests/test_plugin_spawn.py`

- [ ] **Step 1: 실패하는 테스트로 교체**

`tests/test_plugin_spawn.py`의 산출물 검증 테스트를 새 산출물 기준으로 바꾼다. 핵심 단언:

```python
def test_spawn_creates_thin_claude_md(tmp_path):
    rc = _call(tmp_path, instance_id="Coder1", role="coder",
               description="React 컴포넌트 담당")
    assert rc == 0
    md = (tmp_path / "Coder1" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Coder1" in md and "coder" in md
    # thin — 페르소나 본문(미션 등)을 stamp하지 않는다
    assert "## 미션" not in md
    assert "persona" in md  # 페르소나 스킬 적용 지시


def test_spawn_creates_settings_local_json(tmp_path):
    rc = _call(tmp_path, instance_id="Coder1", role="coder", description="d")
    assert rc == 0
    s = json.loads(
        (tmp_path / "Coder1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert "extraKnownMarketplaces" in s
    assert "agentagora" in s["extraKnownMarketplaces"]
    assert s["enabledPlugins"].get("cc-agora-coder@agentagora") is True


def test_spawn_undefined_role_enables_general_persona(tmp_path):
    rc = _call(tmp_path, instance_id="X1", role="phantom", description="d")
    assert rc == 0
    s = json.loads(
        (tmp_path / "X1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert s["enabledPlugins"].get("cc-agora-general@agentagora") is True
```

`.mcp.json`·`run.bat` 검증 테스트는 유지(이 둘은 불변). `_call` 헬퍼가 `do_spawn`에 넘기는 인자는 Step 3의 새 시그니처에 맞춘다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -q`
Expected: FAIL — 현 `do_spawn`은 preset 본문을 stamp하고 `.claude/settings.local.json`을 안 만든다.

- [ ] **Step 3: spawn.py 재설계**

`plugin/cc-agora-ops/scripts/spawn.py`를 다음과 같이 고친다.

(a) import에서 `preset_for` → `plugin_for`:

```python
from role_policy import is_defined, load_roles, plugin_for, warn_undefined_role
```

(b) `_render_claude_md`를 thin 버전으로 교체:

```python
def _render_thin_claude_md(*, instance_id: str, role: str, description: str) -> str:
    return (
        f"# {instance_id} ({role})\n"
        f"\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n"
        f"\n"
        f"## 페르소나\n"
        f"\n"
        f"본인의 역할 페르소나는 `cc-agora-{role}` 플러그인이 제공하는 `persona` 스킬에 "
        f"있다. 기동 시 그 스킬을 적용해 역할을 수행한다.\n"
        f"\n"
        f"## 통신\n"
        f"\n"
        f"채널 모드 메시징은 `agora-protocol` 스킬을 따른다 — 채널 알림으로 깨어나 "
        f"`agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신한다. "
        f"등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/"
        f"`agora.unregister`를 호출하지 않는다.\n"
    )
```

(c) `.claude/settings.local.json` 렌더러를 추가. 마켓플레이스 소스는 `directory` 타입으로 AgentAgora 저장소 루트를 가리킨다(로컬 개발 기본값). 저장소 루트는 plugin root의 두 단계 상위(`plugin/cc-agora-ops` → `plugin` → repo):

```python
def _render_settings_local(*, persona_plugin: str, marketplace_path: str) -> str:
    settings = {
        "extraKnownMarketplaces": {
            "agentagora": {"source": "directory", "path": marketplace_path}
        },
        "enabledPlugins": {f"{persona_plugin}@agentagora": True},
    }
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
```

> 구현 시 확인: `extraKnownMarketplaces`의 `directory` 소스 하위 키가 `path`가 맞는지 Claude Code settings 스키마(<https://www.schemastore.org/claude-code-settings.json>)로 확정한다. 다른 키명이면 그에 맞춘다.

(d) `do_spawn`에서 preset 결정 로직을 페르소나 플러그인 결정으로 교체:

```python
    defined = is_defined(role, roles)
    persona_plugin = plugin_for(role, roles) if defined else None
    if persona_plugin is None:
        persona_plugin = "cc-agora-general"
    if not defined:
        warn_undefined_role(role, stream=stderr)
```

`--preset` 인자와 그 처리는 제거한다(페르소나가 플러그인으로 결정되므로 preset 개념이 사라짐).

(e) `do_spawn`의 파일 생성 부분을 교체 — preset 파일 읽기를 없애고, thin CLAUDE.md + `.claude/settings.local.json`을 쓴다. `.mcp.json`·`run.bat` 생성은 그대로:

```python
    worker_dir.mkdir(parents=True, exist_ok=True)

    # 1. thin CLAUDE.md
    _write_text(
        worker_dir / "CLAUDE.md",
        _render_thin_claude_md(
            instance_id=instance_id, role=role, description=description),
    )

    # 2. .mcp.json — HTTP 서버 + agora-channel stdio 어댑터 (불변)
    mcp_template = _read_template(plugin_root, "templates", "mcp.json.template")
    _write_text(
        worker_dir / ".mcp.json",
        _render_mcp_json(
            template=mcp_template, server_url=server_url,
            instance_id=instance_id, role=role, description=description),
    )

    # 3. run.bat — 채널 모드 기동 (불변)
    _write_text(worker_dir / "run.bat", _RUN_BAT)

    # 4. .claude/settings.local.json — 워커별 페르소나 플러그인 활성화
    marketplace_path = plugin_root.parent.parent.as_posix()
    _write_text(
        worker_dir / ".claude" / "settings.local.json",
        _render_settings_local(
            persona_plugin=persona_plugin, marketplace_path=marketplace_path),
    )
```

`do_spawn` 시그니처에서 `preset` 파라미터를 제거한다. `_render_claude_md`(구 버전)와 preset 파일 경로 처리 코드는 삭제한다. arg parser에서도 `--preset`을 제거한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add plugin/cc-agora-ops/scripts/spawn.py tests/test_plugin_spawn.py
git commit -m "feat: spawn 재설계 — thin CLAUDE.md + .claude/settings.local.json"
```

---

### Task 5: spawn_team + agora-spawn 슬래시 정합

`spawn_team.py`는 `do_spawn`을 호출하므로 시그니처 변경(`preset` 제거)에 맞춰야 한다. `agora-spawn`·`agora-spawn-team` SKILL.md는 영어화 + 새 산출물 반영.

**Files:**
- Modify: `plugin/cc-agora-ops/scripts/spawn_team.py`
- Modify: `tests/test_plugin_spawn_team.py`
- Modify: `plugin/cc-agora-ops/skills/agora-spawn/SKILL.md`
- Modify: `plugin/cc-agora-ops/skills/agora-spawn-team/SKILL.md`

- [ ] **Step 1: spawn_team.py에서 do_spawn 호출 정합**

`spawn_team.py`가 `do_spawn`에 `preset=`을 넘기던 부분을 제거한다(시그니처에서 `preset`이 사라졌으므로). manifest 항목의 `preset?` 필드는 무시하거나, manifest 스키마에서 제거한다 — manifest 검증에서 `preset`을 optional로 받되 `do_spawn` 호출 시 넘기지 않는다.

- [ ] **Step 2: spawn_team 테스트 갱신 + 통과 확인**

`tests/test_plugin_spawn_team.py`에서 `do_spawn` 호출 산출물을 검증하는 부분이 있으면 새 산출물(thin CLAUDE.md + settings.local.json)에 맞춘다. `_validate_manifest` 순수 검증 테스트는 그대로.

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn_team.py -q`
Expected: PASS

- [ ] **Step 3: agora-spawn SKILL.md 영어화 + 새 산출물 반영**

`plugin/cc-agora-ops/skills/agora-spawn/SKILL.md`를 영어로 옮기고 `disable-model-invocation: true` + `argument-hint`를 frontmatter에 넣는다:

```markdown
---
description: Spawn one cc-agora worker — creates a thin CLAUDE.md, .mcp.json, run.bat, and .claude/settings.local.json that enables the worker's persona plugin.
argument-hint: <id> <role> "<description>" [--dir --force --server-url]
disable-model-invocation: true
---
```

본문은 새 산출물(thin CLAUDE.md + `.claude/settings.local.json`)을 기술한다. `--preset` 설명은 삭제한다(제거됨).

- [ ] **Step 4: agora-spawn-team SKILL.md 영어화**

`plugin/cc-agora-ops/skills/agora-spawn-team/SKILL.md`를 영어로 옮기고 frontmatter에 `disable-model-invocation: true` + `argument-hint`를 넣는다:

```markdown
---
description: Spawn a whole cc-agora worker team from a manifest JSON — batch directory setup with optional Windows Terminal auto-launch.
argument-hint: <manifest.json> [--dir --launch=off/manual/auto --force --server-url]
disable-model-invocation: true
---
```

- [ ] **Step 5: 커밋**

```bash
git add plugin/cc-agora-ops/scripts/spawn_team.py tests/test_plugin_spawn_team.py plugin/cc-agora-ops/skills/agora-spawn/SKILL.md plugin/cc-agora-ops/skills/agora-spawn-team/SKILL.md
git commit -m "feat: spawn_team 정합 + agora-spawn 슬래시 영어화"
```

---

### Task 6: 로컬 서버 런처 — `run-server.bat` + `.mcp.json.example`

**Files:**
- Create: `plugin/cc-agora-ops/templates/run-server.bat`
- Create: `plugin/cc-agora-ops/templates/.mcp.json.example`

- [ ] **Step 1: run-server.bat 생성 (CRLF + ASCII)**

`plugin/cc-agora-ops/templates/run-server.bat`를 아래 내용으로, **CRLF 줄바꿈 + ASCII**로 생성한다(한글 `REM`은 cmd.exe 파서를 깨뜨림):

```bat
@echo off
REM AgentAgora server launcher.
REM Run by double-clicking, or from a terminal: run-server.bat
REM Stop the server with Ctrl+C in the spawned window.
setlocal
cd /d "%~dp0"
REM --dir points to the PARENT of .agentagora (the server appends ".agentagora").
REM --no-tls: plain HTTP for localhost testing.
where agent-agora >nul 2>nul
if %ERRORLEVEL%==0 (
    agent-agora --dir "%~dp0." --port 8420 --no-tls
) else (
    py -3.13 -m agent_agora --dir "%~dp0." --port 8420 --no-tls
)
echo.
echo Server stopped. Press any key to close.
pause >nul
endlocal
```

CRLF로 쓰는 법(PowerShell): 내용을 LF로 만든 뒤 `(Get-Content -Raw run-server.bat) -replace "`n","`r`n" | Set-Content -NoNewline run-server.bat`, 또는 처음부터 CRLF로 작성. 검증: `python -c "b=open('plugin/cc-agora-ops/templates/run-server.bat','rb').read(); assert b'\r\n' in b; assert all(c<128 for c in b); print('crlf+ascii ok')"`.

- [ ] **Step 2: .mcp.json.example 생성**

`plugin/cc-agora-ops/templates/.mcp.json.example`:

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "http://127.0.0.1:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "Operator1",
        "X-Agora-Role": "orchestrator",
        "X-Agora-Description": "operator control session"
      }
    }
  }
}
```

- [ ] **Step 3: 검증 + 커밋**

Run: `.venv\Scripts\python.exe -c "import json; json.load(open('plugin/cc-agora-ops/templates/.mcp.json.example',encoding='utf-8')); b=open('plugin/cc-agora-ops/templates/run-server.bat','rb').read(); assert b'\r\n' in b and all(c<128 for c in b); print('ok')"`
Expected: `ok`

```bash
git add plugin/cc-agora-ops/templates/run-server.bat plugin/cc-agora-ops/templates/.mcp.json.example
git commit -m "feat: cc-agora-ops — 로컬 서버 런처 + .mcp.json 예시"
```

---

### Task 7: `agora-comm-matrix` 스킬 + `comm_matrix.py`

운영자가 토큰 게이트 `/admin/comm-matrix` 엔드포인트로 comm-matrix를 교체·조회하는 스킬.

**Files:**
- Create: `plugin/cc-agora-ops/scripts/comm_matrix.py`
- Create: `plugin/cc-agora-ops/skills/agora-comm-matrix/SKILL.md`
- Create: `tests/test_plugin_comm_matrix.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_comm_matrix.py`:

```python
"""Unit tests for plugin/cc-agora-ops/scripts/comm_matrix.py."""
from __future__ import annotations

import pytest

from comm_matrix import build_request


def test_build_request_get():
    method, url, headers, body = build_request(
        action="get", server_url="http://127.0.0.1:8420", token="t0ken", csv=None)
    assert method == "GET"
    assert url == "http://127.0.0.1:8420/admin/comm-matrix"
    assert headers["Authorization"] == "Bearer t0ken"
    assert body is None


def test_build_request_post_includes_csv_body():
    method, url, headers, body = build_request(
        action="post", server_url="http://127.0.0.1:8420", token="t0ken",
        csv="A,B\n0,1\n1,0")
    assert method == "POST"
    assert body == "A,B\n0,1\n1,0"
    assert headers["Authorization"] == "Bearer t0ken"


def test_build_request_missing_token_raises():
    with pytest.raises(ValueError, match="AGORA_ADMIN_TOKEN"):
        build_request(action="get", server_url="http://127.0.0.1:8420",
                      token=None, csv=None)


def test_build_request_post_without_csv_raises():
    with pytest.raises(ValueError, match="csv"):
        build_request(action="post", server_url="http://127.0.0.1:8420",
                      token="t0ken", csv=None)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_comm_matrix.py -q`
Expected: FAIL — `comm_matrix` 모듈 없음.

- [ ] **Step 3: comm_matrix.py 작성**

`plugin/cc-agora-ops/scripts/comm_matrix.py`:

```python
"""/agora-comm-matrix implementation — operator comm-matrix admin client.

Calls the token-gated /admin/comm-matrix endpoint (comm-matrix governance spec).
``build_request`` is pure (testable); ``main`` performs the HTTP call.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

DEFAULT_SERVER_URL = "http://127.0.0.1:8420"


def build_request(
    *, action: str, server_url: str, token: str | None, csv: str | None,
) -> tuple[str, str, dict[str, str], str | None]:
    """Return (method, url, headers, body) for the admin call.

    action='get' → GET (no body). action='post' → POST with the CSV body.
    Raises ValueError when the token is missing or a POST has no CSV.
    """
    if not token:
        raise ValueError(
            "AGORA_ADMIN_TOKEN is not set — the server must run with that env var "
            "and the operator must export the same token.")
    url = server_url.rstrip("/") + "/admin/comm-matrix"
    headers = {"Authorization": f"Bearer {token}"}
    if action == "get":
        return "GET", url, headers, None
    if action == "post":
        if csv is None:
            raise ValueError("post action requires a csv file argument")
        return "POST", url, headers, csv
    raise ValueError(f"unknown action: {action!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agora-comm-matrix")
    p.add_argument("csv_path", nargs="?", default=None,
                   help="CSV file to POST. Omit to GET the current matrix.")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    args = p.parse_args(argv)

    token = os.environ.get("AGORA_ADMIN_TOKEN")
    action = "post" if args.csv_path else "get"
    csv = None
    if action == "post":
        csv = open(args.csv_path, encoding="utf-8").read()
    try:
        method, url, headers, body = build_request(
            action=action, server_url=args.server_url, token=token, csv=csv)
    except ValueError as e:
        print(f"[cc-agora-ops] {e}", file=sys.stderr)
        return 1

    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            print(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 401:
            print("[cc-agora-ops] 401 Unauthorized — AGORA_ADMIN_TOKEN이 서버 토큰과 "
                  "일치하지 않습니다.", file=sys.stderr)
        elif e.code == 400:
            print(f"[cc-agora-ops] 400 — CSV 오류: {detail}", file=sys.stderr)
        else:
            print(f"[cc-agora-ops] HTTP {e.code}: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_comm_matrix.py -q`
Expected: PASS

- [ ] **Step 5: agora-comm-matrix SKILL.md 작성**

`plugin/cc-agora-ops/skills/agora-comm-matrix/SKILL.md` (영어, `disable-model-invocation: true`):

```markdown
---
description: Manage the AgentAgora communication matrix via the token-gated /admin/comm-matrix endpoint — push a new CSV or read the current matrix.
argument-hint: [<csv-path>] [--server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-comm-matrix

Manage the communication matrix on a running AgentAgora server through the
operator-only `/admin/comm-matrix` endpoint.

## Arguments

- `<csv-path>` (optional) — a comm-matrix CSV file to POST (replaces the
  in-memory matrix without a restart). Omit it to GET the current matrix.
- `--server-url` (optional) — server base URL. Default `http://127.0.0.1:8420`.

## Behavior

1. The server must run with the `AGORA_ADMIN_TOKEN` environment variable set.
   Export the same token in this session before invoking.
2. Run `python <plugin-root>/scripts/comm_matrix.py $ARGUMENTS` via the Bash tool.
3. The script sends `Authorization: Bearer <token>`. With a CSV path it POSTs;
   without one it GETs.
4. Print the server response. On 401 (token mismatch) or 400 (bad CSV) the
   script reports a Korean diagnostic.
```

- [ ] **Step 6: 전체 스위트 회귀 + 커밋**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

```bash
git add plugin/cc-agora-ops/scripts/comm_matrix.py plugin/cc-agora-ops/skills/agora-comm-matrix/SKILL.md tests/test_plugin_comm_matrix.py
git commit -m "feat: agora-comm-matrix 스킬 + comm_matrix.py"
```

---

## 완료 기준

- 운영자 콘텐츠가 `plugin/cc-agora-ops/`에 있고 `cc-agora`에는 통신 코어만 남는다.
- spawn이 thin CLAUDE.md + `.claude/settings.local.json`(페르소나 플러그인 활성화)을 만든다.
- `roles.json`이 역할→페르소나 플러그인 이름을 매핑한다.
- `run-server.bat`(CRLF+ASCII)·`.mcp.json.example`·`agora-comm-matrix`가 존재한다.
- 전체 테스트 스위트 통과.

## 비고

페르소나 플러그인(`cc-agora-coder` 등)은 Plan 3에서 만든다. 이 플랜의 spawn은 페르소나 플러그인 *이름 문자열*만 `settings.local.json`에 쓰므로, 페르소나 플러그인이 아직 없어도 이 플랜은 독립적으로 머지·테스트된다(워커를 실제 기동하면 Plan 3 머지 후 정상 동작).
