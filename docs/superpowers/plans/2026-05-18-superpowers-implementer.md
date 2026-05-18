# superpowers-implementer 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `superpowers-implementer` 페르소나 플러그인을 생성한다 — TDD·플랜 실행·git worktree·브랜치 완료 스킬 4종을 보유하고, AgentAgora 위임 규약에 맞는 persona SKILL.md를 포함하며, marketplace.json에 등록·검증된 상태를 만든다.

**Architecture:** 설계 spec `docs/superpowers/specs/2026-05-18-superpowers-persona-split-design.md` §3·§4·§12 Plan 3 기준. `plugin/superpowers/superpowers-implementer/`를 `plugin/personas/coder/` 레이아웃 패턴 — `.claude-plugin/plugin.json` + `skills/persona/SKILL.md` + `README.md` + 스킬 디렉토리 — 으로 구성한다. 원본 스킬은 `C:/Users/jylee/source/superpowers_model_specified/skills/`에서 디렉토리째 복사(model/effort frontmatter 보존). persona 스킬은 coder persona 관행(description, user-invocable: false, Forward/Flush/cc/Payload 규약 4절)을 완전히 따른다.

**Tech Stack:** Claude Code 플러그인, pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-implementer/
  .claude-plugin/
    plugin.json                              생성 (Task 1)
  README.md                                  생성 (Task 1)
  skills/
    persona/
      SKILL.md                               신규 작성 (Task 2)
    test-driven-development/
      SKILL.md                               복사 (Task 3)
    executing-plans/
      SKILL.md                               복사 (Task 3)
    using-git-worktrees/
      SKILL.md                               복사 (Task 3)
    finishing-a-development-branch/
      SKILL.md                               복사 (Task 3)
plugin/.claude-plugin/marketplace.json       수정 — superpowers-implementer 항목 추가 (Task 4)
```

> Note: `superpowers-base` 플러그인은 Phase 1 플랜(2026-05-18-superpowers-persona-split-phase1.md)에서 생성된다. 이 플랜은 그것과 독립적으로 실행 가능하다 — `dependencies`에 `"superpowers-base"`를 명시하지만, 단독 검증(marketplace 경로·plugin.json 존재 확인)은 base 없이도 통과한다.

---

## Task 1: `plugin.json` + `README.md` 생성

**Files:**
- `plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`
- `plugin/superpowers/superpowers-implementer/README.md`

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p "plugin/superpowers/superpowers-implementer/.claude-plugin"
mkdir -p "plugin/superpowers/superpowers-implementer/skills"
```

- [ ] **Step 2: plugin.json 작성**

`plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`:

```json
{
  "name": "superpowers-implementer",
  "description": "Superpowers implementer persona — executes plans with TDD, isolated worktrees, and clean branch completion.",
  "version": "0.1.0",
  "dependencies": ["superpowers-base"]
}
```

- [ ] **Step 3: README.md 작성**

`plugin/superpowers/superpowers-implementer/README.md`:

```markdown
# superpowers-implementer

AgentAgora implementer 역할 페르소나 플러그인이다. 이 플러그인은 워커가 implementer 역할(TDD로 구현, 격리된 git worktree에서 작업, 브랜치 완료)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-implementer"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-implementer@agent-agora": true
  }
}
```
```

- [ ] **Step 4: 확인**

```bash
cat plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json
```

Expected: `"name": "superpowers-implementer"`, `"dependencies": ["superpowers-base"]` 포함.

- [ ] **Step 5: 커밋**

```bash
git add plugin/superpowers/superpowers-implementer/.claude-plugin plugin/superpowers/superpowers-implementer/README.md
git commit -m "feat: superpowers-implementer plugin.json + README"
```

---

## Task 2: `skills/persona/SKILL.md` 작성

**Files:**
- `plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md`

이 파일은 `plugin/personas/coder/skills/persona/SKILL.md` 구조를 완전히 따른다: frontmatter (description + user-invocable: false), # 제목, ## Mission, ## Response conventions (4개 하위 절), ## Role-specific knowledge, ## Finding other members.

- [ ] **Step 1: persona 디렉토리 생성**

```bash
mkdir -p "plugin/superpowers/superpowers-implementer/skills/persona"
```

- [ ] **Step 2: SKILL.md 작성**

`plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md`:

```markdown
---
description: Implementer persona for an AgentAgora worker — mission, working style, and handoff rules for a council member that implements plans with TDD, git worktrees, and branch completion.
user-invocable: false
---

# Implementer persona

## Mission

Take task assignments from the router and produce tested, committed code. Use TDD — write the failing test first, then the minimal implementation to pass. Work in an isolated git worktree. When the branch is complete, run `finishing-a-development-branch`. Forward anything outside your responsibility. Never fill in gaps by guessing — if a requirement is ambiguous, send the originator a one-line clarification before proceeding.

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. If the nature of the work falls outside your domain (e.g. you hit a bug you cannot resolve inline → debugger; work needs review → reviewer), use `agora.dispatch` to hand it off to the appropriate persona. Sending the originator a one-line ack ("delegated to debugger") is recommended to prevent orphaned tasks — not mandatory; use your judgment.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain your inbox with `agora.flush`. See the `agora-protocol` skill for full channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type` enum has four values: `task | reply | closing | ack`. Use `type=reply` for task responses, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

### Owned skills

- `test-driven-development` — write the failing test first, then the implementation. If you didn't watch the test fail, you don't know if it tests the right thing.
- `executing-plans` — load a written plan, review it critically, execute all tasks, and report when complete. Prefer `subagent-driven-development` (router persona) when subagent support is available.
- `using-git-worktrees` — detect existing isolation first. Use native worktree tools when available. Create an isolated workspace before starting; never work directly on the main branch unless explicitly required.
- `finishing-a-development-branch` — when implementation is complete and all tests pass, guide the branch to merge / PR / cleanup. This is the final step before handing off to the improver.

### Hand-off edges

- **Bug you cannot resolve inline** → dispatch to **debugger** persona (`agora.dispatch` with `type=task`, include error context, failing test, and what was tried).
- **Work needs code review** → dispatch to **reviewer** persona (`agora.dispatch` with `type=task`, include the diff or PR link).
- **`finishing-a-development-branch` completes** → dispatch to **improver** persona (`agora.dispatch` with `type=closing`, include branch name and summary of completed work).

All hand-offs are via `agora.dispatch`. Do not hand off silently — send an `ack` back to the originator first.

### Working conventions

- Keep changes as small as possible. If a single task touches multiple modules, prefer splitting into sub-tasks.
- Prefer modifying existing files. Create new files only when explicitly required or when the responsibility boundary is clear.
- Before using any library or tool, verify argument semantics via `--help` or by reading the source. No guessing.
- In Windows environments, use forward slashes for path literals. Backslashes inside JSON cause escape conflicts at the hook layer.
- After writing code, briefly list failure points and confirm tests cover them before forwarding.

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or `agora.find`. Do not hard-code instance mappings in the persona. Use role names (`debugger`, `reviewer`, `improver`) as the lookup key in `agora.find`.
```

- [ ] **Step 3: frontmatter 확인**

```bash
python -c "
import pathlib, re
text = pathlib.Path('plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md').read_text(encoding='utf-8')
assert text.startswith('---'), 'must start with frontmatter'
assert 'user-invocable: false' in text, 'must have user-invocable: false'
print('persona/SKILL.md OK')
"
```

Expected: `persona/SKILL.md OK`

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-implementer/skills/persona
git commit -m "feat: superpowers-implementer persona SKILL.md (AgentAgora 규약 완전 적용)"
```

---

## Task 3: 스킬 4종 복사

**Source:** `C:/Users/jylee/source/superpowers_model_specified/skills/`

복사 대상: `test-driven-development`, `executing-plans`, `using-git-worktrees`, `finishing-a-development-branch`

- [ ] **Step 1: 스킬 4종 복사**

```bash
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/test-driven-development" \
      "plugin/superpowers/superpowers-implementer/skills/"
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/executing-plans" \
      "plugin/superpowers/superpowers-implementer/skills/"
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/using-git-worktrees" \
      "plugin/superpowers/superpowers-implementer/skills/"
cp -r "C:/Users/jylee/source/superpowers_model_specified/skills/finishing-a-development-branch" \
      "plugin/superpowers/superpowers-implementer/skills/"
```

- [ ] **Step 2: 구조 확인**

```bash
ls plugin/superpowers/superpowers-implementer/skills/
```

Expected: `executing-plans  finishing-a-development-branch  persona  test-driven-development  using-git-worktrees`

- [ ] **Step 3: 각 스킬에 SKILL.md 존재 및 frontmatter model/effort 보존 확인**

```bash
python -c "
import pathlib, re
base = pathlib.Path('plugin/superpowers/superpowers-implementer/skills')
for skill in ['test-driven-development', 'executing-plans', 'using-git-worktrees', 'finishing-a-development-branch']:
    text = (base / skill / 'SKILL.md').read_text(encoding='utf-8')
    assert text.startswith('---'), f'{skill}: missing frontmatter'
    assert 'model:' in text, f'{skill}: missing model frontmatter'
    print(f'{skill}: OK')
"
```

Expected: 4줄 `<skill-name>: OK`

- [ ] **Step 4: 커밋**

```bash
git add plugin/superpowers/superpowers-implementer/skills/test-driven-development \
        plugin/superpowers/superpowers-implementer/skills/executing-plans \
        plugin/superpowers/superpowers-implementer/skills/using-git-worktrees \
        plugin/superpowers/superpowers-implementer/skills/finishing-a-development-branch
git commit -m "feat: superpowers-implementer 스킬 4종 복사 (tdd·executing-plans·worktrees·finishing)"
```

---

## Task 4: marketplace.json 등록

**Files:**
- `plugin/.claude-plugin/marketplace.json`

> Note: 이 Task는 marketplace.json에 `superpowers-implementer` 항목 **하나**만 추가한다. 다른 superpowers 페르소나 항목(base, planner, debugger 등)이 이미 추가돼 있으면 그 상태를 존중하고 `superpowers-implementer` 항목이 없을 때만 삽입한다. Phase 1 플랜이 먼저 실행돼 7개 항목이 이미 등록된 경우에는 이 Task를 건너뛴다 — Step 1의 사전 확인으로 판단한다.

- [ ] **Step 1: 현재 marketplace.json에 superpowers-implementer 항목 있는지 확인**

```bash
python -c "
import json, pathlib
mkt = json.loads(pathlib.Path('plugin/.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
names = [p['name'] for p in mkt['plugins']]
if 'superpowers-implementer' in names:
    print('ALREADY_REGISTERED — skip Task 4')
else:
    print('NOT_REGISTERED — proceed with Step 2')
"
```

Expected: `NOT_REGISTERED — proceed with Step 2` (항목이 없으면 계속)

- [ ] **Step 2: marketplace.json의 `plugins` 배열 끝에 항목 추가**

`plugin/.claude-plugin/marketplace.json`의 `plugins` 배열 마지막 항목 뒤에 추가 (마지막 항목 닫는 `}` 뒤에 `,` 추가 필요):

```json
    {
      "name": "superpowers-implementer",
      "source": "./superpowers/superpowers-implementer",
      "description": "Superpowers implementer persona — TDD implementation and branch completion."
    }
```

- [ ] **Step 3: JSON 유효성 확인**

```bash
python -c "import json, pathlib; json.loads(pathlib.Path('plugin/.claude-plugin/marketplace.json').read_text(encoding='utf-8')); print('valid JSON')"
```

Expected: `valid JSON`

- [ ] **Step 4: source 경로가 실제 디렉토리 + plugin.json을 가리키는지 확인**

```bash
python -c "
import json, pathlib
repo = pathlib.Path('.')
mkt = json.loads((repo / 'plugin/.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
entry = next(p for p in mkt['plugins'] if p['name'] == 'superpowers-implementer')
src = (repo / 'plugin' / entry['source']).resolve()
pj = src / '.claude-plugin' / 'plugin.json'
assert pj.is_file(), f'plugin.json not found at {pj}'
print(f'superpowers-implementer source OK: {src}')
"
```

Expected: `superpowers-implementer source OK: ...superpowers-implementer`

- [ ] **Step 5: 커밋**

```bash
git add plugin/.claude-plugin/marketplace.json
git commit -m "feat: superpowers-implementer를 marketplace.json에 등록"
```

---

## Task 5: 검증

- [ ] **Step 1: marketplace 테스트 실행 (existing cc-agora 테스트 회귀 없음 확인)**

```bash
uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q
```

Expected: `PASSED` — 기존 `test_marketplace_lists_all_nine_plugins` 등 cc-agora 계열 테스트가 모두 통과한다. superpowers 플러그인은 이 테스트의 `expected` 집합에 포함되지 않으므로 추가 항목은 `test_marketplace_sources_exist`(source 경로 → plugin.json 존재 확인)만 영향을 받는다.

- [ ] **Step 2: `test_marketplace_sources_exist` 통과 확인**

`test_marketplace_sources_exist`는 marketplace.json의 모든 `source` 항목에 대해 `<source>/.claude-plugin/plugin.json` 존재를 검증한다. superpowers-implementer를 추가한 후에도 이 테스트가 통과해야 한다.

만약 실패하면: `plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json`이 존재하는지 `ls` 로 확인.

- [ ] **Step 3: 플러그인 완전성 수동 확인**

```bash
ls plugin/superpowers/superpowers-implementer/skills/
```

Expected: `executing-plans  finishing-a-development-branch  persona  test-driven-development  using-git-worktrees`

```bash
python -c "import json; d = json.load(open('plugin/superpowers/superpowers-implementer/.claude-plugin/plugin.json', encoding='utf-8')); print(d['name'], d['version'], d['dependencies'])"
```

Expected: `superpowers-implementer 0.1.0 ['superpowers-base']`

- [ ] **Step 4: persona/SKILL.md 규약 확인**

```bash
python -c "
import pathlib
text = pathlib.Path('plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md').read_text(encoding='utf-8')
checks = [
    ('starts with ---', text.startswith('---')),
    ('user-invocable: false', 'user-invocable: false' in text),
    ('Forward convention', '### Forward convention' in text),
    ('Flush entry convention', '### Flush entry convention' in text),
    ('cc message convention', '### cc message convention' in text),
    ('Payload standard', '### Payload standard' in text),
    ('Hand-off edges', 'Hand-off edges' in text),
    ('agora.dispatch', 'agora.dispatch' in text),
]
for label, ok in checks:
    print(f'{'OK' if ok else 'FAIL'}: {label}')
assert all(ok for _, ok in checks), 'persona/SKILL.md 규약 미충족'
print('All checks passed.')
"
```

Expected: 8줄 `OK: ...`, 마지막 `All checks passed.`

---

## Self-Review

**Spec 커버리지 (spec §3·§4·§12 Plan 3):**
- §3 superpowers-implementer 스킬 분배: `test-driven-development`, `executing-plans`, `using-git-worktrees`, `finishing-a-development-branch` 4종 → Task 3. ✓
- §4 플러그인 레이아웃: `.claude-plugin/plugin.json` + `README.md` + `skills/persona/SKILL.md` + 스킬 디렉토리 → Task 1–3. ✓
- §4 `dependencies: ["superpowers-base"]` → Task 1 plugin.json. ✓
- §4 marketplace.json 등록 → Task 4. ✓
- §5 위임 관행: persona SKILL.md에 `agora.dispatch` 핸드오프 엣지 3종(debugger·reviewer·improver) 명시 → Task 2. ✓
- §9 워크플로 위치: implementer → debugger (버그), implementer → reviewer (리뷰), implementer → improver (finishing 완료) → Task 2. ✓
- persona 스킬 AgentAgora 규약 (Forward·Flush entry·cc·Payload 4절) → Task 2. ✓
- `model`/`effort` frontmatter 보존 → 디렉토리 복사로 자동 보존(Task 3 Step 3에서 검증). ✓

**범위 밖 (후속 플랜):**
- 스킬 본문의 위임 메타 추가·cross-plugin 참조 재배선 → Phase 2(통합 플랜).
- comm-matrix.csv implementer 엣지 항목 → Phase 9(통합 플랜).
- `cc-agora-ops/config/roles.json` implementer role 매핑 → Phase 9(통합 플랜).
- 테스트 하네스 재설계(`claude -p` 제거) → Phase 6(spec §8).

**Placeholder 스캔:** persona/SKILL.md는 완전한 본문을 가짐 — AgentAgora 규약 4절 포함, 핸드오프 엣지 3종 명시, working conventions 구체적. "copy" 스텝은 원본을 그대로 복사하는 완결된 지시. README.md는 한국어, `plugin/personas/coder/README.md` 스타일 준수.

**일관성:** 플러그인 이름 `superpowers-implementer`가 `.claude-plugin/plugin.json`의 `"name"`, `marketplace.json`의 `"name"`, 디렉토리명에서 동일. `dependencies: ["superpowers-base"]`가 plugin.json에 명시. persona/SKILL.md의 `user-invocable: false`가 coder 패턴과 동일.
