# agora-design-worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cc-agora-ops`에 `agora-design-worker` 스킬을 추가한다 — 운영자와 대화해 커스텀 페르소나를 작성하고 워커 디렉토리를 스캐폴딩한다. 7개 사전 정의 페르소나에 매이지 않는다.

**Architecture:** `spawn.py`의 `do_spawn`에 `persona_body` 인자를 더해 "커스텀 모드"를 만든다 — `roles.json` 조회를 건너뛰고 페르소나를 `.claude/CLAUDE.md`에 쓰며 `cc-agora`만 활성화하고, 실행 스크립트는 쓰지 않는다(`agora-run-script` 담당). `agora-design-worker` SKILL.md는 페르소나 대화 → `spawn.py --persona-file` 호출 → `agora-run-script` 호출 순서를 기술한다. 기존 비커스텀 경로는 불변.

**Tech Stack:** Python 3.13, pytest, Markdown(SKILL.md). 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 진단 무시(pytest 정답).

spec: `docs/superpowers/specs/2026-05-18-operator-onboarding-skills-design.md` §3.

이 플랜은 3개 중 2번 — Plan 1(`agora-run-script`)을 호출하므로 그 다음에 구현한다. Plan 3(`agora-setup`)이 이 플랜을 호출한다.

대상 파일: `plugin/cc-agora-ops/scripts/spawn.py`는 `do_spawn`(워커 디렉토리 4파일 생성) + CLI 진입점. `tests/test_plugin_spawn.py`는 `do_spawn`을 `target_dir=tmp_path`로 직접 호출해 검증하며, 헬퍼 `_call(tmp_path, **overrides)`가 `kwargs.update(overrides)`로 인자를 덮어쓴다.

---

### Task 1: `spawn.py` 커스텀 모드 — `persona_body`

**Files:**
- Modify: `plugin/cc-agora-ops/scripts/spawn.py`
- Test: `tests/test_plugin_spawn.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_spawn.py` 끝에 추가한다. (`do_spawn`·`DEFAULT_SERVER_URL`·헬퍼 `_call`은 파일에 이미 있다.)

```python
_PERSONA = "# DB Migrator persona\n\n## Mission\n\nMigrate schemas safely.\n"


def test_spawn_custom_mode_writes_claude_persona(tmp_path):
    rc = _call(tmp_path, instance_id="Db1", role="db-migrator",
               persona_body=_PERSONA)
    assert rc == 0
    persona = (tmp_path / "Db1" / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert persona == _PERSONA


def test_spawn_custom_mode_enables_cc_agora_not_persona_plugin(tmp_path):
    rc = _call(tmp_path, instance_id="Db1", role="db-migrator",
               persona_body=_PERSONA)
    assert rc == 0
    s = json.loads(
        (tmp_path / "Db1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert s["enabledPlugins"].get("cc-agora@agentagora") is True
    # 페르소나 플러그인(cc-agora-<role>)은 켜지 않는다
    assert not any(k.startswith("cc-agora-") for k in s["enabledPlugins"])


def test_spawn_custom_mode_writes_no_run_script(tmp_path):
    rc = _call(tmp_path, instance_id="Db1", role="db-migrator",
               persona_body=_PERSONA)
    assert rc == 0
    assert not (tmp_path / "Db1" / "run.bat").exists()


def test_spawn_custom_mode_root_claude_points_to_persona(tmp_path):
    rc = _call(tmp_path, instance_id="Db1", role="db-migrator",
               description="DB 마이그레이션 담당", persona_body=_PERSONA)
    assert rc == 0
    md = (tmp_path / "Db1" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Db1" in md
    assert ".claude/CLAUDE.md" in md


def test_spawn_custom_mode_still_writes_mcp_json(tmp_path):
    rc = _call(tmp_path, instance_id="Db1", role="db-migrator",
               persona_body=_PERSONA)
    assert rc == 0
    mcp = json.loads((tmp_path / "Db1" / ".mcp.json").read_text(encoding="utf-8"))
    assert set(mcp["mcpServers"]) == {"agentagora", "agora-channel"}
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Role"] == "db-migrator"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -k custom_mode -v`
Expected: 5개 신규 테스트 모두 FAIL — `do_spawn`이 `persona_body` 인자를 받지 않아 `TypeError: unexpected keyword argument 'persona_body'`.

- [ ] **Step 3: `_render_custom_claude_md` 추가**

`spawn.py`에서 기존 `_render_thin_claude_md` 함수 바로 아래에 추가한다:

```python
def _render_custom_claude_md(*, instance_id: str, role: str, description: str) -> str:
    return (
        f"# {instance_id} ({role})\n"
        f"\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n"
        f"\n"
        f"## 페르소나\n"
        f"\n"
        f"역할 페르소나는 `.claude/CLAUDE.md`에 있다 — Claude Code가 프로젝트 "
        f"메모리로 자동 로드한다.\n"
        f"\n"
        f"## 통신\n"
        f"\n"
        f"채널 모드 메시징은 `agora-protocol` 스킬을 따른다 — 채널 알림으로 깨어나 "
        f"`agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신한다. "
        f"등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/"
        f"`agora.unregister`를 호출하지 않는다.\n"
    )
```

- [ ] **Step 4: `do_spawn`을 커스텀 모드 지원으로 교체**

`spawn.py`의 `do_spawn` 함수 전체를 아래로 교체한다:

```python
def do_spawn(
    *,
    instance_id: str,
    role: str,
    description: str,
    target_dir: Path,
    force: bool,
    server_url: str,
    plugin_root: Path,
    persona_body: str | None = None,
    stderr=sys.stderr,
    stdout=sys.stdout,
    env: dict[str, str] | None = None,
) -> int:
    """채널 모드 워커 디렉토리를 ``target_dir/<instance_id>/``에 만든다.

    ``persona_body``가 주어지면 커스텀 모드 — roles.json 조회를 건너뛰고
    페르소나를 ``.claude/CLAUDE.md``에 쓰며 ``cc-agora``만 활성화한다. 실행
    스크립트는 쓰지 않는다(agora-run-script 담당).

    0=성공, 1=실패. 실패는 한국어로 stderr에 보고한다.
    """
    _ = env  # 향후 확장·테스트 패리티용
    custom = persona_body is not None

    if custom:
        persona_plugin = "cc-agora"
    else:
        roles = load_roles(plugin_root / "config" / "roles.json")
        defined = is_defined(role, roles)
        persona_plugin = plugin_for(role, roles) if defined else None
        if persona_plugin is None:
            persona_plugin = "cc-agora-general"
        if not defined:
            warn_undefined_role(role, stream=stderr)

    worker_dir = target_dir / instance_id
    if worker_dir.exists() and not force:
        print(
            f"[cc-agora] '{instance_id}/' 디렉토리가 이미 존재합니다. "
            f"--force로 덮어쓰기 가능.",
            file=stderr,
        )
        return 1
    worker_dir.mkdir(parents=True, exist_ok=True)

    # 1. CLAUDE.md (루트 thin)
    if custom:
        _write_text(
            worker_dir / "CLAUDE.md",
            _render_custom_claude_md(
                instance_id=instance_id, role=role, description=description),
        )
        # 1b. .claude/CLAUDE.md — 커스텀 페르소나 (Claude Code가 자동 로드)
        _write_text(worker_dir / ".claude" / "CLAUDE.md", persona_body)
    else:
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

    # 3. run.bat — 비커스텀 모드만. 커스텀 모드 실행 스크립트는 agora-run-script.
    if not custom:
        _write_text(worker_dir / "run.bat", _RUN_BAT)

    # 4. .claude/settings.local.json — 페르소나 플러그인(커스텀이면 cc-agora) 활성화
    marketplace_path = plugin_root.parent.parent.as_posix()
    _write_text(
        worker_dir / ".claude" / "settings.local.json",
        _render_settings_local(
            persona_plugin=persona_plugin, marketplace_path=marketplace_path),
    )

    if custom:
        print(
            f"[cc-agora] '{instance_id}/' 생성 완료 "
            f"(role={role}, 커스텀 페르소나, 채널 모드). "
            f"실행 스크립트는 agora-run-script로 생성하라.",
            file=stdout,
        )
    else:
        print(
            f"[cc-agora] '{instance_id}/' 생성 완료 "
            f"(role={role}, persona={persona_plugin}, 채널 모드). "
            f"시작: cd {instance_id} && run.bat",
            file=stdout,
        )
    return 0
```

- [ ] **Step 5: 커스텀 모드 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -k custom_mode -v`
Expected: 5개 신규 테스트 모두 PASS.

- [ ] **Step 6: 비커스텀 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py tests/test_plugin_spawn_team.py -v`
Expected: 기존 테스트 전부 PASS — `persona_body` 기본값 `None`이라 비커스텀 경로(`run.bat` 기록·페르소나 플러그인 활성화)는 불변. `spawn_team.py`도 `persona_body`를 넘기지 않아 영향 없음.

- [ ] **Step 7: 커밋**

```bash
git add plugin/cc-agora-ops/scripts/spawn.py tests/test_plugin_spawn.py
git commit -m "feat: spawn.py — persona_body 커스텀 모드"
```

---

### Task 2: `spawn.py` `--persona-file` CLI 인자

**Files:**
- Modify: `plugin/cc-agora-ops/scripts/spawn.py`
- Test: `tests/test_plugin_spawn.py`

`agora-design-worker` 스킬은 페르소나 본문을 임시 파일에 쓴 뒤 `spawn.py`를 CLI로 호출한다. 멀티라인 페르소나를 CLI 인자로 직접 넘기긴 어려우므로 `--persona-file` 경로 인자를 추가한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_spawn.py`의 import 줄을 `from spawn import DEFAULT_SERVER_URL, do_spawn`에서 `from spawn import DEFAULT_SERVER_URL, do_spawn, main`으로 바꾸고, 파일 끝에 추가한다:

```python
def test_main_persona_file_triggers_custom_mode(tmp_path, monkeypatch):
    pf = tmp_path / "persona.md"
    pf.write_text("# Custom\n\n## Mission\n\nDo the thing.\n", encoding="utf-8")
    monkeypatch.setenv("AGORA_HOME", str(tmp_path))
    rc = main(["Cli1", "custom-role", "desc", "--persona-file", str(pf)])
    assert rc == 0
    persona = (tmp_path / "Cli1" / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert persona == "# Custom\n\n## Mission\n\nDo the thing.\n"
    assert not (tmp_path / "Cli1" / "run.bat").exists()


def test_main_without_persona_file_stays_non_custom(tmp_path, monkeypatch):
    monkeypatch.setenv("AGORA_HOME", str(tmp_path))
    rc = main(["Cli2", "coder", "desc"])
    assert rc == 0
    assert (tmp_path / "Cli2" / "run.bat").is_file()
    assert not (tmp_path / "Cli2" / ".claude" / "CLAUDE.md").exists()
```

`_resolve_target_dir`는 `--dir` 미지정 시 `AGORA_HOME` 환경변수를 부모 디렉토리로 쓴다 — `monkeypatch.setenv`로 `tmp_path`를 지정한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -k persona_file -v`
Expected: `test_main_persona_file_triggers_custom_mode`가 FAIL — `--persona-file`가 미정의 인자라 argparse가 `SystemExit`. (`test_main_without_persona_file_stays_non_custom`은 현 동작으로도 통과할 수 있다.)

- [ ] **Step 3: 인자 파서에 `--persona-file` 추가**

`spawn.py`의 `_build_arg_parser` 함수에서 `--server-url` 인자 정의 바로 뒤(`return p` 직전)에 추가한다:

```python
    p.add_argument(
        "--persona-file",
        dest="persona_file",
        default=None,
        help="Path to a file holding the custom persona body. When given, "
             "spawn runs in custom mode: writes .claude/CLAUDE.md, enables "
             "cc-agora, and writes no run script.",
    )
```

- [ ] **Step 4: `main`이 `--persona-file`을 읽어 `do_spawn`에 전달**

`spawn.py`의 `main` 함수 전체를 아래로 교체한다:

```python
def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    persona_body = None
    if args.persona_file is not None:
        persona_body = Path(args.persona_file).read_text(encoding="utf-8")
    return do_spawn(
        instance_id=args.id,
        role=args.role,
        description=args.description,
        target_dir=_resolve_target_dir(
            dir_override=args.dir_override,
            cwd=Path.cwd(),
            env=os.environ.copy(),
        ),
        force=args.force,
        server_url=args.server_url,
        plugin_root=_plugin_root(),
        persona_body=persona_body,
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -k persona_file -v`
Expected: 두 테스트 PASS.

- [ ] **Step 6: 커밋**

```bash
git add plugin/cc-agora-ops/scripts/spawn.py tests/test_plugin_spawn.py
git commit -m "feat: spawn.py — --persona-file CLI 인자"
```

---

### Task 3: `cc-agora-ops` → `cc-agora` 플러그인 의존성

**Files:**
- Modify: `plugin/cc-agora-ops/.claude-plugin/plugin.json`
- Test: `tests/test_plugin_marketplace.py`

`agora-design-worker`(`cc-agora-ops`)가 `agora-run-script`(`cc-agora`)를 호출할 수 있도록 `cc-agora-ops`가 `cc-agora`에 의존하게 한다. 의존 선언 시 `cc-agora-ops` 활성화가 `cc-agora`를 함께 켠다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_marketplace.py` 끝에 추가한다 (`_load`·`REPO`는 파일에 이미 있다):

```python
def test_cc_agora_ops_depends_on_cc_agora():
    pj = _load(REPO / "plugin" / "cc-agora-ops" / ".claude-plugin" / "plugin.json")
    assert pj["dependencies"] == ["cc-agora"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_marketplace.py -k ops_depends -v`
Expected: FAIL — `plugin.json`에 `dependencies` 키가 없어 `KeyError`.

- [ ] **Step 3: `plugin.json`에 `dependencies` 추가**

`plugin/cc-agora-ops/.claude-plugin/plugin.json` 전체를 아래로 교체한다:

```json
{
  "name": "cc-agora-ops",
  "description": "AgentAgora operator tooling — spawn workers, spawn teams from a manifest, manage the communication matrix, and launch a local server.",
  "version": "0.1.0",
  "dependencies": ["cc-agora"]
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_marketplace.py -v`
Expected: 신규 테스트 포함 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add plugin/cc-agora-ops/.claude-plugin/plugin.json tests/test_plugin_marketplace.py
git commit -m "feat: cc-agora-ops — cc-agora 의존성 선언"
```

---

### Task 4: `agora-design-worker` 스킬 + README

**Files:**
- Create: `tests/test_plugin_design_worker.py`
- Create: `plugin/cc-agora-ops/skills/agora-design-worker/SKILL.md`
- Modify: `plugin/cc-agora-ops/README.md`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_design_worker.py`를 새로 만든다:

```python
"""Validates the cc-agora-ops agora-design-worker skill."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = (REPO / "plugin" / "cc-agora-ops" / "skills"
         / "agora-design-worker" / "SKILL.md")


def test_design_worker_skill_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "description:" in text
    assert "disable-model-invocation: true" in text


def test_design_worker_skill_references_spawn_and_run_script():
    text = SKILL.read_text(encoding="utf-8")
    assert "--persona-file" in text
    assert "spawn.py" in text
    assert "agora-run-script" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_design_worker.py -v`
Expected: 두 테스트 FAIL — `SKILL.md`가 없어 `FileNotFoundError`.

- [ ] **Step 3: SKILL.md 작성**

`plugin/cc-agora-ops/skills/agora-design-worker/SKILL.md`를 만든다 (frontmatter·본문 영어 — 프로젝트 규약):

````markdown
---
description: Co-author a custom worker persona with the operator and scaffold the worker directory — for roles not covered by the seven preset persona plugins.
argument-hint: [<id>] [--dir --force --server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-design-worker

Set up one channel-mode AgentAgora worker with a **custom persona** authored
together with the operator. Unlike `/cc-agora-ops:agora-spawn` — which enables one
of the seven preset persona plugins — this skill builds a persona from a short
dialogue and stamps it into the worker directory's `.claude/CLAUDE.md`.

## Arguments

- `<id>` (optional) — worker instance_id (alphanumeric, hyphens, underscores;
  1–32 chars). If omitted, ask for it as the first dialogue question.
- `--dir=<path>` (optional) — explicit parent directory for the worker folder.
- `--force` (optional) — overwrite managed files inside an existing `<id>/`.
- `--server-url=<url>` (optional) — MCP server URL. Default
  `http://127.0.0.1:8420/mcp`.

## Behavior

### 1. Persona dialogue

Ask the operator the following **one question at a time** — do not batch them:

1. **Worker id** — only if `<id>` was not passed as an argument.
2. **Mission** — one or two sentences: what does this worker turn its inputs
   into? Its core responsibility.
3. **Role label** — a short single-word role for the `.mcp.json` headers
   (e.g. `db-migrator`).
4. **Working style & role-specific knowledge** — concrete operating rules for
   this role.
5. **Handoff specifics** — does this worker forward out-of-domain work? Is there
   a default delegate?

### 2. Compose the persona

Build the persona body with this exact structure. The **Mission** and
**Role-specific knowledge** sections come from the dialogue; the **Response
conventions** and **Finding other members** sections are fixed boilerplate —
stamp them verbatim:

```markdown
# <role label> persona

## Mission

<dialogue answer 2, with the handoff answer from 5 folded in>

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. When a task is better
suited to another member, use `/invoke <other> "<task>"` to forward it. Sending
the originator a one-line ack ("delegated to X") is recommended — not mandatory.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain
your inbox with `agora.flush`. See the `agora-protocol` skill for full
channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as
observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type`
enum has four values: `task | reply | closing | ack`. Use `type=reply` for task
responses, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

<dialogue answer 4, as a bullet list>

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or
`agora.find`. Do not hard-code instance mappings in the persona.
```

### 3. Confirm

Show the operator the fully composed persona and ask for confirmation. Revise on
request. Do not scaffold until the operator approves.

### 4. Scaffold the worker directory

1. Write the approved persona body to a temporary file in the current working
   directory, e.g. `.agora-design-worker-persona.tmp`.
2. The plugin root is `<repo>/plugin/cc-agora-ops/`. Run via the Bash tool:
   `python <plugin-root>/scripts/spawn.py <id> <role-label> "<responsibility>" --persona-file <tmpfile>` plus any of `--dir`, `--force`, `--server-url` the
   operator passed. `<responsibility>` is a single sentence drawn from the
   Mission. Custom mode creates `CLAUDE.md`, `.claude/CLAUDE.md` (the persona),
   `.mcp.json`, and `.claude/settings.local.json` (enables `cc-agora`); it writes
   no run script.
3. Delete the temporary file.
4. Invoke the `agora-run-script` skill with the worker directory as its `<dir>`
   argument to write the channel-mode launch script (`run.ps1`/`run.sh`).

### 5. Report

Forward `spawn.py` stdout/stderr to the operator as-is, then tell them the worker
starts by running the launch script from inside the worker directory.

## Example

```
/cc-agora-ops:agora-design-worker Db1
```

Walks the operator through the persona dialogue, then creates `<parent>/Db1/`
with a custom persona in `.claude/CLAUDE.md` and a channel-mode launch script.
````

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_design_worker.py -v`
Expected: 두 테스트 PASS.

- [ ] **Step 5: cc-agora-ops README에 슬래시 행 추가**

`plugin/cc-agora-ops/README.md`의 "슬래시 명령" 표에서 `/cc-agora-ops:agora-spawn` 행 바로 아래에 행을 추가한다:

```markdown
| `/cc-agora-ops:agora-design-worker` | `[<id>] [--dir --force --server-url]` | 운영자와 대화해 커스텀 페르소나를 작성하고 워커를 스캐폴딩 — 7개 사전 정의에 없는 역할용. 페르소나는 `.claude/CLAUDE.md`에. |
```

- [ ] **Step 6: 전체 스위트 회귀 확인 + 커밋**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

```bash
git add tests/test_plugin_design_worker.py plugin/cc-agora-ops/skills/agora-design-worker/SKILL.md plugin/cc-agora-ops/README.md
git commit -m "feat: cc-agora-ops — agora-design-worker 스킬"
```

---

## 완료 기준

- `do_spawn(persona_body=...)` 커스텀 모드 — `.claude/CLAUDE.md`에 페르소나, `settings.local.json`이 `cc-agora`만 활성화, 실행 스크립트 미기록. 비커스텀 모드 회귀 불변.
- `spawn.py --persona-file <path>` CLI가 커스텀 모드를 트리거한다.
- `cc-agora-ops` `plugin.json`이 `cc-agora`를 의존 선언한다.
- `agora-design-worker` SKILL.md가 페르소나 대화 → `spawn.py --persona-file` → `agora-run-script` 순서를 기술하고, frontmatter가 유효하다.
- `cc-agora-ops` README에 슬래시 행이 있다.
- 전체 테스트 스위트 통과.
