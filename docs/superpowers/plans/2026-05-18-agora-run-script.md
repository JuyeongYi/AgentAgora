# agora-run-script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cc-agora` 플러그인에 `agora-run-script` 스킬을 추가한다 — 대상 폴더에 호스트 OS에 맞는 채널 모드 실행 스크립트(`run.ps1`/`run.sh`)를 생성한다.

**Architecture:** 백킹 스크립트 없는 순수 SKILL.md 스킬(`agora-make-comm-matrix`와 동일 패턴). 스킬 본문이 OS를 감지해 채널 모드 런처 한 줄을 담은 파일을 쓰는 절차를 기술한다. 테스트는 SKILL.md의 frontmatter 유효성과 런처 커맨드 문자열을 검증한다.

**Tech Stack:** Markdown(SKILL.md), pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell.

spec: `docs/superpowers/specs/2026-05-18-operator-onboarding-skills-design.md` §2.

이 플랜은 3개 중 1번 — Plan 2(`agora-design-worker`)가 이 스킬을 호출한다. 단독 머지 가능.

---

### Task 1: `agora-run-script` 스킬

**Files:**
- Create: `tests/test_plugin_run_script.py`
- Create: `plugin/cc-agora/skills/agora-run-script/SKILL.md`
- Modify: `plugin/cc-agora/README.md`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_run_script.py`를 새로 만든다:

```python
"""Validates the cc-agora agora-run-script skill."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugin" / "cc-agora" / "skills" / "agora-run-script" / "SKILL.md"


def test_run_script_skill_exists_with_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "description:" in text
    assert "disable-model-invocation: true" in text


def test_run_script_skill_specifies_channel_launcher():
    text = SKILL.read_text(encoding="utf-8")
    assert "--dangerously-load-development-channels server:agora-channel" in text
    assert "run.ps1" in text
    assert "run.sh" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_run_script.py -v`
Expected: 두 테스트 모두 FAIL — `SKILL.md` 파일이 아직 없어 `read_text`가 `FileNotFoundError`.

- [ ] **Step 3: SKILL.md 작성**

`plugin/cc-agora/skills/agora-run-script/SKILL.md`를 만든다 (frontmatter·본문 영어 — 프로젝트 규약):

````markdown
---
description: Generate the OS-appropriate channel-mode run script for a worker directory — run.ps1 on Windows, run.sh on Unix.
argument-hint: [<dir>]
disable-model-invocation: true
---

# /cc-agora:agora-run-script

Write the channel-mode launch script for an AgentAgora worker directory. A worker
is started by opening an interactive Claude Code session with the worker
directory as the working directory; the launch script does exactly that. Because
the script is run from inside the worker directory, the working directory is
correct by construction and the worker picks up its own `.mcp.json`, `CLAUDE.md`,
and `.claude/`.

## Arguments

- `<dir>` (optional) — directory to write the script into. Default: the current
  working directory.

## Behavior

1. Determine the host OS.

2. Write the run script into `<dir>`, UTF-8 with LF newlines:

   - **Windows** → `<dir>/run.ps1`:

     ```
     # AgentAgora channel-mode worker launcher. Run from inside this directory.
     claude --dangerously-load-development-channels server:agora-channel @args
     ```

   - **Unix (macOS/Linux)** → `<dir>/run.sh`:

     ```
     #!/usr/bin/env bash
     # AgentAgora channel-mode worker launcher. Run from inside this directory.
     claude --dangerously-load-development-channels server:agora-channel "$@"
     ```

3. On Unix, tell the operator to mark it executable: `chmod +x <dir>/run.sh`.

4. Report the written path. The worker is started by running this script from
   inside `<dir>` — `cd <dir>` then `./run.ps1` (Windows; if PowerShell execution
   policy blocks it, `powershell -ExecutionPolicy Bypass -File .\run.ps1`) or
   `./run.sh` (Unix).

## Notes

- `agora-channel` is a self-made development channel not on the official
  allowlist, so the `--dangerously-load-development-channels` flag is required.
- This skill writes only the launch script. The worker directory itself
  (`.mcp.json`, `CLAUDE.md`, `.claude/`) is created by `/cc-agora-ops:agora-spawn`
  or `/cc-agora-ops:agora-design-worker`.
````

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_run_script.py -v`
Expected: 두 테스트 모두 PASS.

- [ ] **Step 5: cc-agora README에 슬래시 행 추가**

`plugin/cc-agora/README.md`의 "슬래시 명령" 표(현재 4행: invoke·broadcast·agora-target·agora-close) 끝에 행을 추가한다:

```markdown
| `/cc-agora:agora-run-script` | `[<dir>]` | 워커 디렉토리에 OS에 맞는 채널 모드 실행 스크립트(`run.ps1`/`run.sh`)를 생성. |
```

- [ ] **Step 6: 전체 스위트 회귀 확인 + 커밋**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS — 새 스킬 추가는 기존 동작에 영향 없음.

```bash
git add tests/test_plugin_run_script.py plugin/cc-agora/skills/agora-run-script/SKILL.md plugin/cc-agora/README.md
git commit -m "feat: cc-agora — agora-run-script 스킬"
```

---

## 완료 기준

- `plugin/cc-agora/skills/agora-run-script/SKILL.md`가 존재하고 frontmatter가 유효하다(`description`, `argument-hint`, `disable-model-invocation: true`).
- SKILL.md가 채널 모드 런처 커맨드와 `run.ps1`/`run.sh` OS 분기를 기술한다.
- `cc-agora` README의 슬래시 표에 `agora-run-script` 행이 있다.
- 전체 테스트 스위트 통과.
