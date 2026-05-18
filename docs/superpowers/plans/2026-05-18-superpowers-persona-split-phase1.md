# superpowers 페르소나 분리 — Phase 1 (플러그인 스캐폴딩) 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** superpowers 14개 스킬을 `plugin/superpowers/` 아래 7개 플러그인(`superpowers-base` + 페르소나 6종)으로 잘라붙여, 마켓플레이스에 등록·검증되는 상태를 만든다.

**Architecture:** 설계 spec `docs/superpowers/specs/2026-05-18-superpowers-persona-split-design.md` §3·§4·§11(1단계) 기준. 원본 스킬 디렉토리를 그대로 복사(`model`/`effort` frontmatter 보존), 페르소나마다 `plugin.json` + `skills/persona/SKILL.md`(신규)를 추가, `plugin/.claude-plugin/marketplace.json`에 등록. 스킬 간 cross-reference 재배선·위임 배선은 Phase 2, 테스트 하네스 재설계는 Phase 6 — 본 플랜 범위 밖.

**Tech Stack:** Claude Code 플러그인 (`.claude-plugin/plugin.json`, `marketplace.json`), AgentAgora `plugin/personas/` 레이아웃 패턴, pytest (`tests/test_plugin_marketplace.py`).

**원본 위치:** `C:/Users/jylee/source/superpowers_model_specified/skills/<name>/` — `/add-dir`로 추가된 작업 디렉토리. 각 스킬 디렉토리에는 `claude -p` 호출이 없다(전수 조사 확인) — 복사로 `claude -p`가 딸려오지 않는다.

---

## 파일 구조

```
plugin/superpowers/
  superpowers-base/
    .claude-plugin/plugin.json                     생성
    skills/using-superpowers/                      복사
    skills/verification-before-completion/         복사
    skills/writing-skills/                         복사
  superpowers-planner/
    .claude-plugin/plugin.json                     생성
    skills/persona/SKILL.md                        생성
    skills/brainstorming/                          복사
    skills/writing-plans/                          복사
  superpowers-implementer/
    .claude-plugin/plugin.json                     생성
    skills/persona/SKILL.md                        생성
    skills/test-driven-development/                복사
    skills/executing-plans/                        복사
    skills/using-git-worktrees/                    복사
    skills/finishing-a-development-branch/         복사
  superpowers-debugger/
    .claude-plugin/plugin.json                     생성
    skills/persona/SKILL.md                        생성
    skills/systematic-debugging/                   복사
  superpowers-reviewer/
    .claude-plugin/plugin.json                     생성
    skills/persona/SKILL.md                        생성
    skills/requesting-code-review/                 복사
    skills/receiving-code-review/                  복사
  superpowers-router/
    .claude-plugin/plugin.json                     생성
    skills/persona/SKILL.md                        생성
    skills/subagent-driven-development/            복사
    skills/dispatching-parallel-agents/            복사
  superpowers-improver/
    .claude-plugin/plugin.json                     생성
    skills/persona/SKILL.md                        생성
    (improvement-review 스킬은 Phase 4)
plugin/.claude-plugin/marketplace.json             수정 — 7개 항목 추가
```

`superpowers-base`는 라이브러리 — `skills/persona/`가 없다. 페르소나 6종은 `persona` 스킬을 가진다. 신규 플러그인 버전은 `0.1.0`.

---

## Task 1: `superpowers-base` 플러그인

**Files:**
- Create: `plugin/superpowers/superpowers-base/.claude-plugin/plugin.json`
- Copy: `superpowers_model_specified/skills/{using-superpowers,verification-before-completion,writing-skills}/` → `plugin/superpowers/superpowers-base/skills/`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-base/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-base",
  "description": "Superpowers persona base — shared skills every persona needs: skill discovery, verification before completion, and skill authoring.",
  "version": "0.1.0"
}
```

- [ ] **Step 2: 공통 스킬 3종 복사**

```bash
mkdir -p plugin/superpowers/superpowers-base/skills
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/using-superpowers" plugin/superpowers/superpowers-base/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/verification-before-completion" plugin/superpowers/superpowers-base/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/writing-skills" plugin/superpowers/superpowers-base/skills/
```

- [ ] **Step 3: 구조 확인**

Run: `ls plugin/superpowers/superpowers-base/skills/`
Expected: `using-superpowers  verification-before-completion  writing-skills` — 각 디렉토리에 `SKILL.md` 존재.

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-base
git commit -m "feat: superpowers-base 플러그인 스캐폴딩 (공통 스킬 3종)"
```

---

## Task 2: `superpowers-planner` 플러그인

**Files:**
- Create: `plugin/superpowers/superpowers-planner/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-planner/skills/persona/SKILL.md`
- Copy: `skills/{brainstorming,writing-plans}/` → `plugin/superpowers/superpowers-planner/skills/`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-planner/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-planner",
  "description": "Superpowers planner persona — turns ideas into approved specs and bite-sized implementation plans.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: persona 스킬 생성**

`plugin/superpowers/superpowers-planner/skills/persona/SKILL.md`:

```markdown
---
name: persona
description: Superpowers planner persona — owns the brainstorming and writing-plans phases. Use when this worker should act as the planner.
---

# Planner Persona

You are the **planner** in the superpowers multi-persona workflow. You turn raw ideas and requirements into an approved spec and a bite-sized implementation plan.

## Owned skills
- `brainstorming` — explore intent, requirements, and design; produce a spec.
- `writing-plans` — turn a spec into a step-by-step implementation plan.

## Workflow position
Entry point of the workflow. Your input is either a raw idea from the user, or improvement findings handed back from the improver persona. Your output is a spec plus a plan.

## Hand-off
After the plan is written and approved, hand the plan to the **router** persona, which decides parallel vs. sequential execution.
```

- [ ] **Step 3: planner 스킬 2종 복사**

```bash
mkdir -p plugin/superpowers/superpowers-planner/skills
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/brainstorming" plugin/superpowers/superpowers-planner/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/writing-plans" plugin/superpowers/superpowers-planner/skills/
```

- [ ] **Step 4: 구조 확인**

Run: `ls plugin/superpowers/superpowers-planner/skills/`
Expected: `brainstorming  persona  writing-plans`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-planner
git commit -m "feat: superpowers-planner 페르소나 플러그인"
```

---

## Task 3: `superpowers-implementer` 플러그인

**Files:**
- Create: `plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md`
- Copy: `skills/{test-driven-development,executing-plans,using-git-worktrees,finishing-a-development-branch}/`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-implementer",
  "description": "Superpowers implementer persona — executes plans with TDD, isolated worktrees, and clean branch completion.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: persona 스킬 생성**

`plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md`:

```markdown
---
name: persona
description: Superpowers implementer persona — owns TDD implementation, plan execution, worktrees, and branch completion. Use when this worker should act as the implementer.
---

# Implementer Persona

You are the **implementer** in the superpowers multi-persona workflow. You take a task or plan and produce tested, committed code.

## Owned skills
- `test-driven-development` — write the failing test first, then the implementation.
- `executing-plans` — execute a written plan task-by-task.
- `using-git-worktrees` — create an isolated workspace for the work.
- `finishing-a-development-branch` — complete the branch (merge / PR / cleanup).

## Workflow position
You receive task assignments from the router persona. You implement them with TDD.

## Hand-off
- When you hit a bug you cannot resolve inline, hand off to the **debugger** persona.
- When work needs review, hand off to the **reviewer** persona.
- After `finishing-a-development-branch` completes, hand off to the **improver** persona.
```

- [ ] **Step 3: implementer 스킬 4종 복사**

```bash
mkdir -p plugin/superpowers/superpowers-implementer/skills
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/test-driven-development" plugin/superpowers/superpowers-implementer/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/executing-plans" plugin/superpowers/superpowers-implementer/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/using-git-worktrees" plugin/superpowers/superpowers-implementer/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/finishing-a-development-branch" plugin/superpowers/superpowers-implementer/skills/
```

- [ ] **Step 4: 구조 확인**

Run: `ls plugin/superpowers/superpowers-implementer/skills/`
Expected: `executing-plans  finishing-a-development-branch  persona  test-driven-development  using-git-worktrees`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-implementer
git commit -m "feat: superpowers-implementer 페르소나 플러그인"
```

---

## Task 4: `superpowers-debugger` 플러그인

**Files:**
- Create: `plugin/superpowers/superpowers-debugger/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md`
- Copy: `skills/systematic-debugging/`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-debugger/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-debugger",
  "description": "Superpowers debugger persona — systematically tracks down and fixes bugs and test failures.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: persona 스킬 생성**

`plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md`:

```markdown
---
name: persona
description: Superpowers debugger persona — owns systematic debugging of bugs and test failures. Use when this worker should act as the debugger.
---

# Debugger Persona

You are the **debugger** in the superpowers multi-persona workflow. You take a bug, test failure, or unexpected behavior and find the root cause.

## Owned skills
- `systematic-debugging` — investigate methodically before proposing a fix.

## Workflow position
You receive a bug report from the implementer persona when it hits something it cannot resolve inline.

## Hand-off
Once the root cause is found and the fix is verified, hand control back to the **implementer** persona.
```

- [ ] **Step 3: debugger 스킬 복사**

```bash
mkdir -p plugin/superpowers/superpowers-debugger/skills
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/systematic-debugging" plugin/superpowers/superpowers-debugger/skills/
```

- [ ] **Step 4: 구조 확인**

Run: `ls plugin/superpowers/superpowers-debugger/skills/`
Expected: `persona  systematic-debugging`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-debugger
git commit -m "feat: superpowers-debugger 페르소나 플러그인"
```

---

## Task 5: `superpowers-reviewer` 플러그인

**Files:**
- Create: `plugin/superpowers/superpowers-reviewer/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md`
- Copy: `skills/{requesting-code-review,receiving-code-review}/`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-reviewer/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-reviewer",
  "description": "Superpowers reviewer persona — reviews code changes and handles review feedback with technical rigor.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: persona 스킬 생성**

`plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md`:

```markdown
---
name: persona
description: Superpowers reviewer persona — owns code review, both requesting and receiving feedback. Use when this worker should act as the reviewer.
---

# Reviewer Persona

You are the **reviewer** in the superpowers multi-persona workflow. You verify that code changes meet requirements and quality standards.

## Owned skills
- `requesting-code-review` — review changes for correctness, readability, and test coverage.
- `receiving-code-review` — process review feedback with technical rigor, not blind agreement.

## Workflow position
You receive review requests from the implementer persona.

## Hand-off
After review, hand control back to the **implementer** persona — with approval, or with the issues that must be fixed.
```

- [ ] **Step 3: reviewer 스킬 2종 복사**

```bash
mkdir -p plugin/superpowers/superpowers-reviewer/skills
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/requesting-code-review" plugin/superpowers/superpowers-reviewer/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/receiving-code-review" plugin/superpowers/superpowers-reviewer/skills/
```

- [ ] **Step 4: 구조 확인**

Run: `ls plugin/superpowers/superpowers-reviewer/skills/`
Expected: `persona  receiving-code-review  requesting-code-review`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-reviewer
git commit -m "feat: superpowers-reviewer 페르소나 플러그인"
```

---

## Task 6: `superpowers-router` 플러그인

**Files:**
- Create: `plugin/superpowers/superpowers-router/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-router/skills/persona/SKILL.md`
- Copy: `skills/{subagent-driven-development,dispatching-parallel-agents}/`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-router/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-router",
  "description": "Superpowers router persona — decomposes a plan into tasks and routes them to worker personas, parallel or sequential.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: persona 스킬 생성**

`plugin/superpowers/superpowers-router/skills/persona/SKILL.md`:

```markdown
---
name: persona
description: Superpowers router persona — decomposes plans into tasks and routes them, choosing parallel or sequential execution. Use when this worker should act as the router.
---

# Router Persona

You are the **router** in the superpowers multi-persona workflow. You take an approved plan and route its tasks to worker personas.

## Owned skills
- `subagent-driven-development` — execute a plan task-by-task, sequentially, with review between tasks.
- `dispatching-parallel-agents` — dispatch independent tasks in parallel.

## Workflow position
You receive an approved plan from the planner persona.

## Parallel checkpoint
Before dispatching, decide: are the plan's tasks independent enough to run in parallel?
- Independent → `dispatching-parallel-agents` path.
- Sequential (interdependent) → `subagent-driven-development` path.

## Hand-off
Dispatch tasks to the **implementer** persona.
```

- [ ] **Step 3: router 스킬 2종 복사**

```bash
mkdir -p plugin/superpowers/superpowers-router/skills
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/subagent-driven-development" plugin/superpowers/superpowers-router/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/dispatching-parallel-agents" plugin/superpowers/superpowers-router/skills/
```

- [ ] **Step 4: 구조 확인**

Run: `ls plugin/superpowers/superpowers-router/skills/`
Expected: `dispatching-parallel-agents  persona  subagent-driven-development`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-router
git commit -m "feat: superpowers-router 페르소나 플러그인"
```

---

## Task 7: `superpowers-improver` 플러그인 (셸만)

`improvement-review` 스킬은 Phase 4에서 작성한다. Phase 1에서는 플러그인 셸 + persona 스킬만 만든다.

**Files:**
- Create: `plugin/superpowers/superpowers-improver/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-improver/skills/persona/SKILL.md`

- [ ] **Step 1: plugin.json 생성**

`plugin/superpowers/superpowers-improver/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-improver",
  "description": "Superpowers improver persona — reviews finished work for improvements, refactors, and new ideas, then loops back to the planner.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: persona 스킬 생성**

`plugin/superpowers/superpowers-improver/skills/persona/SKILL.md`:

```markdown
---
name: persona
description: Superpowers improver persona — reviews completed work for improvement opportunities and loops the workflow back to the planner. Use when this worker should act as the improver.
---

# Improver Persona

You are the **improver** in the superpowers multi-persona workflow. You close the loop: after work is done, you look for what could be better.

## Owned skills
- `improvement-review` — review finished work for feature improvements, refactors, and new ideas. (Added in a later phase.)

## Workflow position
You are triggered after the implementer persona completes `finishing-a-development-branch`.

## User gate
Before reviewing, ask the user whether they want an improvement pass. If they decline, the workflow ends.

## Hand-off
If the user approves and you find improvement opportunities, hand the findings to the **planner** persona — which turns them into a new plan, looping the workflow.
```

- [ ] **Step 3: 구조 확인**

Run: `ls plugin/superpowers/superpowers-improver/skills/`
Expected: `persona`

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-improver
git commit -m "feat: superpowers-improver 페르소나 플러그인 셸"
```

---

## Task 8: marketplace.json 등록 & 검증

**Files:**
- Modify: `plugin/.claude-plugin/marketplace.json`
- Test: `tests/test_plugin_marketplace.py`

- [ ] **Step 1: 마켓플레이스 검증 테스트를 먼저 실행 (현재 통과 확인)**

Run: `uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q`
Expected: PASS — 신규 플러그인 추가 전 baseline.

- [ ] **Step 2: marketplace.json의 `plugins` 배열에 7개 항목 추가**

`plugin/.claude-plugin/marketplace.json`의 `plugins` 배열 끝(`cc-agora-writer` 항목 뒤)에 추가:

```json
    {
      "name": "superpowers-base",
      "source": "./superpowers/superpowers-base",
      "description": "Superpowers persona base — shared skills every persona needs."
    },
    {
      "name": "superpowers-planner",
      "source": "./superpowers/superpowers-planner",
      "description": "Superpowers planner persona — ideas into specs and implementation plans."
    },
    {
      "name": "superpowers-implementer",
      "source": "./superpowers/superpowers-implementer",
      "description": "Superpowers implementer persona — TDD implementation and branch completion."
    },
    {
      "name": "superpowers-debugger",
      "source": "./superpowers/superpowers-debugger",
      "description": "Superpowers debugger persona — systematic debugging."
    },
    {
      "name": "superpowers-reviewer",
      "source": "./superpowers/superpowers-reviewer",
      "description": "Superpowers reviewer persona — code review and feedback handling."
    },
    {
      "name": "superpowers-router",
      "source": "./superpowers/superpowers-router",
      "description": "Superpowers router persona — task decomposition and routing."
    },
    {
      "name": "superpowers-improver",
      "source": "./superpowers/superpowers-improver",
      "description": "Superpowers improver persona — improvement review and workflow loop-back."
    }
```

직전 항목(`cc-agora-writer`)의 닫는 `}` 뒤에 `,`를 추가하는 것을 잊지 말 것 — JSON 배열 구분자.

- [ ] **Step 3: marketplace.json이 유효한 JSON인지 확인**

Run: `python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json', encoding='utf-8')); print('valid JSON')"`
Expected: `valid JSON`

- [ ] **Step 4: 마켓플레이스 검증 테스트 재실행**

Run: `uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q`
Expected: PASS — 7개 신규 플러그인 항목의 `source` 경로가 실제 디렉토리를 가리키고 각 디렉토리에 `.claude-plugin/plugin.json`이 존재함을 검증.
만약 테스트가 신규 플러그인을 커버하지 않으면(테스트가 cc-agora 계열만 검사) FAIL이 아닌 PASS로 끝날 수 있다 — 그 경우 Step 5의 수동 확인으로 보강.

- [ ] **Step 5: 7개 플러그인 디렉토리 수동 확인**

Run: `for d in base planner implementer debugger reviewer router improver; do echo "-- superpowers-$d --"; ls "plugin/superpowers/superpowers-$d/.claude-plugin/plugin.json" && ls "plugin/superpowers/superpowers-$d/skills/"; done`
Expected: 7개 모두 `plugin.json` 존재, `skills/` 디렉토리에 해당 스킬들 존재.

- [ ] **Step 6: 커밋**

```bash
git add plugin/.claude-plugin/marketplace.json
git commit -m "feat: superpowers 페르소나 7종을 마켓플레이스에 등록"
```

---

## Self-Review (작성자 체크 — 실행 전 확인용)

**Spec 커버리지 (Phase 1 = spec §11 1단계):**
- §3 페르소나 7종 + 스킬 분배 → Task 1–7이 7개 플러그인 생성, 14개 원본 스킬을 spec §3 표대로 복사. ✓
- §4 플러그인 레이아웃 (`plugin/superpowers/<persona>/`, plugin.json, persona 스킬, base 의존) → Task 1–7. ✓
- §4 marketplace.json 등록 → Task 8. ✓
- §8 `claude -p` 제거 → 스킬 디렉토리엔 `claude -p`가 없으므로(전수 조사) 복사만으로 충족. 테스트 하네스 재설계는 Phase 6. ✓
- §3 `model`/`effort` frontmatter 보존 → 디렉토리 복사로 자동 보존. ✓

**Phase 1 범위 밖 (후속 플랜):** 위임 배선·스킬 cross-reference 재작성(Phase 2), 라우팅 봇(Phase 3), `improvement-review` 스킬(Phase 4), 병렬 체크포인트 배선(Phase 5), 테스트 재설계(Phase 6).

**Placeholder 스캔:** persona 스킬 6종은 완전한 본문을 가짐. improver의 persona 스킬은 `improvement-review`가 "later phase"에 온다고 명시 — 이는 Phase 1 산출물 기준 정확한 사실이며 placeholder가 아님. "copy" 스텝은 원본을 그대로 복사하는 완결된 지시.

**일관성:** 플러그인 이름 `superpowers-<persona>` 7종이 plugin.json `name`·marketplace.json `name`·디렉토리명에서 일치. `dependencies: ["superpowers-base"]`가 페르소나 6종에 동일 적용.
