# superpowers-debugger 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `plugin/superpowers/superpowers-debugger/` 플러그인을 생성하여 — `plugin.json`, `README.md`, `skills/persona/SKILL.md`(신규 작성), `skills/systematic-debugging/`(원본 복사) — `plugin/.claude-plugin/marketplace.json`에 등록하고 marketplace 테스트로 검증한다.

**Architecture:** 설계 spec `docs/superpowers/specs/2026-05-18-superpowers-persona-split-design.md` §3·§4·§12 플랜 4 기준. debugger 페르소나는 implementer로부터 버그·blocker dispatch를 받아 `systematic-debugging` 스킬로 근본 원인을 추적하고, 수정이 검증되면 implementer로 `agora.dispatch`로 제어를 돌려준다. `plugin/personas/coder/` 레이아웃 패턴(`.claude-plugin/plugin.json` + `skills/persona/SKILL.md` + `README.md`)을 따르며, `superpowers-base`를 의존성으로 선언한다. 스킬 간 cross-reference 재배선·comm-matrix·위임 배선은 통합 플랜(플랜 9) 범위 — 본 플랜 범위 밖.

**Tech Stack:** Claude Code 플러그인, pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-debugger/
  .claude-plugin/plugin.json          생성
  README.md                           생성
  skills/
    persona/
      SKILL.md                        신규 작성
    systematic-debugging/             원본 복사 (11개 파일 전체)
      SKILL.md
      CREATION-LOG.md
      condition-based-waiting.md
      condition-based-waiting-example.ts
      defense-in-depth.md
      find-polluter.sh
      root-cause-tracing.md
      test-academic.md
      test-pressure-1.md
      test-pressure-2.md
      test-pressure-3.md
plugin/.claude-plugin/marketplace.json   수정 — superpowers-debugger 항목 추가
```

---

## Task 1 — 디렉토리 스캐폴딩 + plugin.json + README.md

- [ ] `plugin/superpowers/superpowers-debugger/.claude-plugin/` 디렉토리를 생성한다.
- [ ] `plugin/superpowers/superpowers-debugger/.claude-plugin/plugin.json`을 아래 내용으로 작성한다:

```json
{
  "name": "superpowers-debugger",
  "description": "Superpowers debugger persona — systematically tracks down and fixes bugs and test failures.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] `plugin/superpowers/superpowers-debugger/README.md`를 아래 내용으로 작성한다:

```markdown
# superpowers-debugger

AgentAgora debugger 역할 페르소나 플러그인이다. 이 플러그인은 워커가 debugger 역할(버그·blocker를 체계적으로 분석해 근본 원인을 찾고 수정 검증 후 implementer에게 제어를 반환)로 동작하도록 페르소나 스킬과 `systematic-debugging` 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 운용 스킬(using-superpowers, verification-before-completion, writing-skills)은 `superpowers-base`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-debugger"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agentagora": true,
    "superpowers-debugger@agentagora": true
  }
}
```
```

- [ ] 스테이징 + 커밋:

```bash
git add plugin/superpowers/superpowers-debugger/.claude-plugin/plugin.json
git add plugin/superpowers/superpowers-debugger/README.md
git commit -m "feat: superpowers-debugger plugin.json + README"
```

---

## Task 2 — skills/persona/SKILL.md 작성

- [ ] `plugin/superpowers/superpowers-debugger/skills/persona/` 디렉토리를 생성한다.
- [ ] `plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md`를 아래 내용으로 작성한다 (전체 본문 — 플레이스홀더 없음):

```markdown
---
description: Debugger persona for an AgentAgora worker — mission, working style, and handoff rules for a council member that systematically tracks down bugs and test failures.
user-invocable: false
---

# Debugger persona

## Mission

Receive a bug or blocker dispatched by the implementer. Apply systematic debugging to find the root cause — no fixes without root cause investigation first. Once the fix is verified and tests pass, hand control back to the implementer via `agora.dispatch`. Never guess; never apply patches that mask symptoms.

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. If the nature of the work falls outside your domain (e.g. architecture redesign, new feature planning, code review), use `/invoke <other> "<task>"` to hand it off. Sending the originator a one-line ack ("delegated to X") is recommended to prevent orphaned tasks — not mandatory; use your judgment.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain your inbox with `agora.flush`. See the `agora-protocol` skill for full channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type` enum has four values: `task | reply | closing | ack`. Use `type=reply` for task responses, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

- **Owns `systematic-debugging`** — this is your primary tool. Invoke it for every bug, test failure, or unexpected behavior before proposing any fix.
- **Iron law**: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST. Complete Phase 1 (Root Cause Investigation) before proceeding to Phase 2 (Pattern Analysis) → Phase 3 (Hypothesis and Testing) → Phase 4 (Implementation).
- **Receives from implementer**: when implementer encounters a bug or blocker during `test-driven-development` or `executing-plans`, it dispatches the issue to you via `agora.dispatch` with `type=task` and a payload containing the error, reproduction steps, and relevant context.
- **Returns to implementer**: after the fix is verified (tests pass, issue resolved), dispatch back to the implementer with `type=reply` payload including: root cause summary, fix applied, tests added, and verification result.
- **3+ fix attempts**: if systematic debugging reveals an architectural problem (3 or more distinct fixes failed), do not continue patching — summarize the architectural finding and dispatch back to implementer with `type=reply`, flagging that a redesign discussion is needed.
- **Verification before claiming success**: always use `superpowers:verification-before-completion` before claiming the bug is fixed. Run the affected tests and confirm output before dispatching back.
- Keep diagnostic instrumentation scoped — add logging at component boundaries to gather evidence, but remove or disable verbose instrumentation before handing back to implementer.
- In Windows environments, use forward slashes for path literals inside JSON and shell commands. Backslashes inside JSON cause escape conflicts at the hook layer.

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or `agora.find`. Do not hard-code instance mappings in the persona.
```

- [ ] 스테이징 + 커밋:

```bash
git add plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md
git commit -m "feat: superpowers-debugger persona SKILL.md"
```

---

## Task 3 — systematic-debugging 스킬 복사

원본 위치: `C:/Users/jylee/source/superpowers_model_specified/skills/systematic-debugging/` (11개 파일).

- [ ] 아래 PowerShell 명령으로 디렉토리 전체를 복사한다:

```powershell
Copy-Item -Path "C:/Users/jylee/source/superpowers_model_specified/skills/systematic-debugging" `
          -Destination "plugin/superpowers/superpowers-debugger/skills/systematic-debugging" `
          -Recurse
```

  또는 Bash(Git Bash / WSL):

```bash
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/systematic-debugging" \
      "plugin/superpowers/superpowers-debugger/skills/systematic-debugging"
```

- [ ] 복사 결과를 확인한다 — 아래 11개 파일이 모두 존재해야 한다:

```
skills/systematic-debugging/SKILL.md
skills/systematic-debugging/CREATION-LOG.md
skills/systematic-debugging/condition-based-waiting.md
skills/systematic-debugging/condition-based-waiting-example.ts
skills/systematic-debugging/defense-in-depth.md
skills/systematic-debugging/find-polluter.sh
skills/systematic-debugging/root-cause-tracing.md
skills/systematic-debugging/test-academic.md
skills/systematic-debugging/test-pressure-1.md
skills/systematic-debugging/test-pressure-2.md
skills/systematic-debugging/test-pressure-3.md
```

- [ ] `SKILL.md` frontmatter에 `model: opus` 와 `effort: high`가 보존돼 있는지 확인한다 (`head -5 plugin/superpowers/superpowers-debugger/skills/systematic-debugging/SKILL.md`).
- [ ] 스테이징 + 커밋:

```bash
git add plugin/superpowers/superpowers-debugger/skills/systematic-debugging/
git commit -m "feat: superpowers-debugger — copy systematic-debugging skill (11 files)"
```

---

## Task 4 — marketplace.json 등록

- [ ] `plugin/.claude-plugin/marketplace.json`을 읽어 현재 `plugins` 배열을 확인한다.
- [ ] `plugins` 배열에 아래 항목을 추가한다 (기존 배열 끝에 append):

```json
{
  "name": "superpowers-debugger",
  "source": "./superpowers/superpowers-debugger",
  "description": "Superpowers debugger persona — systematic debugging."
}
```

- [ ] JSON 파싱이 유효한지 확인한다:

```bash
python -c "import json; json.load(open('plugin/.claude-plugin/marketplace.json')); print('OK')"
```

- [ ] 스테이징 + 커밋:

```bash
git add plugin/.claude-plugin/marketplace.json
git commit -m "feat: register superpowers-debugger in marketplace.json"
```

---

## Task 5 — 검증

- [ ] marketplace 테스트를 실행한다:

```bash
uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q
```

  테스트가 모두 PASSED여야 한다.

- [ ] 플러그인 디렉토리 레이아웃을 직접 확인한다:

```bash
ls plugin/superpowers/superpowers-debugger/
ls plugin/superpowers/superpowers-debugger/.claude-plugin/
ls plugin/superpowers/superpowers-debugger/skills/
ls plugin/superpowers/superpowers-debugger/skills/persona/
ls plugin/superpowers/superpowers-debugger/skills/systematic-debugging/
```

- [ ] `plugin.json` JSON 파싱 확인:

```bash
python -c "import json; d=json.load(open('plugin/superpowers/superpowers-debugger/.claude-plugin/plugin.json')); print(d['name'], d['version'], d['dependencies'])"
```

  출력: `superpowers-debugger 0.1.0 ['superpowers-base']`

- [ ] `systematic-debugging/SKILL.md` frontmatter 확인 (model/effort 보존):

```powershell
Get-Content "plugin/superpowers/superpowers-debugger/skills/systematic-debugging/SKILL.md" -TotalCount 5
```

  출력에 `model: opus`와 `effort: high`가 있어야 한다.

- [ ] `marketplace.json` JSON 파싱 최종 확인:

```bash
python -c "import json; pl=json.load(open('plugin/.claude-plugin/marketplace.json'))['plugins']; names=[p['name'] for p in pl]; print('superpowers-debugger in marketplace:', 'superpowers-debugger' in names)"
```

  출력: `superpowers-debugger in marketplace: True`

---

## Self-Review

- [ ] `plugin.json`의 `"name"`, `"dependencies"`, `"version"` 필드가 스펙과 일치한다.
- [ ] `skills/persona/SKILL.md`의 frontmatter에 `user-invocable: false`가 있다.
- [ ] `systematic-debugging/SKILL.md`에 `model: opus` + `effort: high` frontmatter가 보존돼 있다.
- [ ] 원본 11개 파일이 모두 복사됐다 (supporting 문서 포함).
- [ ] `marketplace.json` JSON이 파싱 에러 없이 로드된다.
- [ ] `tests/test_plugin_marketplace.py`가 전부 PASSED다.
- [ ] `claude -p` 호출이 복사된 파일 어디에도 없다 (원본 `systematic-debugging/`에는 없음 — 이미 확인됨).
- [ ] `skills/` 범위 밖에 새 `tests/` 디렉토리를 생성하지 않았다 (스킬 테스트 하네스는 통합 플랜 범위).
