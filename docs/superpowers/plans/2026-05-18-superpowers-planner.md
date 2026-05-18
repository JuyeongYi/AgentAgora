# superpowers-planner 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `superpowers-planner` 페르소나 플러그인을 생성한다 — brainstorming + writing-plans 스킬을 보유하고, 아이디어(또는 improver의 findings)를 spec + 구현 플랜으로 전환한 뒤 router 페르소나로 핸드오프하는 워크플로 진입점 워커.

**Architecture:** spec §3·§4에 따라 `plugin/superpowers/superpowers-planner/` 하위에 `.claude-plugin/plugin.json`·`README.md`·`skills/persona/SKILL.md`·`skills/brainstorming/`·`skills/writing-plans/`를 배치한다. 스킬 디렉토리는 `C:/Users/jylee/source/superpowers_model_specified/skills/<name>/`에서 `cp -r`로 통째 복사하고, `plugin/.claude-plugin/marketplace.json`에 플러그인을 등록하는 것으로 플러그인을 완성한다. 동작 검증은 manifest 구조 검사 + pytest `test_plugin_marketplace.py`로 수행하며 행동 스킬 테스트는 §13에 따라 이 플랜 범위 밖이다.

**Tech Stack:** Claude Code 플러그인, pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-planner/
  .claude-plugin/
    plugin.json                   # 플러그인 메타, dependencies: ["superpowers-base"]
  README.md                       # 한국어 설명 ~10줄
  skills/
    persona/
      SKILL.md                    # planner 페르소나 정의 (신규 작성)
    brainstorming/
      SKILL.md                    # 원본 복사
      visual-companion.md         # 원본 복사
      spec-document-reviewer-prompt.md  # 원본 복사
      scripts/                    # visual-companion Node 서버 통째 복사
        frame-template.html
        helper.js
        server.cjs
        start-server.sh
        stop-server.sh
    writing-plans/
      SKILL.md                    # 원본 복사
      plan-document-reviewer-prompt.md  # 원본 복사

plugin/.claude-plugin/marketplace.json   # 기존 파일에 항목 추가
```

---

## Task 1: 플러그인 scaffolding — plugin.json + README.md

**Files:**
- Create: `plugin/superpowers/superpowers-planner/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-planner/README.md`

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p "plugin/superpowers/superpowers-planner/.claude-plugin"
mkdir -p "plugin/superpowers/superpowers-planner/skills/persona"
```

- [ ] **Step 2: plugin.json 작성**

`plugin/superpowers/superpowers-planner/.claude-plugin/plugin.json` 전체 내용:

```json
{
  "name": "superpowers-planner",
  "description": "Superpowers planner persona — turns ideas into approved specs and bite-sized implementation plans.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 3: README.md 작성**

`plugin/superpowers/superpowers-planner/README.md` 전체 내용:

```markdown
# superpowers-planner

AgentAgora superpowers planner 역할 페르소나 플러그인이다. 이 플러그인은 워커가 planner 역할(아이디어 → spec → 구현 플랜 → router 핸드오프)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 워크플로 스킬(`using-superpowers`, `verification-before-completion`, `writing-skills`)은 `superpowers-base`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-planner"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-planner@agent-agora": true
  }
}
```

## 워크플로 위치

```
planner (brainstorming → writing-plans)
   │
   ▼  agora.dispatch → router
```

planner는 워크플로 진입점이다. 유저의 아이디어 또는 improver의 findings를 받아 brainstorming → writing-plans 순으로 실행하고, 완성된 플랜을 router 페르소나로 위임한다.
```

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-planner/.claude-plugin/plugin.json
git add plugin/superpowers/superpowers-planner/README.md
git commit -m "feat(superpowers-planner): scaffold plugin.json and README"
```

---

## Task 2: persona/SKILL.md 작성

**Files:**
- Create: `plugin/superpowers/superpowers-planner/skills/persona/SKILL.md`

- [ ] **Step 1: SKILL.md 작성**

`plugin/superpowers/superpowers-planner/skills/persona/SKILL.md` 전체 내용:

```markdown
---
description: Planner persona for an AgentAgora worker — mission, working style, and handoff rules for a council member that turns ideas into approved specs and bite-sized implementation plans.
user-invocable: false
---

# Planner persona

## Mission

Turn received ideas (or improvement findings from the improver) into an approved design spec and a bite-sized implementation plan. Run `brainstorming` first to reach user-approved spec, then run `writing-plans` to produce the plan. Forward the completed plan to the router persona via `agora.dispatch`. Never skip the user approval gate — wait for explicit approval before moving from brainstorming to writing-plans, and again before dispatching to router.

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. If the nature of the work falls outside your domain (e.g. debugging, code review, test writing), use `/invoke <other> "<task>"` to hand it off. Sending the originator a one-line ack ("delegated to X") is recommended to prevent orphaned tasks — not mandatory; use your judgment.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain your inbox with `agora.flush`. See the `agora-protocol` skill for full channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type` enum has four values: `task | reply | closing | ack`. Use `type=reply` for task responses, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

- **Entry point**: planner is the first persona in the superpowers workflow. Incoming triggers are either a fresh user idea or a `findings` payload from the improver persona.
- **Skill sequence**: always run skills in order — `brainstorming` first (produces user-approved spec), then `writing-plans` (produces implementation plan). Do not run writing-plans before the spec is approved.
- **User approval gates**: two hard gates exist — (1) user must approve the spec before writing-plans starts; (2) user must confirm the plan before dispatching to router. Never skip either gate.
- **Handoff target**: after the plan is approved, dispatch to the **router** persona via `agora.dispatch`. The payload must include `{type: "task", from: "planner", ts: <ISO timestamp>, message: <plan file path or plan content summary>}`. The router decides whether to execute sequentially (`subagent-driven-development`) or in parallel (`dispatching-parallel-agents`).
- **Receiving from improver**: if the incoming payload contains a `findings` key (improvement opportunities from the improver), pass the findings as context to brainstorming — treat them as the "idea" for a new iteration. The brainstorming checklist still applies in full.
- **No implementation**: planner does not write code. If a message asks for implementation, forward it to router with a one-line ack.
- **Spec location**: write specs to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and commit before proceeding to writing-plans.
- **Plan location**: write plans to `docs/superpowers/plans/YYYY-MM-DD-<topic>.md` and commit before dispatching to router.

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or `agora.find`. Do not hard-code instance mappings in the persona.
```

- [ ] **Step 2: 커밋**

```bash
git add plugin/superpowers/superpowers-planner/skills/persona/SKILL.md
git commit -m "feat(superpowers-planner): author planner persona SKILL.md"
```

---

## Task 3: brainstorming + writing-plans 스킬 복사

**Files:**
- Create: `plugin/superpowers/superpowers-planner/skills/brainstorming/` (디렉토리 전체)
- Create: `plugin/superpowers/superpowers-planner/skills/writing-plans/` (디렉토리 전체)

원본 경로: `C:/Users/jylee/source/superpowers_model_specified/skills/`

- [ ] **Step 1: brainstorming 스킬 통째 복사 (scripts/ 포함)**

```bash
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/brainstorming" \
      "plugin/superpowers/superpowers-planner/skills/brainstorming"
```

복사 결과 확인 (아래 파일이 모두 있어야 함):

```
plugin/superpowers/superpowers-planner/skills/brainstorming/
  SKILL.md
  visual-companion.md
  spec-document-reviewer-prompt.md
  scripts/
    frame-template.html
    helper.js
    server.cjs
    start-server.sh
    stop-server.sh
```

```bash
ls plugin/superpowers/superpowers-planner/skills/brainstorming/
ls plugin/superpowers/superpowers-planner/skills/brainstorming/scripts/
```

Expected: 위 파일 목록이 표시됨.

- [ ] **Step 2: writing-plans 스킬 통째 복사**

```bash
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/writing-plans" \
      "plugin/superpowers/superpowers-planner/skills/writing-plans"
```

복사 결과 확인:

```
plugin/superpowers/superpowers-planner/skills/writing-plans/
  SKILL.md
  plan-document-reviewer-prompt.md
```

```bash
ls plugin/superpowers/superpowers-planner/skills/writing-plans/
```

Expected: `SKILL.md`와 `plan-document-reviewer-prompt.md`가 표시됨.

- [ ] **Step 3: 커밋**

```bash
git add plugin/superpowers/superpowers-planner/skills/brainstorming/
git add plugin/superpowers/superpowers-planner/skills/writing-plans/
git commit -m "feat(superpowers-planner): copy brainstorming and writing-plans skills from superpowers_model_specified"
```

---

## Task 4: marketplace.json 등록

**Files:**
- Modify: `plugin/.claude-plugin/marketplace.json`

- [ ] **Step 1: marketplace.json 현재 내용 확인**

```bash
cat plugin/.claude-plugin/marketplace.json
```

현재 `"plugins"` 배열의 마지막 항목을 확인한다.

- [ ] **Step 2: superpowers-planner 항목 추가**

`plugin/.claude-plugin/marketplace.json`의 `"plugins"` 배열 맨 끝에 다음 항목을 추가한다 (기존 마지막 항목 뒤에 쉼표 추가 후 삽입):

```json
{
  "name": "superpowers-planner",
  "source": "./superpowers/superpowers-planner",
  "description": "Superpowers planner persona — ideas into specs and plans."
}
```

추가 후 전체 파일이 유효한 JSON인지 검증:

```bash
python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json')); print('JSON valid')"
```

Expected: `JSON valid`

- [ ] **Step 3: 커밋**

```bash
git add plugin/.claude-plugin/marketplace.json
git commit -m "feat(superpowers-planner): register in marketplace.json"
```

---

## Task 5: 검증

- [ ] **Step 1: 디렉토리 구조 전체 확인**

```bash
ls plugin/superpowers/superpowers-planner/
ls plugin/superpowers/superpowers-planner/.claude-plugin/
ls plugin/superpowers/superpowers-planner/skills/
ls plugin/superpowers/superpowers-planner/skills/persona/
ls plugin/superpowers/superpowers-planner/skills/brainstorming/
ls plugin/superpowers/superpowers-planner/skills/brainstorming/scripts/
ls plugin/superpowers/superpowers-planner/skills/writing-plans/
```

Expected 목록:
- `.claude-plugin/` · `README.md` · `skills/`
- `plugin.json`
- `persona/` · `brainstorming/` · `writing-plans/`
- `SKILL.md`
- `SKILL.md` · `visual-companion.md` · `spec-document-reviewer-prompt.md` · `scripts/`
- `frame-template.html` · `helper.js` · `server.cjs` · `start-server.sh` · `stop-server.sh`
- `SKILL.md` · `plan-document-reviewer-prompt.md`

- [ ] **Step 2: plugin.json JSON 유효성 확인**

```bash
python -c "import json; d=json.load(open('plugin/superpowers/superpowers-planner/.claude-plugin/plugin.json')); assert d['name']=='superpowers-planner'; assert d['dependencies']==['superpowers-base']; print('plugin.json OK')"
```

Expected: `plugin.json OK`

- [ ] **Step 3: marketplace.json JSON 유효성 + 항목 존재 확인**

```bash
python -c "
import json
d = json.load(open('plugin/.claude-plugin/marketplace.json'))
names = [p['name'] for p in d['plugins']]
assert 'superpowers-planner' in names, f'superpowers-planner not found in {names}'
entry = next(p for p in d['plugins'] if p['name']=='superpowers-planner')
assert entry['source'] == './superpowers/superpowers-planner'
print('marketplace.json OK — superpowers-planner registered')
"
```

Expected: `marketplace.json OK — superpowers-planner registered`

- [ ] **Step 4: pytest test_plugin_marketplace 실행**

```bash
uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q
```

Expected: 전체 PASSED (실패 없음).

- [ ] **Step 5: persona SKILL.md user-invocable 플래그 확인**

```bash
python -c "
content = open('plugin/superpowers/superpowers-planner/skills/persona/SKILL.md').read()
assert 'user-invocable: false' in content
assert '## Mission' in content
assert '## Response conventions' in content
assert '## Role-specific knowledge' in content
assert '## Finding other members' in content
print('persona SKILL.md structure OK')
"
```

Expected: `persona SKILL.md structure OK`

---

## Self-Review

spec §12 Plan 2 대비 체크:

| 요구사항 | 태스크 | 상태 |
|---|---|---|
| `.claude-plugin/plugin.json` with `dependencies: ["superpowers-base"]` | Task 1 | - [ ] |
| `README.md` (Korean, ~10줄, coder README 스타일) | Task 1 | - [ ] |
| `skills/persona/SKILL.md` (신규 작성, coder 패턴 일치) | Task 2 | - [ ] |
| `skills/brainstorming/` 디렉토리 통째 복사 (scripts/ 포함) | Task 3 | - [ ] |
| `skills/writing-plans/` 디렉토리 통째 복사 | Task 3 | - [ ] |
| `plugin/.claude-plugin/marketplace.json` 항목 추가 | Task 4 | - [ ] |
| pytest test_plugin_marketplace 통과 | Task 5 | - [ ] |
| spec §9 워크플로 역할 — brainstorming→writing-plans→router dispatch | Task 2 (SKILL.md) | - [ ] |
| spec §7 improver→planner 재순환 수신 처리 | Task 2 (SKILL.md) | - [ ] |
