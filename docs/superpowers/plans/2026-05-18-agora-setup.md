# agora-setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cc-agora-ops`에 `agora-setup` 스킬을 추가한다 — 운영자와 대화해 AgentAgora 배치 전체(서버 기동 스크립트·스키마·권한·워커 로스터)를 한 번에 부트스트랩한다.

**Architecture:** 백킹 스크립트 없는 순수 SKILL.md 스킬. 본문이 5단계 절차를 기술한다 — 서버 설정(→ OS별 `run-cc-agora` 스크립트), 에이전트 로스터, 스키마(→ `.agentagora/schemas.jsonl`), 권한(→ `comm-matrix.csv`·`file-policy.json`), 에이전트 생성(각 항목마다 `agora-design-worker` 호출). 테스트는 SKILL.md frontmatter 유효성과 본문이 단계별 산출물·하위 스킬을 기술하는지 검증한다.

**Tech Stack:** Markdown(SKILL.md), pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell.

spec: `docs/superpowers/specs/2026-05-18-operator-onboarding-skills-design.md` §4.

이 플랜은 3개 중 3번 — 5단계에서 Plan 2의 `agora-design-worker`를 호출하므로 마지막에 구현한다.

참고 — 서버가 시작 시 로드하는 `.agentagora/schemas.jsonl`은 한 줄당 JSON 객체이며 `name`·`kind`·`purpose`·`body` 4개 키가 필수다(`src/agent_agora/schemas.py::parse_schema_lines`). 서버 CLI 인자는 `--port`·`--no-tls`·`--no-timeout`/`--default-wait-timeout-ms`·`--restore`이고, `.agentagora/`는 `--dir` 아래에 만들어진다(`src/agent_agora/__main__.py`).

---

### Task 1: `agora-setup` 스킬 + README

**Files:**
- Create: `tests/test_plugin_agora_setup.py`
- Create: `plugin/cc-agora-ops/skills/agora-setup/SKILL.md`
- Modify: `plugin/cc-agora-ops/README.md`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_agora_setup.py`를 새로 만든다:

```python
"""Validates the cc-agora-ops agora-setup skill."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugin" / "cc-agora-ops" / "skills" / "agora-setup" / "SKILL.md"


def test_agora_setup_skill_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "description:" in text
    assert "disable-model-invocation: true" in text


def test_agora_setup_skill_covers_all_steps():
    text = SKILL.read_text(encoding="utf-8")
    # 5단계 산출물
    assert "run-cc-agora.ps1" in text and "run-cc-agora.sh" in text
    assert "schemas.jsonl" in text
    assert "comm-matrix.csv" in text
    assert "file-policy.json" in text
    # 5단계는 agora-design-worker에 위임
    assert "agora-design-worker" in text


def test_agora_setup_skill_documents_launch_order():
    text = SKILL.read_text(encoding="utf-8")
    # 서버 먼저, 워커 나중 — MCP 등록 순서 보장
    assert "run-cc-agora" in text
    assert "agent_agora" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_agora_setup.py -v`
Expected: 세 테스트 FAIL — `SKILL.md`가 없어 `FileNotFoundError`.

- [ ] **Step 3: SKILL.md 작성**

`plugin/cc-agora-ops/skills/agora-setup/SKILL.md`를 만든다 (frontmatter·본문 영어 — 프로젝트 규약):

````markdown
---
description: Bootstrap a whole AgentAgora deployment with the operator — server launch script, message schemas, communication and file permissions, and the worker roster.
argument-hint: [--dir]
disable-model-invocation: true
---

# /cc-agora-ops:agora-setup

Walk the operator through standing up a complete AgentAgora deployment in one
pass: server launch configuration, message schemas, communication and file
permissions, and the creation of every planned worker. End-to-end — for each
planned agent this skill runs the `agora-design-worker` flow.

## Arguments

- `--dir=<path>` (optional) — deployment root. Default: the current working
  directory (`$CWD`). The `.agentagora/` data directory, the `run-cc-agora`
  launch script, and the worker directories are all created under it.

## Behavior

Run these steps in order. Ask questions one at a time.

### 1. Server configuration

Ask the operator: server port (default `8420`); TLS on or off; wait timeout in
milliseconds or no timeout; whether to restore undelivered messages on restart
(`--restore`); whether to set an `AGORA_ADMIN_TOKEN`.

Write the server launch script to the deployment root, matching the host OS —
`run-cc-agora.ps1` on Windows, `run-cc-agora.sh` on Unix. It launches the
AgentAgora server with the chosen flags. It is server-only — it does not launch
workers.

Windows `run-cc-agora.ps1`:

```powershell
# AgentAgora server launcher — run this BEFORE starting any worker. Ctrl+C to stop.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:AGORA_ADMIN_TOKEN = "<token>"   # include this line only if a token was chosen
if (Get-Command agent-agora -ErrorAction SilentlyContinue) {
    agent-agora --dir "." --port <port> <flags>
} else {
    python -m agent_agora --dir "." --port <port> <flags>
}
```

Unix `run-cc-agora.sh`:

```bash
#!/usr/bin/env bash
# AgentAgora server launcher — run this BEFORE starting any worker. Ctrl+C to stop.
set -e
cd "$(dirname "$0")"
export AGORA_ADMIN_TOKEN="<token>"   # include this line only if a token was chosen
if command -v agent-agora >/dev/null 2>&1; then
    exec agent-agora --dir "." --port <port> <flags>
else
    exec python -m agent_agora --dir "." --port <port> <flags>
fi
```

`<flags>` is the chosen combination of `--no-tls`, `--no-timeout` or
`--default-wait-timeout-ms <ms>`, and `--restore`.

### 2. Agent roster

Ask the operator for the list of agents to create — each as an `id` plus a
one-line responsibility. This roster is the input to steps 3–5.

### 3. Schemas

Ask the operator how deep to go on message schemas, and act on the choice:

- **Lightweight** — ask only for each schema's name, purpose, and main fields;
  generate a minimal JSON Schema body.
- **Full** — design each message type's field types, required flags, and
  constraints in detail.
- **File only** — note the built-in schemas (`schema_conflict`, `file_share`)
  and prepare an empty schema file; custom schemas are registered at runtime by
  workers and bots.

Write the result to `<dir>/.agentagora/schemas.jsonl` — one JSON object per
line, each with the four keys the server requires: `name`, `kind`, `purpose`,
`body` (the `body` is the JSON Schema). `kind` is typically `conversation`.

### 4. Permissions

Using the roster from step 2:

- **Communication matrix** — pick a topology with the operator (hub-and-spoke /
  all-allow / custom) and write an `(N+1)×(N+1)` CSV with a `*` fallback row and
  column to `<dir>/.agentagora/comm-matrix.csv`. Cells are non-negative integers
  — `0` forbids the edge, `>0` allows it. Follow the `agora-make-comm-matrix`
  skill's CSV rules.
- **File policy** — for each agent, ask for read and write gitignore-pattern
  globs, and write `<dir>/.agentagora/file-policy.json` as
  `{"<id>": {"r": [...], "w": [...]}}`. A missing `r` means read-all; a missing
  `w` means write-none.

### 5. Create agents

For each roster entry, run the `agora-design-worker` flow — pass the `id`, use
the one-line responsibility, then conduct the persona dialogue (mission, role
label, working style, handoff) and scaffold the worker directory under `<dir>`.

## Closing

Tell the operator the launch order: first run `run-cc-agora` to start the server
and confirm it is up, then run each worker's `run.ps1`/`run.sh` from inside its
directory. The server must be up before any worker connects — a worker registers
with the server when its MCP client connects at session start, and Claude Code
connects MCP servers before it runs any `SessionStart` hook, so a hook cannot
bring the server up in time. A standalone launch script run first is the only
reliable ordering.

## Output

| Artifact | Location |
| --- | --- |
| `run-cc-agora.ps1` / `run-cc-agora.sh` | `<dir>/` |
| `schemas.jsonl`, `comm-matrix.csv`, `file-policy.json` | `<dir>/.agentagora/` |
| Worker directories | `<dir>/<id>/` |
````

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_agora_setup.py -v`
Expected: 세 테스트 PASS.

- [ ] **Step 5: cc-agora-ops README에 슬래시 행 추가**

`plugin/cc-agora-ops/README.md`의 "슬래시 명령" 표 끝에 행을 추가한다:

```markdown
| `/cc-agora-ops:agora-setup` | `[--dir]` | AgentAgora 배치 전체를 한 번에 부트스트랩 — 서버 기동 스크립트·스키마·권한·워커 로스터. 각 에이전트는 `agora-design-worker`로 생성. |
```

- [ ] **Step 6: 전체 스위트 회귀 확인 + 커밋**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

```bash
git add tests/test_plugin_agora_setup.py plugin/cc-agora-ops/skills/agora-setup/SKILL.md plugin/cc-agora-ops/README.md
git commit -m "feat: cc-agora-ops — agora-setup 스킬"
```

---

## 완료 기준

- `plugin/cc-agora-ops/skills/agora-setup/SKILL.md`가 존재하고 frontmatter가 유효하다(`disable-model-invocation: true`).
- SKILL.md가 5단계 절차(서버 설정 → 로스터 → 스키마 → 권한 → 에이전트 생성)와 산출물(`run-cc-agora.{ps1,sh}`·`schemas.jsonl`·`comm-matrix.csv`·`file-policy.json`)을 기술한다.
- 5단계가 `agora-design-worker`에 위임한다.
- SKILL.md가 기동 순서(서버 먼저, 워커 나중)와 그 근거를 기술한다.
- `cc-agora-ops` README에 슬래시 행이 있다.
- 전체 테스트 스위트 통과.
