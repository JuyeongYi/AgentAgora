# superpowers 워크플로 개정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** superpowers 페르소나 시스템에 `sp-tester`를 추가하고, 디버거·리뷰어를 흐름에 안정적으로 배선하며, 멤버별 사일런트/리액티브 모드와 에이전트 팀 규칙을 모든 페르소나에 더한다.

**Architecture:** 변경 대부분은 플러그인 콘텐츠다 — 페르소나 `SKILL.md`(마크다운), `plugin.json`/`marketplace.json`/`roles.json`(JSON), `comm-matrix.csv`(CSV). 코드(Python)는 건드리지 않는다. 신규 `superpowers-tester` 플러그인을 만들고 `test-driven-development` 스킬을 그쪽으로 이전한다. comm-matrix만 실제 회귀 테스트(`CommMatrix` 클래스 로드) 대상이고, 나머지는 JSON/frontmatter 검증으로 확인한다.

**Tech Stack:** Claude Code 플러그인(plugin.json·SKILL.md), AgentAgora `comm_matrix.CommMatrix`, pytest, JSON/CSV.

**근거 스펙:** `docs/superpowers/specs/2026-05-19-superpowers-workflow-revision-design.md` — 각 Task는 해당 spec 절을 참조한다.

**대상:** AgentAgora 레포의 `plugin/`·`docs/`. UeT3DRay 배포 마이그레이션(spec §9)은 이 플랜 범위 밖 — 별도 후속.

---

## 공유 콘텐츠 (모든 페르소나 Task가 사용)

아래 두 섹션은 7개 페르소나 `SKILL.md` 전부에 동일하게 들어간다. Task 4~9는 이 블록을 그대로 삽입한다.

**블록 A — Response mode** (`## Finding other members` 섹션 바로 앞에 삽입):

```markdown
## Response mode

기동 시 `Read`로 `../.superpower/response.json`을 확인한다 (배포 루트 = 이 워커 디렉터리의 부모). 파일에서 자신의 instance-id를 키로 모드를 찾는다.

- 파일이 없거나 자신의 instance-id 키가 없으면 → `silent` (기본값).
- `silent`: `AskUserQuestion`을 사용하지 않는다. 사용자 입력 없이 진행하고, 결정 분기와 사용자 게이트(승인·확인)를 추천 선택지로 자동 결정한다.
- `reactive`: `AskUserQuestion`을 적극 사용해 사용자에게 묻는다. 사용자 게이트는 사용자에게 확인한다.
```

**블록 B — Agent teams** (블록 A 바로 뒤에 삽입):

```markdown
## Agent teams

환경변수 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` 값이 `1`이고 맡은 임무가 병렬 분해 가능하면, 에이전트 팀으로 분할해 실행한다. `1`이 아니면 단일 에이전트로 진행한다.
```

---

## Task 1: `superpowers-tester` 플러그인 등록

**Files:**
- Create: `plugin/superpowers/superpowers-tester/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-tester/README.md`
- Modify: `plugin/.claude-plugin/marketplace.json`
- Modify: `plugin/cc-agora-ops/config/roles.json`

- [ ] **Step 1: plugin.json 작성**

`plugin/superpowers/superpowers-tester/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-tester",
  "description": "Superpowers tester persona — owns all test code: writes, runs, and analyzes tests in a TDD ping-pong with the implementer.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 2: README.md 작성**

`plugin/superpowers/superpowers-tester/README.md`:

```markdown
# superpowers-tester

AgentAgora tester 역할 페르소나 플러그인이다. 이 플러그인은 워커가 tester 역할(모든 테스트 코드의 작성·실행·결과 분석, 구현자와의 TDD 핑퐁)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-tester"`를 추가하면 페르소나가 적용된다.

​```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-tester@agent-agora": true
  }
}
​```
```

(위 코드블록의 ` ​``` `는 실제 파일에서 백틱 3개로 — README 안의 중첩 코드블록 표기다.)

- [ ] **Step 3: marketplace.json에 등록**

`plugin/.claude-plugin/marketplace.json`의 `plugins` 배열에서 `superpowers-improver` 항목 뒤에 추가:

```json
    {
      "name": "superpowers-tester",
      "source": "./superpowers/superpowers-tester",
      "description": "Superpowers tester persona — owns and analyzes all test code."
    }
```

- [ ] **Step 4: roles.json에 등록**

`plugin/cc-agora-ops/config/roles.json`에 `sp-improver` 항목 뒤에 추가:

```json
  "sp-tester":    { "plugin": "superpowers-tester" }
```

(앞 항목 줄 끝에 콤마를 빠뜨리지 않는다.)

- [ ] **Step 5: 검증**

Run: `python -c "import json; [json.load(open(p,encoding='utf-8')) for p in ['plugin/superpowers/superpowers-tester/.claude-plugin/plugin.json','plugin/.claude-plugin/marketplace.json','plugin/cc-agora-ops/config/roles.json']]; print('json ok')"`
Expected: `json ok`

Run: `python -c "import json; m=json.load(open('plugin/.claude-plugin/marketplace.json',encoding='utf-8')); assert any(p['name']=='superpowers-tester' for p in m['plugins']); r=json.load(open('plugin/cc-agora-ops/config/roles.json',encoding='utf-8')); assert r['sp-tester']['plugin']=='superpowers-tester'; print('registered ok')"`
Expected: `registered ok`

- [ ] **Step 6: Commit**

```bash
git add plugin/superpowers/superpowers-tester/ plugin/.claude-plugin/marketplace.json plugin/cc-agora-ops/config/roles.json
git commit -m "feat(superpowers): superpowers-tester 플러그인 등록"
```

---

## Task 2: `test-driven-development` 스킬을 테스터로 이전

**Files:**
- Move: `plugin/superpowers/superpowers-implementer/skills/test-driven-development/` → `plugin/superpowers/superpowers-tester/skills/test-driven-development/`

- [ ] **Step 1: 디렉터리 이전**

```bash
git mv plugin/superpowers/superpowers-implementer/skills/test-driven-development plugin/superpowers/superpowers-tester/skills/test-driven-development
```

- [ ] **Step 2: 스킬 frontmatter의 delegation-target 갱신**

`plugin/superpowers/superpowers-tester/skills/test-driven-development/SKILL.md`의 frontmatter에 `delegation-target`이 있으면 `sp-implementer`로 둔다 (TDD 핑퐁의 주 핸드오프 대상은 구현자). `delegation-schema`는 기존 값 유지. frontmatter에 해당 키가 없으면 추가하지 않는다 (기존 형식 보존).

- [ ] **Step 3: 검증**

Run: `test -d plugin/superpowers/superpowers-tester/skills/test-driven-development && test ! -d plugin/superpowers/superpowers-implementer/skills/test-driven-development && echo "moved ok"`
Expected: `moved ok`

- [ ] **Step 4: Commit**

```bash
git add -A plugin/superpowers/superpowers-implementer/skills plugin/superpowers/superpowers-tester/skills
git commit -m "refactor(superpowers): test-driven-development 스킬을 tester로 이전"
```

---

## Task 3: `analyzing-test-results` 신규 스킬

**Files:**
- Create: `plugin/superpowers/superpowers-tester/skills/analyzing-test-results/SKILL.md`

- [ ] **Step 1: SKILL.md 작성**

`plugin/superpowers/superpowers-tester/skills/analyzing-test-results/SKILL.md`:

```markdown
---
name: analyzing-test-results
description: Use when a test run produces failures - classify each failure and decide whether the implementer can fix it inline or it needs the debugger
model: opus
effort: high
delegation-target: "sp-implementer"
delegation-schema: "delegation_request"
---

# Analyzing Test Results

## Overview

테스트 실패는 종류가 다르다. 분류 없이 무작정 디버거로 넘기면 디버거가 과부하되고, 무작정 구현자에게 넘기면 구조적 문제가 패치로 가려진다. 이 스킬은 실패를 분류하고 다음 행선지를 정한다.

## 실패 분류

각 실패를 네 범주 중 하나로 판정한다:

1. **실제 버그** — 구현 코드가 명세대로 동작하지 않는다. 재현 가능하고 결정적.
2. **잘못된 테스트** — 테스트 자체가 틀렸다 (잘못된 기대값, 잘못된 셋업). 구현이 아니라 테스트를 고친다.
3. **플래키** — 같은 코드에서 통과·실패가 갈린다. 타이밍·순서·격리 문제.
4. **환경 요인** — 의존성 누락, 경로, 권한 등 코드 외부 원인.

## 행선지 결정

- **잘못된 테스트** → 테스터 자신이 테스트를 수정한다 (위임 없음).
- **단순한 실제 버그** (원인이 명확하고 국소적) → 구현자에게 `type=reply`로 반려, 실패 테스트·기대 동작·원인 추정을 포함.
- **원인 불명·구조적 실제 버그**, 또는 **플래키** → 디버거에게 `agora.dispatch` `type=task`로 위임. 에러·재현 절차·시도한 것을 포함.
- **환경 요인** → 구현자에게 보고하되 코드 문제 아님을 명시.

## 출력 규약

분석 결과는 항상 분류와 근거를 함께 적는다. "테스트 3건 실패"가 아니라 "테스트 3건 — 2건 실제 버그(단순, 구현자), 1건 플래키(디버거)"처럼 행선지까지 명시한다.

## 검증

`superpowers:verification-before-completion`을 따른다 — 실패를 분류했다고 주장하기 전에 실제 테스트 출력을 확인한다.
```

- [ ] **Step 2: 검증**

Run: `python -c "import re; t=open('plugin/superpowers/superpowers-tester/skills/analyzing-test-results/SKILL.md',encoding='utf-8').read(); m=re.match(r'^---\n.*?\n---\n', t, re.S); assert m and 'name: analyzing-test-results' in m.group(0); print('frontmatter ok')"`
Expected: `frontmatter ok`

- [ ] **Step 3: Commit**

```bash
git add plugin/superpowers/superpowers-tester/skills/analyzing-test-results
git commit -m "feat(superpowers): analyzing-test-results 스킬 추가"
```

---

## Task 4: 테스터 페르소나 SKILL.md

**Files:**
- Create: `plugin/superpowers/superpowers-tester/skills/persona/SKILL.md`

참조: 형식은 `plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md`와 동일한 템플릿(frontmatter / Mission / Response conventions / Role-specific knowledge / Response mode / Agent teams / Finding other members). 내용은 spec §4.1.

- [ ] **Step 1: SKILL.md 작성**

`plugin/superpowers/superpowers-tester/skills/persona/SKILL.md`:

```markdown
---
description: Tester persona for an AgentAgora worker — mission, working style, and handoff rules for a council member that owns all test code and analyzes test results.
user-invocable: false
---

# Tester persona

## Mission

모든 테스트 코드의 작성·실행·결과 분석을 전담한다. 구현자와 핑퐁하며 TDD 사이클을 구동한다 — 실패하는 테스트를 먼저 쓰고 실패를 직접 확인한 뒤 구현자에게 넘기고, 구현 완료 통보를 받으면 실행·분석한다. 어려운 실패는 디버거에게 위임한다. 테스트가 무엇을 검증하는지 모른 채 통과를 보고하지 않는다.

## Response conventions

### Forward convention

원 발신자에게만 답할 의무는 없다. 일이 도메인 밖이면(예: 구현 자체 → 구현자, 원인 추적 → 디버거) `agora.dispatch`로 적절한 페르소나에 넘긴다. 원 발신자에게 한 줄 ack("디버거에 위임") 권장 — 필수는 아니나 고아 task 방지.

### Flush entry convention

채널 알림(`<channel source="agora-channel">`)으로 깨어나면 `agora.flush`로 인박스를 드레인한다. 채널 모드 메시징 규칙은 `agora-protocol` 스킬을 따른다.

### cc message convention

`envelope.delivered_as='cc'` 메시지에는 답하지 않는다. 관측 신호로만 흡수한다.

### Payload standard

모든 발신 payload는 `{type, from, ts, message?}` 형식. `type` enum 4값: `task | reply | closing | ack`.

## Role-specific knowledge

### Owned skills

- `test-driven-development` — 실패하는 테스트를 먼저 쓰고, 실패를 직접 확인한 뒤에만 구현으로 넘긴다. 실패를 안 봤으면 그 테스트가 옳은 것을 검증하는지 알 수 없다.
- `analyzing-test-results` — 테스트 실행 결과를 읽고 실패를 분류(실제 버그/잘못된 테스트/플래키/환경)하며 행선지(구현자 vs 디버거)를 정한다.

### Hand-off edges

- **TDD 핑퐁** — 구현자에게서 task를 받으면 task별로: 실패 테스트 작성·실행(실패 확인) → 구현자에게 `type=reply`("테스트 준비, 실패 확인됨") → 구현 완료 통보 수신 → 실행·`analyzing-test-results`로 분석.
- **단순 실패** → 구현자에게 `type=reply`로 반려.
- **어려운 실패**(원인 불명·구조적·플래키) → 디버거에게 `agora.dispatch` `type=task`.
- **디버거 복귀 수신** → 수정본을 재검증(테스트 재실행)하고 핑퐁을 잇는다.
- 전 task가 green이면 구현자에게 `type=reply`로 통보한다 — 리뷰어로의 디스패치는 구현자가 한다.

### Working conventions

- Windows 환경에서 경로 리터럴은 forward slash. JSON 안 backslash는 hook 레이어에서 escape 충돌을 일으킨다.
- 테스트 코드도 작게 — 한 테스트는 한 동작을 검증한다.

## Response mode

(공유 콘텐츠 블록 A를 여기 삽입한다.)

## Agent teams

(공유 콘텐츠 블록 B를 여기 삽입한다.)

## Finding other members

등록된 워커는 `agora.instances`·`agora.find`로 동적 발견한다. 인스턴스 매핑을 페르소나에 하드코딩하지 않는다. 역할명(`implementer`, `debugger`)을 `agora.find` 조회 키로 쓴다.
```

작성 시 `## Response mode`·`## Agent teams` 자리에 공유 콘텐츠 블록 A·B의 본문을 그대로 채운다.

- [ ] **Step 2: 검증**

Run: `python -c "t=open('plugin/superpowers/superpowers-tester/skills/persona/SKILL.md',encoding='utf-8').read(); assert t.startswith('---'); assert 'user-invocable: false' in t; assert '## Response mode' in t and '## Agent teams' in t; print('persona ok')"`
Expected: `persona ok`

- [ ] **Step 3: Commit**

```bash
git add plugin/superpowers/superpowers-tester/skills/persona
git commit -m "feat(superpowers): tester 페르소나 SKILL.md"
```

---

## Task 5: 구현자 페르소나 SKILL.md 개정

**Files:**
- Modify: `plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md`
- Modify: `plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`

근거: spec §4.2.

- [ ] **Step 1: Owned skills에서 test-driven-development 제거**

`## Role-specific knowledge` → `### Owned skills`에서 `test-driven-development` 불릿을 삭제한다. 남는 소유 스킬: `executing-plans`, `using-git-worktrees`, `finishing-a-development-branch`.

- [ ] **Step 2: Hand-off edges 교체**

`### Hand-off edges` 하위 불릿 전체를 아래로 교체한다:

```markdown
- **task별 TDD 핑퐁** → **tester** 페르소나와 핑퐁(`agora.dispatch`). task마다 테스터에게 실패 테스트를 요청하고, 테스터가 준비하면 최소 구현으로 통과시킨 뒤 `type=reply`로 검증을 요청한다. 디버거로는 직접 보내지 않는다 — 실패 라우팅은 테스터가 맡는다.
- **전 task green** → **reviewer** 페르소나에 `agora.dispatch` `type=task`, diff/PR 링크 포함.
- **reviewer 승인 수신** → `finishing-a-development-branch`를 수행한 뒤 **improver** 페르소나에 `agora.dispatch` `type=closing`, 브랜치명·완료 요약 포함.
- **reviewer가 코드 레벨 이슈 반려** → 수정 후 다시 tester 핑퐁으로 재검증.
```

- [ ] **Step 3: Mission에서 TDD 주체 표현 조정**

`## Mission`의 "Use TDD — write the failing test first..." 문장을 "구현 코드를 작성한다. 테스트 작성·검증은 tester 페르소나가 맡으며, task마다 tester와 핑퐁한다."로 바꾼다. 나머지 Mission 문장(worktree, finishing-a-development-branch, 추측 금지)은 유지.

- [ ] **Step 4: 공유 블록 삽입**

`## Finding other members` 바로 앞에 공유 콘텐츠 블록 A(`## Response mode`)와 블록 B(`## Agent teams`)를 삽입한다.

- [ ] **Step 5: plugin.json description 갱신**

`plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`의 `description`을 `"Superpowers implementer persona — writes implementation code in a TDD ping-pong with the tester, in isolated worktrees, with clean branch completion."`로 바꾼다.

- [ ] **Step 6: 검증**

Run: `python -c "t=open('plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md',encoding='utf-8').read(); assert 'test-driven-development' not in t; assert '## Response mode' in t and '## Agent teams' in t; assert 'reviewer' in t and 'tester' in t; print('implementer ok')"`
Expected: `implementer ok`

Run: `python -c "import json; json.load(open('plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json',encoding='utf-8')); print('json ok')"`
Expected: `json ok`

- [ ] **Step 7: Commit**

```bash
git add plugin/superpowers/superpowers-implementer
git commit -m "refactor(superpowers): implementer — TDD를 tester로 이양, 핸드오프 개정"
```

---

## Task 6: 리뷰어 페르소나 SKILL.md 개정

**Files:**
- Modify: `plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md`

근거: spec §4.3.

- [ ] **Step 1: Mission 교체**

`## Mission` 본문을 아래로 교체한다:

```markdown
구현자에게서 리뷰 요청을 받아 코드를 *읽고* 판단한다 — 정확성(추론), 가독성, 유지보수성, 그리고 코드 구조/아키텍처. 테스트 결과는 입력 컨텍스트로만 참고하며 커버리지 분석은 하지 않는다(그건 tester 영역). 테스터가 "동작하나?"를 본다면 리뷰어는 "잘 만들었나?"를 본다. "간단하니까" 리뷰를 건너뛰지 않는다. 모든 지적에 file:line과 근거를 단다.
```

- [ ] **Step 2: Role-specific knowledge의 출력 분기 교체**

기존 "After review is complete, dispatch back to the implementer..." 불릿을 아래 분기로 교체한다:

```markdown
- 리뷰 결과는 세 갈래로 나간다:
  - **코드 레벨 이슈**(국소 수정 가능) → 구현자에게 `agora.dispatch` `type=reply`. Critical/Important/Minor + 각 file:line·근거·제안.
  - **구조/아키텍처 문제**(국소 수정 불가) → 플래너에게 `agora.dispatch` `type=task`. 구조 문제 요약. 리뷰어가 구조 문제를 발견하면 구현자가 아니라 플래너로 보낸다.
  - **승인** → 구현자에게 `agora.dispatch` `type=reply`. 구현자가 `finishing-a-development-branch`를 진행한다.
```

기존 "test coverage"를 리뷰 항목으로 적은 부분이 있으면 제거한다 — 커버리지는 tester 책임이다.

- [ ] **Step 3: 공유 블록 삽입**

`## Finding other members` 바로 앞에 공유 콘텐츠 블록 A·B를 삽입한다.

- [ ] **Step 4: 검증**

Run: `python -c "t=open('plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md',encoding='utf-8').read(); assert '플래너' in t and '구조' in t; assert '## Response mode' in t and '## Agent teams' in t; print('reviewer ok')"`
Expected: `reviewer ok`

- [ ] **Step 5: Commit**

```bash
git add plugin/superpowers/superpowers-reviewer
git commit -m "refactor(superpowers): reviewer — 구조 판독으로 재정의, planner 에스컬레이션 추가"
```

---

## Task 7: 디버거 페르소나 SKILL.md + systematic-debugging 개정

**Files:**
- Modify: `plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md`
- Modify: `plugin/superpowers/superpowers-debugger/skills/systematic-debugging/SKILL.md`

근거: spec §4.4.

- [ ] **Step 1: 페르소나 Mission·핸드오프 교체**

`## Mission`의 "Receive a bug ... dispatched by the implementer" → "dispatched by the tester"로, "hand control back to the implementer" → "hand control back to the tester"로 바꾼다.

`## Role-specific knowledge`에서:
- "Receives from implementer" 불릿 → "**Receives from tester**: 테스터가 `analyzing-test-results`로 어려운 실패(원인 불명·구조적·플래키)를 판정해 `agora.dispatch` `type=task`로 위임한다."
- "Returns to implementer" 불릿 → "**Returns to tester**: 수정·검증(테스트 통과) 후 테스터에게 `type=reply`로 복귀. 테스터가 전체 테스트를 재검증한다."
- "3+ fix attempts" 불릿 → 아키텍처 문제 진단 시 구현자가 아니라 **플래너**에게 `agora.dispatch` `type=task`로 에스컬레이션하도록 바꾼다.

- [ ] **Step 2: 공유 블록 삽입**

`## Finding other members` 바로 앞에 공유 콘텐츠 블록 A·B를 삽입한다.

- [ ] **Step 3: systematic-debugging 스킬의 delegation-target 갱신**

`plugin/superpowers/superpowers-debugger/skills/systematic-debugging/SKILL.md` frontmatter의 `delegation-target: "sp-implementer"`를 `delegation-target: "sp-tester"`로 바꾼다. `delegation-schema`는 유지.

- [ ] **Step 4: 검증**

Run: `python -c "t=open('plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md',encoding='utf-8').read(); assert 'tester' in t and '플래너' in t; assert '## Response mode' in t and '## Agent teams' in t; s=open('plugin/superpowers/superpowers-debugger/skills/systematic-debugging/SKILL.md',encoding='utf-8').read(); assert 'delegation-target: \"sp-tester\"' in s; print('debugger ok')"`
Expected: `debugger ok`

- [ ] **Step 5: Commit**

```bash
git add plugin/superpowers/superpowers-debugger
git commit -m "refactor(superpowers): debugger — tester 경유로 배선, 구조 문제는 planner로"
```

---

## Task 8: 플래너 페르소나 SKILL.md 개정

**Files:**
- Modify: `plugin/superpowers/superpowers-planner/skills/persona/SKILL.md`

근거: spec §4.5.

- [ ] **Step 1: 진입점 확장**

`## Role-specific knowledge`의 "Entry point" 불릿을 아래로 교체한다:

```markdown
- **Entry point**: planner는 superpowers 워크플로의 첫 페르소나다. 진입 트리거는 셋 — (1) 새 유저 아이디어, (2) improver의 `findings` payload, (3) reviewer·debugger의 구조 에스컬레이션. 구조 에스컬레이션을 받으면 그 구조 문제를 brainstorming의 "아이디어"로 취급해 새 사이클을 연다.
```

"Receiving from improver" 불릿은 유지하되, 같은 방식으로 reviewer/debugger 구조 에스컬레이션도 brainstorming 입력으로 다룬다는 한 문장을 더한다.

- [ ] **Step 2: 공유 블록 삽입**

`## Finding other members` 바로 앞에 공유 콘텐츠 블록 A·B를 삽입한다.

- [ ] **Step 3: 검증**

Run: `python -c "t=open('plugin/superpowers/superpowers-planner/skills/persona/SKILL.md',encoding='utf-8').read(); assert '에스컬레이션' in t; assert '## Response mode' in t and '## Agent teams' in t; print('planner ok')"`
Expected: `planner ok`

- [ ] **Step 4: Commit**

```bash
git add plugin/superpowers/superpowers-planner
git commit -m "refactor(superpowers): planner — reviewer·debugger 구조 에스컬레이션 진입점 추가"
```

---

## Task 9: 라우터·임프루버 페르소나 — 공유 블록만 추가

**Files:**
- Modify: `plugin/superpowers/superpowers-router/skills/persona/SKILL.md`
- Modify: `plugin/superpowers/superpowers-improver/skills/persona/SKILL.md`

router·improver는 책임 변경은 없고 공유 블록만 더한다.

- [ ] **Step 1: router에 공유 블록 삽입**

`superpowers-router/skills/persona/SKILL.md`의 `## Finding other members` 바로 앞에 공유 콘텐츠 블록 A·B를 삽입한다.

- [ ] **Step 2: improver에 공유 블록 삽입**

`superpowers-improver/skills/persona/SKILL.md`의 `## Finding other members` 바로 앞에 공유 콘텐츠 블록 A·B를 삽입한다.

- [ ] **Step 3: 검증**

Run: `python -c "[exec(\"t=open('plugin/superpowers/superpowers-%s/skills/persona/SKILL.md'%r,encoding='utf-8').read(); assert '## Response mode' in t and '## Agent teams' in t\") for r in ['router','improver']]; print('router+improver ok')"`
Expected: `router+improver ok`

- [ ] **Step 4: Commit**

```bash
git add plugin/superpowers/superpowers-router plugin/superpowers/superpowers-improver
git commit -m "feat(superpowers): router·improver에 Response mode·Agent teams 규칙 추가"
```

---

## Task 10: comm-matrix.csv 8×8 재작성 + 회귀 테스트

**Files:**
- Modify: `plugin/superpowers/routing-bot/comm-matrix.csv`
- Create: `tests/test_superpowers_comm_matrix.py`

근거: spec §5.

- [ ] **Step 1: 회귀 테스트 작성 (실패 예정)**

`CommMatrix` API는 `tests/test_v4_comm_matrix.py`를 읽어 확인한다 (로드·`is_allowed`/`weight_of` 사용법). `tests/test_superpowers_comm_matrix.py`:

```python
"""superpowers routing-bot comm-matrix.csv 회귀 테스트 — 개정 워크플로 엣지 검증."""
from pathlib import Path

from agent_agora.comm_matrix import CommMatrix

_CSV = (Path(__file__).resolve().parent.parent
        / "plugin" / "superpowers" / "routing-bot" / "comm-matrix.csv")


def _matrix() -> CommMatrix:
    # CommMatrix 로드 방식은 tests/test_v4_comm_matrix.py와 동일하게 맞춘다.
    return CommMatrix.load_csv(_CSV.read_text(encoding="utf-8"))


# (from_id, to_id) 허용돼야 하는 엣지
_ALLOWED = [
    ("sp-planner-1", "sp-router-1"),
    ("sp-router-1", "sp-implementer-1"),
    ("sp-implementer-1", "sp-tester-1"),
    ("sp-tester-1", "sp-implementer-1"),
    ("sp-tester-1", "sp-debugger-1"),
    ("sp-debugger-1", "sp-tester-1"),
    ("sp-debugger-1", "sp-planner-1"),
    ("sp-implementer-1", "sp-reviewer-1"),
    ("sp-reviewer-1", "sp-implementer-1"),
    ("sp-reviewer-1", "sp-planner-1"),
    ("sp-implementer-1", "sp-improver-1"),
    ("sp-improver-1", "sp-planner-1"),
]

# 허용되면 안 되는 엣지 (개정 설계에서 제거/미존재)
_FORBIDDEN = [
    ("sp-implementer-1", "sp-debugger-1"),   # 구현자는 디버거로 직접 안 보냄
    ("sp-debugger-1", "sp-implementer-1"),   # 디버거는 테스터로 복귀
    ("sp-tester-1", "sp-reviewer-1"),        # 리뷰 디스패치는 구현자가 함
]


def test_revised_workflow_allowed_edges():
    m = _matrix()
    for frm, to in _ALLOWED:
        assert m.is_allowed(frm, to), f"엣지 허용돼야 함: {frm} -> {to}"


def test_revised_workflow_forbidden_edges():
    m = _matrix()
    for frm, to in _FORBIDDEN:
        assert not m.is_allowed(frm, to), f"엣지 금지돼야 함: {frm} -> {to}"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_superpowers_comm_matrix.py -v`
Expected: FAIL — 현재 `comm-matrix.csv`는 7×7이라 `sp-tester-*` 매칭·신규 엣지가 없다.

- [ ] **Step 3: comm-matrix.csv를 8×8로 교체**

`plugin/superpowers/routing-bot/comm-matrix.csv` 전체를 아래로 교체한다 (행=수신자, 열=발신자):

```
sp-planner-.*,sp-router-.*,sp-implementer-.*,sp-tester-.*,sp-debugger-.*,sp-reviewer-.*,sp-improver-.*,(?!sp-).*
0,0,0,0,1,1,1,0
1,0,0,0,0,0,0,0
0,1,0,1,0,1,0,0
0,0,1,0,1,0,0,0
0,0,0,1,0,0,0,0
0,0,1,0,0,0,0,0
0,0,1,0,0,0,0,0
0,0,0,0,0,0,0,1
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_superpowers_comm_matrix.py -v`
Expected: PASS — 2개 테스트 통과.

- [ ] **Step 5: Commit**

```bash
git add plugin/superpowers/routing-bot/comm-matrix.csv tests/test_superpowers_comm_matrix.py
git commit -m "feat(superpowers): comm-matrix 8x8 — sp-tester 추가, 개정 워크플로 엣지"
```

---

## Task 11: README 워크플로 갱신

**Files:**
- Modify: `plugin/superpowers/README.md`

- [ ] **Step 1: 워크플로 다이어그램 교체**

`plugin/superpowers/README.md`의 `## 워크플로` 아래 ASCII 다이어그램을 spec §3의 다이어그램으로 교체한다 (planner → router → implementer ⇄ tester → debugger/reviewer → improver, reviewer·debugger의 planner 에스컬레이션 포함).

- [ ] **Step 2: 구성 표에 tester 행 추가**

`## 구성` 표에 `superpowers-tester` 행을 추가한다:

```markdown
| `superpowers-tester` | `plugin/superpowers/superpowers-tester/` | test-driven-development + analyzing-test-results — 모든 테스트 코드 작성·실행·결과 분석, 구현자와 핑퐁 |
```

`superpowers-implementer` 행 설명에서 `test-driven-development`를 빼고 "구현 코드 전담, 테스터와 핑퐁"으로 조정한다.

- [ ] **Step 3: 워커 spawn 예시에 tester 추가**

`### 5단계. 페르소나 워커 spawn`의 예시 명령 목록에 한 줄 추가:

```
/cc-agora-ops:agora-spawn sp-tester-1 sp-tester "superpowers 테스터"
```

- [ ] **Step 4: 검증**

Run: `python -c "t=open('plugin/superpowers/README.md',encoding='utf-8').read(); assert 'superpowers-tester' in t and 'sp-tester' in t; print('readme ok')"`
Expected: `readme ok`

- [ ] **Step 5: Commit**

```bash
git add plugin/superpowers/README.md
git commit -m "docs(superpowers): README 워크플로·구성에 tester 반영"
```

---

## Task 12: 전체 검증

**Files:** 없음 (검증 전용)

- [ ] **Step 1: 전체 테스트 스위트**

Run: `python -m pytest tests/ -v`
Expected: 전부 PASS — 신규 `test_superpowers_comm_matrix.py` 포함, 기존 테스트 회귀 없음. (Python 3.13 환경. `.venv`가 3.13이면 `.venv/Scripts/python.exe -m pytest tests/ -v`, 아니면 `uv run --python 3.13 --extra dev pytest tests/ -v`.)

- [ ] **Step 2: 플러그인 구조 검증**

Run: `python -c "import json,glob; [json.load(open(p,encoding='utf-8')) for p in glob.glob('plugin/**/.claude-plugin/*.json',recursive=True)]; print('all plugin json ok')"`
Expected: `all plugin json ok`

마켓플레이스 16→17개 플러그인(superpowers-tester 추가) 확인:
Run: `python -c "import json; m=json.load(open('plugin/.claude-plugin/marketplace.json',encoding='utf-8')); print(len(m['plugins']),'plugins'); assert any(p['name']=='superpowers-tester' for p in m['plugins'])"`
Expected: `17 plugins`

- [ ] **Step 3: 페르소나 7종 일관성**

Run: `python -c "import glob; ps=sorted(glob.glob('plugin/superpowers/superpowers-*/skills/persona/SKILL.md')); assert len(ps)==7, f'{len(ps)} persona files'; [open(p,encoding='utf-8').read().count('## Response mode') and open(p,encoding='utf-8').read().count('## Agent teams') for p in ps]; print('7 personas, all have shared blocks')"`
Expected: `7 personas, all have shared blocks`

- [ ] **Step 4: 최종 커밋 (스텝에서 누락분 있을 시)**

```bash
git status --short
```
출력이 비어 있어야 한다. 누락분이 있으면 해당 Task로 돌아가 정리한다.

---

## Self-Review

- **Spec coverage:** §3 워크플로 → Task 5~10·11; §4.1 tester → Task 1·3·4; §4.2 implementer → Task 5; §4.3 reviewer → Task 6; §4.4 debugger → Task 7; §4.5 planner → Task 8; §5 comm-matrix → Task 10; §6 Response mode → Task 4~9(공유 블록 A); §7 agent teams → Task 4~9(공유 블록 B); §8 파일 영향 → 전 Task; §2 신규 스킬 → Task 3. §9 배포 마이그레이션은 의도적으로 범위 밖.
- **Placeholder scan:** 신규 파일은 전문(全文) 수록. 수정 파일은 정확한 절·교체 텍스트 명시. 공유 블록은 상단에 1회 정의 후 Task가 "삽입"으로 참조 — subagent 디스패치 시 컨트롤러가 본문을 채워 전달한다.
- **Type consistency:** 페르소나명(`sp-tester`)·플러그인명(`superpowers-tester`)·스킬명(`analyzing-test-results`·`test-driven-development`)·comm-matrix 헤더 패턴이 전 Task에서 일관.
