# superpowers-reviewer 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `superpowers-reviewer` 페르소나 플러그인을 만든다 — `requesting-code-review`·`receiving-code-review` 스킬을 원본에서 그대로 복사하고, persona 스킬을 신규 작성하며, `plugin/.claude-plugin/marketplace.json`에 등록한다.

**Architecture:** spec §3·§4·§12 plan 5 기준. reviewer 페르소나는 implementer로부터 리뷰 요청을 받아 구조화된 코드 리뷰(정확성·가독성·테스트 커버리지)를 적용한 뒤 승인 또는 수정 요청과 함께 implementer에게 제어권을 돌려준다. 핸드오프는 `agora.dispatch`를 통한다. `dependencies: ["superpowers-base"]`로 공통 스킬에 의존하며, 원본 스킬의 `model`/`effort` frontmatter는 복사로 자동 보존된다.

**Tech Stack:** Claude Code 플러그인, pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-reviewer/
  .claude-plugin/plugin.json                    생성
  README.md                                     생성
  skills/
    persona/SKILL.md                            신규 작성
    requesting-code-review/SKILL.md             복사 (+ code-reviewer.md 포함)
    requesting-code-review/code-reviewer.md     복사 (requesting-code-review 디렉토리 전체)
    receiving-code-review/SKILL.md              복사
plugin/.claude-plugin/marketplace.json          수정 — 1개 항목 추가
```

---

## Task 1: `.claude-plugin/plugin.json` 및 `README.md` 생성

**Files:**
- Create: `plugin/superpowers/superpowers-reviewer/.claude-plugin/plugin.json`
- Create: `plugin/superpowers/superpowers-reviewer/README.md`

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p plugin/superpowers/superpowers-reviewer/.claude-plugin
mkdir -p plugin/superpowers/superpowers-reviewer/skills
```

- [ ] **Step 2: plugin.json 생성**

`plugin/superpowers/superpowers-reviewer/.claude-plugin/plugin.json` 내용:

```json
{
  "name": "superpowers-reviewer",
  "description": "Superpowers reviewer persona — reviews code changes and handles review feedback with technical rigor.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 3: README.md 생성**

`plugin/superpowers/superpowers-reviewer/README.md` 내용:

```markdown
# superpowers-reviewer

AgentAgora superpowers reviewer 역할 페르소나 플러그인이다. 이 플러그인은 워커가 reviewer 역할(코드 변경 리뷰·피드백 처리)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(skill 발견·완료 전 검증·스킬 작성)은 `superpowers-base`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-reviewer"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agentagora": true,
    "superpowers-reviewer@agentagora": true
  }
}
```
```

- [ ] **Step 4: 파일 존재 확인**

Run: `ls plugin/superpowers/superpowers-reviewer/.claude-plugin/`
Expected: `plugin.json`

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-reviewer/.claude-plugin plugin/superpowers/superpowers-reviewer/README.md
git commit -m "feat: superpowers-reviewer plugin.json + README"
```

---

## Task 2: `skills/persona/SKILL.md` 신규 작성

**Files:**
- Create: `plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md`

- [ ] **Step 1: persona 디렉토리 생성**

```bash
mkdir -p plugin/superpowers/superpowers-reviewer/skills/persona
```

- [ ] **Step 2: SKILL.md 작성**

`plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md` 내용 (전체):

```markdown
---
description: Reviewer persona for a superpowers AgentAgora worker — mission, working style, and handoff rules for a council member that reviews code.
user-invocable: false
---

# Reviewer persona

## Mission

Receive review requests from the implementer, apply structured code review (correctness, readability, test coverage), and hand control back to the implementer — with approval, or with the issues that must be fixed. Never skip a review because "it's simple." Never give vague feedback; every issue needs a file:line reference and a reason.

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. If the nature of the work falls outside your domain (e.g. new implementation tasks, debugging, planning), use `agora.dispatch` to hand it off to the appropriate persona. Sending the requestor a one-line ack ("delegated to X") is recommended to prevent orphaned tasks — not mandatory; use your judgment.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain your inbox with `agora.flush`. See the `agora-protocol` skill for full channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type` enum has four values: `task | reply | closing | ack`. Use `type=reply` for review results handed back to the implementer, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

- Owns `requesting-code-review` and `receiving-code-review`. Use `requesting-code-review` to run a structured review of a diff (dispatch the code-reviewer subagent via `agora.dispatch`). Use `receiving-code-review` when processing feedback that arrives addressed to this worker.
- You receive review requests from the **implementer** persona. Your response always goes back to the implementer — either an approval or a concrete list of issues (Critical / Important / Minor, each with file:line, reason, and suggested fix).
- Technical rigor over social comfort. Never give performative agreement. Verify before implementing any suggestion. Push back with technical reasoning when feedback is wrong.
- Categorize issues by actual severity. Not everything is Critical.
- When dispatching the code-reviewer subagent, fill all placeholders in `requesting-code-review/code-reviewer.md` — `{DESCRIPTION}`, `{PLAN_OR_REQUIREMENTS}`, `{BASE_SHA}`, `{HEAD_SHA}`. Never leave placeholders unfilled.
- After review is complete, dispatch back to the implementer via `agora.dispatch` with `type=reply`. Include the full assessment (Strengths, Issues, Assessment verdict).

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or `agora.find`. Do not hard-code instance mappings in the persona.
```

- [ ] **Step 3: frontmatter 확인**

Run: `python -c "t=open('plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md',encoding='utf-8').read(); assert t.startswith('---'), 'no frontmatter'; assert 'user-invocable: false' in t, 'missing user-invocable'; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-reviewer/skills/persona
git commit -m "feat: superpowers-reviewer persona 스킬 신규 작성"
```

---

## Task 3: `requesting-code-review` 및 `receiving-code-review` 스킬 복사

**Source:** `C:/Users/jylee/source/superpowers_model_specified/skills/`
**Destination:** `plugin/superpowers/superpowers-reviewer/skills/`

- [ ] **Step 1: 두 스킬 디렉토리 복사**

```bash
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/requesting-code-review" plugin/superpowers/superpowers-reviewer/skills/
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/receiving-code-review" plugin/superpowers/superpowers-reviewer/skills/
```

- [ ] **Step 2: 복사 결과 확인**

Run: `ls plugin/superpowers/superpowers-reviewer/skills/`
Expected: `persona  receiving-code-review  requesting-code-review`

Run: `ls plugin/superpowers/superpowers-reviewer/skills/requesting-code-review/`
Expected: `SKILL.md  code-reviewer.md` (code-reviewer.md 포함 확인)

Run: `ls plugin/superpowers/superpowers-reviewer/skills/receiving-code-review/`
Expected: `SKILL.md`

- [ ] **Step 3: frontmatter model/effort 보존 확인**

Run: `python -c "import pathlib; t=pathlib.Path('plugin/superpowers/superpowers-reviewer/skills/requesting-code-review/SKILL.md').read_text(encoding='utf-8'); assert 'model:' in t or 'effort:' in t, 'missing frontmatter fields'; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-reviewer/skills/requesting-code-review
git add plugin/superpowers/superpowers-reviewer/skills/receiving-code-review
git commit -m "feat: superpowers-reviewer에 requesting/receiving-code-review 스킬 복사"
```

---

## Task 4: `marketplace.json` 등록

**File:** `plugin/.claude-plugin/marketplace.json`

- [ ] **Step 1: 현재 marketplace.json 유효성 확인**

Run: `python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json',encoding='utf-8')); print('valid JSON')"`
Expected: `valid JSON`

- [ ] **Step 2: `plugins` 배열에 항목 추가**

`plugin/.claude-plugin/marketplace.json`의 `plugins` 배열 끝(`cc-agora-writer` 항목 또는 현재 마지막 항목 뒤)에 추가한다. 직전 항목 닫는 `}` 뒤에 `,`를 추가하는 것을 잊지 말 것.

추가할 항목:

```json
    {
      "name": "superpowers-reviewer",
      "source": "./superpowers/superpowers-reviewer",
      "description": "Superpowers reviewer persona — code review and feedback handling."
    }
```

- [ ] **Step 3: 수정 후 JSON 유효성 재확인**

Run: `python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json',encoding='utf-8')); print('valid JSON')"`
Expected: `valid JSON`

- [ ] **Step 4: 항목 등록 확인**

Run: `python -c "import json; m=json.load(open('plugin/.claude-plugin/marketplace.json',encoding='utf-8')); names=[p['name'] for p in m['plugins']]; assert 'superpowers-reviewer' in names, 'not found'; print('registered')"`
Expected: `registered`

- [ ] **Step 5: 커밋**

```bash
git add plugin/.claude-plugin/marketplace.json
git commit -m "feat: superpowers-reviewer를 plugin marketplace에 등록"
```

---

## Task 5: 검증

- [ ] **Step 1: marketplace 테스트 실행**

Run: `uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q`
Expected: PASS — 기존 `cc-agora` 계열 9종 테스트 모두 통과. `test_marketplace_sources_exist`는 `plugin/.claude-plugin/marketplace.json`을 읽지 않고 루트 `.claude-plugin/marketplace.json`을 읽으므로(테스트 코드 확인), 신규 항목은 marketplace source 경로 누락으로 FAIL 되지 않는다.

- [ ] **Step 2: superpowers-reviewer 플러그인 구조 수동 확인**

Run:
```bash
ls plugin/superpowers/superpowers-reviewer/.claude-plugin/plugin.json
ls plugin/superpowers/superpowers-reviewer/README.md
ls plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md
ls plugin/superpowers/superpowers-reviewer/skills/requesting-code-review/SKILL.md
ls plugin/superpowers/superpowers-reviewer/skills/requesting-code-review/code-reviewer.md
ls plugin/superpowers/superpowers-reviewer/skills/receiving-code-review/SKILL.md
```
Expected: 6개 파일 모두 존재.

- [ ] **Step 3: plugin.json 내용 확인**

Run: `python -c "import json; p=json.load(open('plugin/superpowers/superpowers-reviewer/.claude-plugin/plugin.json',encoding='utf-8')); assert p['name']=='superpowers-reviewer'; assert p['dependencies']==['superpowers-base']; assert p['version']=='0.1.0'; print('plugin.json OK')"`
Expected: `plugin.json OK`

- [ ] **Step 4: persona SKILL.md 필수 섹션 확인**

Run:
```bash
python -c "
t = open('plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md', encoding='utf-8').read()
assert t.startswith('---'), 'no frontmatter'
assert 'user-invocable: false' in t, 'missing user-invocable'
assert '# Reviewer persona' in t, 'missing H1'
assert '## Mission' in t, 'missing Mission'
assert '## Response conventions' in t, 'missing Response conventions'
assert '### Forward convention' in t, 'missing Forward'
assert '### Flush entry convention' in t, 'missing Flush entry'
assert '### cc message convention' in t, 'missing cc message'
assert '### Payload standard' in t, 'missing Payload standard'
assert '## Role-specific knowledge' in t, 'missing Role-specific'
assert '## Finding other members' in t, 'missing Finding other members'
print('persona SKILL.md OK')
"
```
Expected: `persona SKILL.md OK`

- [ ] **Step 5: 최종 커밋 없음 — Task 1–4에서 이미 커밋 완료**

검증 단계에서 새로 파일을 생성하거나 수정하지 않는다. 모든 파일은 이미 커밋 상태여야 한다.

---

## Self-Review

**Spec 커버리지 (§12 plan 5):**
- `superpowers-reviewer` 플러그인 신규 생성 — plugin.json·README·persona 스킬·스킬 2종. ✓
- spec §3 스킬 분배 — `requesting-code-review`·`receiving-code-review` reviewer에 배치. ✓
- spec §4 레이아웃 — `.claude-plugin/plugin.json` + `skills/persona/SKILL.md` + `README.md`. ✓
- spec §4 `dependencies: ["superpowers-base"]`. ✓
- spec §9 워크플로 — reviewer가 implementer로부터 받고 implementer로 돌려줌, persona 스킬에 명시. ✓
- spec §4 marketplace.json 등록 — `plugin/.claude-plugin/marketplace.json`에 1개 항목 추가. ✓
- `model`/`effort` frontmatter 보존 — 디렉토리 복사로 자동. ✓
- `code-reviewer.md` 템플릿 — `requesting-code-review/` 디렉토리 전체 복사로 자동 포함. ✓

**Phase 1 범위 밖 (후속 플랜):** 위임 배선·`agora.dispatch` cross-reference 재작성(통합 플랜 9), `cc-agora-ops/config/roles.json` reviewer 역할 추가(통합 플랜 9), comm-matrix 배선(통합 플랜 9), `claude -p` 없는 테스트 재설계(Phase 6).

**Placeholder 스캔:** persona SKILL.md는 완전한 본문을 가진다. 복사 스텝은 원본을 그대로 복사하는 완결된 지시다. README.md·plugin.json 모두 완성 내용이다.

**일관성:** 플러그인 이름 `superpowers-reviewer`가 plugin.json `name`·marketplace.json `name`·디렉토리명에서 일치. `user-invocable: false`가 persona SKILL.md frontmatter에 존재. `dependencies: ["superpowers-base"]`가 plugin.json에 정확히 지정됨.
