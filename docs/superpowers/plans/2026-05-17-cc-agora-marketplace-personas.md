# cc-agora 마켓플레이스 + 페르소나 플러그인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentAgora 마켓플레이스를 발행하고, 7개 역할 페르소나 플러그인(각자 `cc-agora`에 의존)을 만든다.

**Architecture:** 저장소 루트에 `.claude-plugin/marketplace.json`을 두어 `cc-agora`·`cc-agora-ops`·7개 페르소나 플러그인을 등재한다. 각 페르소나 플러그인은 `plugin/personas/<role>/`에 `plugin.json`(`dependencies: ["cc-agora"]`) + `skills/persona/SKILL.md`(역할 정의, `user-invocable: false`, 영어)를 갖는다. 페르소나 본문은 기존 `plugin/cc-agora-ops/templates/presets/<role>.md`(한국어)를 영어 스킬로 옮긴 것이다.

**Tech Stack:** Claude Code 플러그인·마켓플레이스, JSON, Markdown. 테스트는 `.venv\Scripts\python.exe -m pytest`.

**선행 의존:** Plan 1·Plan 2가 먼저 머지돼야 한다 — `cc-agora` 코어가 존재해야 페르소나가 의존을 선언할 수 있고, presets는 Plan 2에서 `cc-agora-ops/templates/presets/`로 이동돼 있어야 한다.

spec: `docs/superpowers/specs/2026-05-17-cc-agora-plugin-split-design.md` (§2·§3·§5·§11).

---

### Task 1: AgentAgora 마켓플레이스 manifest

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `tests/test_plugin_marketplace.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_plugin_marketplace.py`:

```python
"""Validates the AgentAgora marketplace manifest and persona plugin manifests."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROLES = ("orchestrator", "coder", "reviewer", "tester", "writer", "planner", "general")


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_marketplace_lists_all_nine_plugins():
    mkt = _load(REPO / ".claude-plugin" / "marketplace.json")
    names = {p["name"] for p in mkt["plugins"]}
    expected = {"cc-agora", "cc-agora-ops"} | {f"cc-agora-{r}" for r in ROLES}
    assert names == expected


def test_marketplace_sources_exist():
    mkt = _load(REPO / ".claude-plugin" / "marketplace.json")
    for entry in mkt["plugins"]:
        src = (REPO / entry["source"]).resolve()
        assert (src / ".claude-plugin" / "plugin.json").is_file(), entry["name"]


def test_persona_plugins_depend_on_cc_agora():
    for role in ROLES:
        pj = _load(REPO / "plugin" / "personas" / role / ".claude-plugin" / "plugin.json")
        assert pj["name"] == f"cc-agora-{role}"
        assert pj["dependencies"] == ["cc-agora"]


def test_persona_plugins_have_persona_skill():
    for role in ROLES:
        sk = REPO / "plugin" / "personas" / role / "skills" / "persona" / "SKILL.md"
        text = sk.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "user-invocable: false" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_marketplace.py -q`
Expected: FAIL — marketplace.json·페르소나 플러그인 없음.

- [ ] **Step 3: marketplace.json 생성**

`.claude-plugin/marketplace.json` (저장소 루트):

```json
{
  "name": "agentagora",
  "owner": { "name": "AgentAgora" },
  "plugins": [
    { "name": "cc-agora", "source": "./plugin/cc-agora" },
    { "name": "cc-agora-ops", "source": "./plugin/cc-agora-ops" },
    { "name": "cc-agora-orchestrator", "source": "./plugin/personas/orchestrator" },
    { "name": "cc-agora-coder", "source": "./plugin/personas/coder" },
    { "name": "cc-agora-reviewer", "source": "./plugin/personas/reviewer" },
    { "name": "cc-agora-tester", "source": "./plugin/personas/tester" },
    { "name": "cc-agora-writer", "source": "./plugin/personas/writer" },
    { "name": "cc-agora-planner", "source": "./plugin/personas/planner" },
    { "name": "cc-agora-general", "source": "./plugin/personas/general" }
  ]
}
```

> 구현 시 확인: marketplace.json의 정확한 스키마(`owner` 하위 키, `plugins[].source` 형식)를 Claude Code plugin-marketplaces 문서로 확정한다. 위는 plugin-dependencies 문서의 예시 형태를 따른 것.

이 시점에 `test_marketplace_lists_all_nine_plugins`는 통과하지만 `test_marketplace_sources_exist`·persona 테스트는 Task 2~3 완료 전까지 실패한다 — 정상.

- [ ] **Step 4: 커밋**

```bash
git add .claude-plugin/marketplace.json tests/test_plugin_marketplace.py
git commit -m "feat: AgentAgora 마켓플레이스 manifest"
```

---

### Task 2: 페르소나 플러그인 — `cc-agora-coder` (worked example)

페르소나 플러그인 1개를 완전히 만든다. 나머지 6개는 Task 3에서 같은 구조로 반복한다.

**Files:**
- Create: `plugin/personas/coder/.claude-plugin/plugin.json`
- Create: `plugin/personas/coder/skills/persona/SKILL.md`
- Create: `plugin/personas/coder/README.md`

- [ ] **Step 1: plugin.json 생성**

`plugin/personas/coder/.claude-plugin/plugin.json`:

```json
{
  "name": "cc-agora-coder",
  "description": "AgentAgora coder persona — a council member that turns tasks into minimal, reviewable code changes.",
  "version": "0.1.0",
  "dependencies": ["cc-agora"]
}
```

- [ ] **Step 2: 페르소나 스킬 생성**

`plugin/personas/coder/skills/persona/SKILL.md`. 본문은 기존 `plugin/cc-agora-ops/templates/presets/coder.md`(한국어 페르소나)를 **영어로 옮긴 것**. frontmatter:

```markdown
---
description: Coder persona for an AgentAgora worker — mission, working style, and handoff rules for a council member that writes code.
user-invocable: false
---

# Coder persona

[Translate the body of plugin/cc-agora-ops/templates/presets/coder.md into English here,
preserving its sections (mission, working style, handoff/forward rules, etc.).
Keep wording concise. Reference the agora-protocol skill for channel-mode messaging
rather than restating it.]
```

구현자: `plugin/cc-agora-ops/templates/presets/coder.md`를 읽어 그 절 구조를 보존하며 영어로 옮긴다. 채널 동작 규칙은 재기술하지 않고 `agora-protocol`을 참조한다.

- [ ] **Step 3: README.md 생성**

`plugin/personas/coder/README.md` — 한국어 한두 단락: 이 플러그인이 coder 역할 페르소나를 제공하며 `cc-agora` 코어에 의존한다는 점, 워커 `.claude/settings.local.json`의 `enabledPlugins`로 활성화된다는 점.

- [ ] **Step 4: JSON 유효성 확인**

Run: `.venv\Scripts\python.exe -c "import json; pj=json.load(open('plugin/personas/coder/.claude-plugin/plugin.json',encoding='utf-8')); assert pj['dependencies']==['cc-agora']; print('ok')"`
Expected: `ok`

- [ ] **Step 5: 커밋**

```bash
git add plugin/personas/coder
git commit -m "feat: cc-agora-coder 페르소나 플러그인"
```

---

### Task 3: 나머지 6개 페르소나 플러그인

`orchestrator`·`reviewer`·`tester`·`writer`·`planner`·`general` 6개를 Task 2의 `coder`와 **동일한 구조**로 만든다. 각 역할 `<role>`에 대해:

**Files (각 role마다):**
- Create: `plugin/personas/<role>/.claude-plugin/plugin.json`
- Create: `plugin/personas/<role>/skills/persona/SKILL.md`
- Create: `plugin/personas/<role>/README.md`

- [ ] **Step 1: 6개 플러그인 디렉토리·파일 생성**

각 `<role>`에 대해:

(a) `plugin/personas/<role>/.claude-plugin/plugin.json` — Task 2 Step 1과 동일 구조, `name`·`description`만 역할에 맞게:

```json
{
  "name": "cc-agora-<role>",
  "description": "AgentAgora <role> persona — <one-line role summary>.",
  "version": "0.1.0",
  "dependencies": ["cc-agora"]
}
```

(b) `plugin/personas/<role>/skills/persona/SKILL.md` — `plugin/cc-agora-ops/templates/presets/<role>.md`를 영어로 옮긴 본문. frontmatter는 Task 2 Step 2와 동일 형식(`user-invocable: false`, role별 `description`).

(c) `plugin/personas/<role>/README.md` — Task 2 Step 3과 동일 형식, 역할명만 교체.

`description`의 역할 한 줄 요약 가이드: `orchestrator`=team work distribution PM; `reviewer`=reviews diffs and flags issues; `tester`=writes and runs tests; `writer`=produces docs and prose; `planner`=breaks goals into ordered tasks; `general`=generalist fallback worker.

- [ ] **Step 2: 7개 페르소나 플러그인 검증**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_marketplace.py -q`
Expected: 4개 테스트 전부 PASS — marketplace 등재·source 존재·의존성·persona 스킬 모두 충족.

- [ ] **Step 3: 커밋**

```bash
git add plugin/personas
git commit -m "feat: 6개 페르소나 플러그인 (orchestrator·reviewer·tester·writer·planner·general)"
```

---

### Task 4: 잔존 presets 디렉토리 제거 + 최종 정리

페르소나 본문이 전부 페르소나 플러그인으로 이관됐으므로 `cc-agora-ops`의 임시 presets 디렉토리를 제거한다.

**Files:**
- Delete: `plugin/cc-agora-ops/templates/presets/`
- Modify: `plugin/SMOKE.md` (있으면 — spawn 산출물 기술 갱신)

- [ ] **Step 1: presets 디렉토리 제거**

```bash
git rm -r plugin/cc-agora-ops/templates/presets
```

페르소나 본문은 7개 페르소나 플러그인의 `skills/persona/SKILL.md`로 모두 옮겨졌으므로 원본 preset .md는 더 이상 필요 없다.

- [ ] **Step 2: presets를 참조하는 잔존 코드가 없는지 확인**

Run: `.venv\Scripts\python.exe -c "import subprocess; out=subprocess.run(['git','grep','-l','templates/presets'],capture_output=True,text=True).stdout; print(repr(out))"`
Expected: 빈 문자열(`''`) 또는 문서/스펙 파일만 — `spawn.py` 등 코드에 참조가 남아 있으면 안 된다. 코드 참조가 있으면 제거한다(Plan 2의 spawn 재설계로 이미 없어야 정상).

- [ ] **Step 3: SMOKE.md 갱신**

`plugin/SMOKE.md`가 존재하면(Plan 2 또는 별도로 옮겨졌을 수 있음), spawn 산출물을 기술하는 시나리오를 새 산출물(thin CLAUDE.md + .mcp.json + run.bat + `.claude/settings.local.json`)에 맞춘다. 페르소나 플러그인 활성화 흐름을 한 줄 추가한다. `plugin/SMOKE.md`가 아직 `plugin/cc-agora/SMOKE.md`에 있으면 `git mv plugin/cc-agora/SMOKE.md plugin/SMOKE.md`로 옮긴다.

- [ ] **Step 4: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "chore: 잔존 presets 제거 + SMOKE.md 산출물 갱신"
```

---

## 완료 기준

- `.claude-plugin/marketplace.json`이 9개 플러그인을 등재한다.
- 7개 페르소나 플러그인이 `plugin/personas/<role>/`에 존재하고 각자 `dependencies: ["cc-agora"]`를 선언한다.
- 각 페르소나 플러그인이 영어 `persona` 스킬(`user-invocable: false`)을 갖는다.
- `templates/presets/`가 사라졌다.
- `tests/test_plugin_marketplace.py` 4개 테스트 + 전체 스위트 통과.

## 비고

페르소나 본문 영어 번역은 기존 한국어 preset의 절 구조와 의미를 보존하되, 채널 동작
규칙은 `agora-protocol`을 참조하고 재기술하지 않는다(DRY).
