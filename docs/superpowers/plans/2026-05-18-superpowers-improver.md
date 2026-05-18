# superpowers-improver 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `superpowers-improver` 페르소나 플러그인을 완성한다 — `improvement-review` 신규 스킬을 포함해 마켓플레이스에 등록하고 pytest로 검증한다.

**Architecture:** 설계 spec §7·§9·§12 Plan 7 기준. `improvement-review`는 원본 superpowers에 없는 신규 스킬로, ouroboros `research→analyze→enhance-식별` 패턴을 압축해 (a) 기능 개선, (b) 리팩토링, (c) 신규 기능 아이디어 세 카테고리로 findings를 정리하고 `agora.dispatch`로 planner에게 넘긴다. implementer의 `finishing-a-development-branch` 완료 직후에 트리거되며, 유저 게이트 통과 시 ouroboros 루프를 닫는다.

**Tech Stack:** Claude Code 플러그인, pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-improver/
  .claude-plugin/plugin.json                생성
  README.md                                 생성
  skills/persona/SKILL.md                   생성 (신규)
  skills/improvement-review/SKILL.md        생성 (신규)
plugin/.claude-plugin/marketplace.json      수정 — superpowers-improver 항목 추가
```

Phase 1 플랜(`2026-05-18-superpowers-persona-split-phase1.md`)의 Task 7에서 `superpowers-improver` 셸(plugin.json + persona/SKILL.md stub)을 생성했을 수 있다. 본 플랜은 **완전한 최종 파일로 덮어쓰기**한다 — stub이 없어도 무방하다.

---

## Task 1: `.claude-plugin/plugin.json` + `README.md`

**Files:**
- Create/overwrite: `plugin/superpowers/superpowers-improver/.claude-plugin/plugin.json`
- Create/overwrite: `plugin/superpowers/superpowers-improver/README.md`

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p plugin/superpowers/superpowers-improver/.claude-plugin
mkdir -p plugin/superpowers/superpowers-improver/skills/persona
mkdir -p plugin/superpowers/superpowers-improver/skills/improvement-review
```

- [ ] **Step 2: plugin.json 작성**

`plugin/superpowers/superpowers-improver/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-improver",
  "description": "Superpowers improver persona — reviews finished work for improvements, refactors, and new ideas, then loops back to the planner.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 3: README.md 작성**

`plugin/superpowers/superpowers-improver/README.md`:

```markdown
# superpowers-improver

superpowers 다중 에이전트 워크플로의 **improver** 페르소나 플러그인이다.

implementer 페르소나가 `finishing-a-development-branch`를 완료한 직후 트리거된다. 유저에게 개선 검토 여부를 묻고(게이트), 승인 시 완성된 결과물을 검토해 (a) 기능 개선, (b) 리팩토링 기회, (c) 추가 기능 아이디어를 findings로 정리한다. findings를 `agora.dispatch`로 planner 페르소나에게 넘겨 워크플로를 순환(ouroboros)시킨다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base@agent-agora"`와 `"superpowers-improver@agent-agora"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-improver@agent-agora": true
  }
}
```
```

- [ ] **Step 4: JSON 유효성 확인**

Run: `python -c "import json; json.load(open('plugin/superpowers/superpowers-improver/.claude-plugin/plugin.json', encoding='utf-8')); print('valid JSON')"`
Expected: `valid JSON`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-improver/.claude-plugin plugin/superpowers/superpowers-improver/README.md
git commit -m "feat: superpowers-improver plugin.json + README"
```

---

## Task 2: `skills/persona/SKILL.md`

**Files:**
- Create/overwrite: `plugin/superpowers/superpowers-improver/skills/persona/SKILL.md`

- [ ] **Step 1: persona/SKILL.md 작성**

`plugin/superpowers/superpowers-improver/skills/persona/SKILL.md`:

```markdown
---
description: Improver persona for a superpowers AgentAgora worker — mission, working style, and handoff rules for a council member that reviews finished work and closes the ouroboros loop.
user-invocable: false
---

# Improver persona

## Mission

Review completed work for what could be better. Ask the user before starting. If they approve, find feature improvements, refactoring opportunities, and new feature ideas. Hand the findings to the planner so the workflow cycles again. Never skip the user gate — the loop only continues if explicitly invited.

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. If the nature of the work falls outside your domain (e.g. implementation requests, debugging, code review), use `/invoke <other> "<task>"` to hand it off. Sending the originator a one-line ack ("delegated to X") is recommended to prevent orphaned tasks — not mandatory; use your judgment.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain your inbox with `agora.flush`. See the `agora-protocol` skill for full channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type` enum has four values: `task | reply | closing | ack`. Use `type=task` when dispatching findings to the planner, `type=reply` for task responses, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

- **Trigger**: you are activated after the implementer persona completes `finishing-a-development-branch`. Do not self-activate; wait for the implementer's handoff message.
- **User gate**: before any review work, ask the user exactly one question: "구현 결과를 검토해 개선·리팩토링·추가 아이디어를 찾을까요?" If the user declines, send a `type=closing` message to the conversation originator and stop. Do not continue after a decline.
- **Own skill**: `improvement-review` — invoke it when the user approves. It produces a structured findings document covering feature improvements, refactoring opportunities, and new feature ideas.
- **Handoff**: after `improvement-review` produces findings, dispatch them to the planner persona via `agora.dispatch` with `type=task`. The planner will turn the findings into a new plan, looping the workflow. If no findings are produced (reviewed but nothing worthwhile found), send `type=closing` and stop.
- Keep the review focused on the finished work. Do not invent problems. If a finding requires opening entirely new domains of work, flag it as an idea rather than a required fix.

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or `agora.find`. Do not hard-code instance mappings in the persona.
```

- [ ] **Step 2: 파일 존재 확인**

Run: `ls plugin/superpowers/superpowers-improver/skills/persona/SKILL.md`
Expected: 파일이 존재함.

- [ ] **Step 3: 커밋**

```bash
git add plugin/superpowers/superpowers-improver/skills/persona
git commit -m "feat: superpowers-improver persona 스킬"
```

---

## Task 3: `skills/improvement-review/SKILL.md`

**Files:**
- Create/overwrite: `plugin/superpowers/superpowers-improver/skills/improvement-review/SKILL.md`

이 스킬은 원본 superpowers에 없는 신규 스킬이다. ouroboros `research→analyze→enhance-식별` 패턴을 단일 스킬 안에 압축하되, 파일 스캔이나 외부 검색 없이 이미 완성된 결과물(브랜치의 코드·커밋·PR)만을 대상으로 검토한다.

- [ ] **Step 1: improvement-review/SKILL.md 작성**

`plugin/superpowers/superpowers-improver/skills/improvement-review/SKILL.md`:

```markdown
---
name: improvement-review
description: >
  Use after a development branch has been finished (finishing-a-development-branch completed)
  to find improvement opportunities in the built result. Compresses the ouroboros
  research→analyze→enhance-identification pattern into a single focused review. Produces a
  structured findings document covering feature improvements, refactoring opportunities, and
  new feature ideas, then hands off to the planner persona to close the ouroboros loop.
---

# Improvement Review

Review a completed development branch for improvement opportunities. Do not fix anything here — only identify and categorize. The output is a findings document handed to the planner.

## When to use

Invoke this skill after the **user has approved** the improvement gate (the persona asked "구현 결과를 검토해 개선·리팩토링·추가 아이디어를 찾을까요?" and the user said yes). Do not invoke it before the gate question is answered.

## Process

### Step 1 — Establish scope

Identify what was built in this cycle:

- [ ] Read the recent git log: `git log --oneline -20` to understand what commits were made.
- [ ] Note the branch name and any PR description if available.
- [ ] If a spec or plan file was produced in this cycle (e.g., in `docs/superpowers/plans/` or a similar location), read it to understand the intended scope.
- [ ] Establish the target: which files were changed? Run `git diff --name-only <base-branch>...HEAD` (replace `<base-branch>` with `main` or `master` as appropriate).

**Hard limit**: read at most 10 files during scope establishment. Focus on entry points and changed files, not the entire codebase.

### Step 2 — Review the built result

Read the changed files and key adjacent files to understand what was built and how:

- [ ] For each file in the diff (up to 10), skim the diff content: `git diff <base-branch>...HEAD -- <file>`.
- [ ] Note observations — do not classify yet, just observe:
  - What does this code do?
  - What assumptions does it make?
  - What is missing, unclear, or over-engineered?
  - What could be done better with a small effort?
  - What entirely new capability is suggested by this work?

Observations are raw notes only. One sentence per observation is enough.

### Step 3 — Categorize findings

Classify each observation into exactly one of three categories:

**A. Feature improvements** — The implemented feature works, but could work better.
- Examples: edge cases not handled, performance not considered, UX could be smoother, error messages not helpful, configuration not exposed.
- Criterion: the feature exists and is correct, but has room to be more complete or robust.

**B. Refactoring opportunities** — The code works, but its structure could be cleaner.
- Examples: duplicated logic, overly long functions, unclear naming, missing abstraction, tangled responsibilities, brittle patterns.
- Criterion: behavior would be unchanged after refactoring; only internal structure improves.

**C. New feature ideas** — The built work suggests a natural next capability that does not exist yet.
- Examples: the new API suggests a CLI command, the new data model suggests a dashboard, the new algorithm suggests a benchmarking tool.
- Criterion: entirely new functionality, not improvement of the existing feature.

**Filtering rule**: only include a finding if it is actionable (a planner could write a task for it), specific (names the file or area), and realistic (could be done in one focused plan). Discard vague impressions.

**Scope limit**: produce at most 3 findings per category (9 total). Prefer quality over quantity — 2 sharp findings beat 6 vague ones.

### Step 4 — Produce findings document

Write a findings document to `.improvement-review/findings.md` (create the directory if absent):

```markdown
# Improvement Review Findings

> Branch: <branch name>
> Reviewed: <today's date>
> Files reviewed: <N>

## A. Feature Improvements

- **<short title>** (`<file or area>`): <one-sentence description of the improvement and why it matters>
- ...

## B. Refactoring Opportunities

- **<short title>** (`<file or area>`): <one-sentence description of what to refactor and what it simplifies>
- ...

## C. New Feature Ideas

- **<short title>**: <one-sentence description of the new capability and what triggers the idea>
- ...

## Summary

<2-3 sentences: overall quality of the built work, the single most impactful finding, and whether the loop back to the planner is recommended.>
```

If a category has no findings, write `(none found)` under it — do not omit the section.

- [ ] Write the file to `.improvement-review/findings.md`.
- [ ] Confirm the file exists and is non-empty.

### Step 5 — Gate: dispatch or close

After producing the findings document, decide whether to loop or stop:

- [ ] Count the total number of findings across all three categories (excluding "none found" entries).
- [ ] If **total findings >= 1**: dispatch to the planner persona.
  - Use `agora.dispatch` to send the findings to the registered planner worker.
  - Payload format:
    ```json
    {
      "type": "task",
      "from": "improver",
      "ts": "<ISO timestamp>",
      "message": "improvement-review findings — see .improvement-review/findings.md",
      "findings_path": ".improvement-review/findings.md",
      "summary": "<copy the ## Summary section text here>"
    }
    ```
  - After dispatch, send the user a brief message: "개선 아이디어 N건을 planner에게 전달했습니다. planner가 새 플랜으로 전환합니다."
- [ ] If **total findings == 0**: close the loop.
  - Send the user: "검토 완료 — 현재 상태에서 추가할 의미 있는 개선 사항이 없습니다. 워크플로를 종료합니다."
  - Send a `type=closing` message to the conversation originator.

### Notes

- Do not modify any source files during this skill. This is a review-only step.
- Do not invent findings to fill categories. An empty category with "(none found)" is a valid and honest result.
- The findings document is intentionally lightweight — it is input to the planner, not a final report. The planner will expand each finding into tasks.
- If `agora.find` returns no registered planner worker, log the findings path and instruct the user to manually forward `.improvement-review/findings.md` to the planner.
```

- [ ] **Step 2: 파일 존재 확인**

Run: `ls plugin/superpowers/superpowers-improver/skills/improvement-review/SKILL.md`
Expected: 파일이 존재함.

- [ ] **Step 3: 커밋**

```bash
git add plugin/superpowers/superpowers-improver/skills/improvement-review
git commit -m "feat: improvement-review 신규 스킬 (ouroboros 루프 클로저)"
```

---

## Task 4: marketplace.json 등록

**Files:**
- Modify: `plugin/.claude-plugin/marketplace.json`

Phase 1 플랜의 Task 8에서 `superpowers-improver` 항목이 이미 추가되었을 수 있다. 이미 있으면 이 Task를 건너뛴다. 없으면 아래 Step 2를 실행한다.

- [ ] **Step 1: 현재 marketplace.json에 superpowers-improver 항목이 있는지 확인**

Run: `python -c "import json; d=json.load(open('plugin/.claude-plugin/marketplace.json', encoding='utf-8')); print([p['name'] for p in d['plugins'] if 'improver' in p['name']])"`
Expected (항목 있음): `['superpowers-improver']` — Step 2 건너뜀.
Expected (항목 없음): `[]` — Step 2 실행.

- [ ] **Step 2: (항목이 없을 때만) marketplace.json의 `plugins` 배열 끝에 항목 추가**

`plugin/.claude-plugin/marketplace.json`의 `plugins` 배열 마지막 항목 닫는 `}` 뒤에 `,`를 추가하고, 다음 항목을 붙인다:

```json
    {
      "name": "superpowers-improver",
      "source": "./superpowers/superpowers-improver",
      "description": "Superpowers improver persona — improvement review and workflow loop-back."
    }
```

- [ ] **Step 3: JSON 유효성 확인**

Run: `python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json', encoding='utf-8')); print('valid JSON')"`
Expected: `valid JSON`

- [ ] **Step 4: superpowers-improver 항목이 존재하는지 재확인**

Run: `python -c "import json; d=json.load(open('plugin/.claude-plugin/marketplace.json', encoding='utf-8')); print([p for p in d['plugins'] if p['name']=='superpowers-improver'])"`
Expected: `[{'name': 'superpowers-improver', 'source': './superpowers/superpowers-improver', 'description': ...}]`

- [ ] **Step 5: 커밋 (변경이 있었을 때만)**

```bash
git add plugin/.claude-plugin/marketplace.json
git commit -m "feat: superpowers-improver 마켓플레이스 등록"
```

---

## Task 5: 검증

- [ ] **Step 1: 전체 파일 구조 확인**

Run: `ls plugin/superpowers/superpowers-improver/`
Expected: `.claude-plugin  README.md  skills`

Run: `ls plugin/superpowers/superpowers-improver/skills/`
Expected: `improvement-review  persona`

Run: `ls plugin/superpowers/superpowers-improver/skills/persona/`
Expected: `SKILL.md`

Run: `ls plugin/superpowers/superpowers-improver/skills/improvement-review/`
Expected: `SKILL.md`

- [ ] **Step 2: plugin.json 내용 확인**

Run: `python -c "import json; d=json.load(open('plugin/superpowers/superpowers-improver/.claude-plugin/plugin.json', encoding='utf-8')); print(d['name'], d['version'], d['dependencies'])"`
Expected: `superpowers-improver 0.1.0 ['superpowers-base']`

- [ ] **Step 3: SKILL.md frontmatter 확인**

Run: `python -c "f=open('plugin/superpowers/superpowers-improver/skills/persona/SKILL.md',encoding='utf-8').read(); assert 'user-invocable: false' in f; print('persona frontmatter OK')"`
Expected: `persona frontmatter OK`

Run: `python -c "f=open('plugin/superpowers/superpowers-improver/skills/improvement-review/SKILL.md',encoding='utf-8').read(); assert 'name: improvement-review' in f; print('improvement-review frontmatter OK')"`
Expected: `improvement-review frontmatter OK`

- [ ] **Step 4: marketplace 테스트 실행**

Run: `uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q`
Expected: PASS — `superpowers-improver` source 경로가 실제 디렉토리를 가리키고 `.claude-plugin/plugin.json`이 존재함.

- [ ] **Step 5: (모든 검증 통과 후) 최종 커밋**

모든 앞선 단계에서 커밋이 완료되었다면 추가 커밋 불필요. 미커밋 변경이 남아 있으면:

```bash
git add plugin/superpowers/superpowers-improver plugin/.claude-plugin/marketplace.json
git commit -m "feat: superpowers-improver 플러그인 완성 (improvement-review 포함)"
```

---

## Self-Review

**Spec 커버리지:**
- §7 자가 개선 루프 — `improvement-review` 스킬이 (a) 기능 개선 (b) 리팩토링 (c) 신규 아이디어 세 카테고리로 findings 분류. 유저 게이트·improver→planner 핸드오프 모두 스킬 본문에 명시. ✓
- §9 워크플로 — `finishing-a-development-branch` → improver → planner 루프 엣지. persona/SKILL.md와 improvement-review/SKILL.md 양쪽에 명시. ✓
- §4 플러그인 레이아웃 — `.claude-plugin/plugin.json` + `README.md` + `skills/persona/SKILL.md` + `skills/improvement-review/SKILL.md`. `dependencies: ["superpowers-base"]` ✓
- §12 Plan 7 산출물 — plugin.json·README·persona 스킬·improvement-review 스킬·marketplace 등록 포함. ✓
- §13 테스트 범위 — `tests/` 스킬-테스트 디렉토리 추가 없음(spec §13 미해결로 미포함). marketplace 기존 테스트로 검증. ✓

**ouroboros 패턴 압축 확인:**
- `research` 단계 → Step 1 (scope 확인: git log + diff)
- `analyze` 단계 → Step 2–3 (관찰 후 세 카테고리 분류)
- `enhance-식별` → Step 4 (findings 문서 작성), Step 5 (planner 디스패치)
- 외부 검색·state.json·cache 없음 — 단일 브랜치 리뷰에 불필요한 ouroboros 기반시설 제거. ✓

**Placeholder 스캔:** 두 SKILL.md 모두 완전한 본문. `<base-branch>` 같은 런타임 치환자는 스킬 실행 시 Claude가 채우는 명령 인자이며 설계 placeholder가 아님. plugin.json·README.md 완전한 내용. ✓

**일관성:** 플러그인 이름 `superpowers-improver`가 plugin.json `name`·marketplace.json `name`·디렉토리명·README 제목에서 일치. `dependencies: ["superpowers-base"]`가 Phase 1 플랜의 다른 페르소나 플러그인과 동일한 패턴. ✓
