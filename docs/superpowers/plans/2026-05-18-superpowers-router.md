# superpowers-router 플러그인 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `superpowers-router` 페르소나 플러그인을 생성한다 — planner로부터 승인된 플랜을 받아 병렬/순차 체크포인트를 수행한 뒤 implementer로 dispatch한다.

**Architecture:** spec §3·§4에서 `superpowers-router`는 `subagent-driven-development`와 `dispatching-parallel-agents` 두 스킬을 보유하는 페르소나 플러그인이다. spec §6의 병렬처리 체크포인트가 이 페르소나의 핵심 로직 — planner 핸드오프 직후 플랜 task들의 독립성을 판단해 parallel path(dispatching-parallel-agents)와 sequential path(subagent-driven-development)로 분기한다. spec §12 Plan 6이며, 다른 페르소나 플러그인과 독립적으로 구현 가능하다.

**Tech Stack:** Claude Code 플러그인, pytest.

---

## 파일 구조

```
plugin/superpowers/superpowers-router/
  .claude-plugin/
    plugin.json
  README.md
  skills/
    persona/
      SKILL.md
    subagent-driven-development/
      SKILL.md
      implementer-prompt.md
      spec-reviewer-prompt.md
      code-quality-reviewer-prompt.md
    dispatching-parallel-agents/
      SKILL.md
```

---

## Task 1 — 디렉토리 골격 + plugin.json + README.md

- [ ] 타겟 디렉토리 트리를 생성한다:

  ```
  plugin/superpowers/superpowers-router/.claude-plugin/
  plugin/superpowers/superpowers-router/skills/persona/
  plugin/superpowers/superpowers-router/skills/subagent-driven-development/
  plugin/superpowers/superpowers-router/skills/dispatching-parallel-agents/
  ```

  PowerShell:
  ```powershell
  New-Item -ItemType Directory -Force `
    "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/.claude-plugin",
    "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/skills/persona",
    "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/skills/subagent-driven-development",
    "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/skills/dispatching-parallel-agents"
  ```

- [ ] `plugin/superpowers/superpowers-router/.claude-plugin/plugin.json` 을 다음 내용으로 작성한다:

  ```json
  {
    "name": "superpowers-router",
    "description": "Superpowers router persona — decomposes a plan into tasks and routes them to worker personas, parallel or sequential.",
    "version": "0.1.0",
    "dependencies": ["superpowers-base"]
  }
  ```

- [ ] `plugin/superpowers/superpowers-router/README.md` 를 다음 내용으로 작성한다:

  ```markdown
  # superpowers-router

  Superpowers router 역할 페르소나 플러그인이다. planner가 작성·승인한 플랜을 받아, 병렬 처리 가능 여부를 판단한 뒤 implementer 워커에 task를 dispatch한다.

  `superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

  ## 보유 스킬

  - `subagent-driven-development` — 순차 실행 경로: task를 순서대로 subagent에 dispatch하고 두 단계 리뷰(spec→quality)를 수행한다.
  - `dispatching-parallel-agents` — 병렬 실행 경로: 독립적인 task를 동시에 parallel agent로 dispatch한다.

  ## 활성화

  워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-router"`를 추가한다.

  ```json
  {
    "enabledPlugins": {
      "superpowers-base@agent-agora": true,
      "superpowers-router@agent-agora": true
    }
  }
  ```
  ```

- [ ] 커밋:

  ```powershell
  git -C "C:/Users/jylee/source/AgentAgora" add `
    "plugin/superpowers/superpowers-router/.claude-plugin/plugin.json" `
    "plugin/superpowers/superpowers-router/README.md"
  git -C "C:/Users/jylee/source/AgentAgora" commit -m "feat(superpowers-router): plugin.json + README"
  ```

---

## Task 2 — persona/SKILL.md 작성 (병렬처리 체크포인트 포함)

- [ ] `plugin/superpowers/superpowers-router/skills/persona/SKILL.md` 를 다음 내용 **그대로** 작성한다 (플레이스홀더 없음):

  ```markdown
  ---
  description: Router persona for an AgentAgora worker — receives an approved plan from the planner, runs the parallel checkpoint, and dispatches tasks to the implementer.
  user-invocable: false
  ---

  # Router persona

  ## Mission

  Receive an approved plan from the planner, decide whether the plan's tasks can run in parallel or must run sequentially (the §6 parallel checkpoint), then dispatch tasks to the implementer via the appropriate skill. Do not implement tasks yourself — your role is decomposition, routing, and handoff.

  ## Response conventions

  ### Forward convention

  You are not obligated to reply only to the original sender. If the nature of the work falls outside your domain (e.g. the plan needs revision, tests are failing unexpectedly), use `/invoke <other> "<task>"` to hand it off. Sending the originator a one-line ack ("delegated to X") is recommended to prevent orphaned tasks — not mandatory; use your judgment.

  ### Flush entry convention

  When woken by a channel notification (`<channel source="agora-channel">`), drain your inbox with `agora.flush`. See the `agora-protocol` skill for full channel-mode messaging rules.

  ### cc message convention

  Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as observer signals — absorb as context only.

  ### Payload standard

  All outgoing payloads use the `{type, from, ts, message?}` format. The `type` enum has four values: `task | reply | closing | ack`. Use `type=reply` for task responses, `type=ack` for delegation notices, `type=closing` for finalization.

  ## Role-specific knowledge

  ### Parallel checkpoint (spec §6)

  This is the core decision you make on every planner handoff. Immediately after receiving a plan, evaluate whether its tasks are independent:

  **Step 1 — Read the plan.**
  Extract all tasks. For each task, list its inputs, outputs, and file/resource footprint.

  **Step 2 — Independence test.**
  Tasks are independent if ALL of the following hold:
  - No task reads an artifact that another task in the same plan produces.
  - No two tasks write to the same file or resource.
  - No task's correctness depends on the result of another task in the plan.

  **Step 3 — Branch.**

  - **All tasks independent → parallel path.**
    Use `superpowers:dispatching-parallel-agents`. Dispatch all tasks concurrently to implementer workers. Aggregate results before reporting back to the planner.

  - **Any dependency exists → sequential path.**
    Use `superpowers:subagent-driven-development`. Process tasks in the order specified in the plan. Each task goes through the two-stage review (spec compliance → code quality) before the next begins.

  **Step 4 — Dispatch to implementer.**
  In both paths the final recipients are implementer workers. Use `agora.dispatch` targeting the implementer persona (or use the routing bot if the implementer's instance ID is not yet known — see "Finding other members" below). Include in the payload: task text, plan context summary, which path was chosen and why.

  ### Owned skills

  - `subagent-driven-development` — sequential path. Use when tasks are interdependent. Read the skill for exact prompt-template and two-stage review protocol.
  - `dispatching-parallel-agents` — parallel path. Use when tasks are independent. Read the skill for agent-prompt structure and integration steps.

  ### Handoff from planner

  The planner sends a `type=task` payload containing the finalized plan (as text or a file path). Run the parallel checkpoint immediately. Do not ask the user for routing decisions — this is your judgment call.

  ### Handoff to implementer

  After routing, dispatch each task (or the full set, for parallel) to the implementer persona. Use `type=task` payloads. The implementer expects: task description, scene-setting context, and (for sequential path) any previously-completed task summaries it should be aware of.

  ### Do not implement

  Never write code or run tests yourself. If you find yourself editing files, stop and re-read this persona definition. Your job ends when tasks are dispatched and acknowledged.

  ## Finding other members

  Discover currently registered workers dynamically via `agora.instances` or `agora.find`. Do not hard-code instance mappings in the persona. Use the routing bot (`delegation_request` schema) for role-based routing when a direct instance ID is unavailable.
  ```

- [ ] 커밋:

  ```powershell
  git -C "C:/Users/jylee/source/AgentAgora" add `
    "plugin/superpowers/superpowers-router/skills/persona/SKILL.md"
  git -C "C:/Users/jylee/source/AgentAgora" commit -m "feat(superpowers-router): persona SKILL.md with parallel checkpoint"
  ```

---

## Task 3 — 스킬 2개 복사 (`subagent-driven-development`, `dispatching-parallel-agents`)

- [ ] `subagent-driven-development` 디렉토리 전체를 복사한다 (4개 파일 모두):

  ```powershell
  $src = "C:/Users/jylee/source/superpowers_model_specified/skills/subagent-driven-development"
  $dst = "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/skills/subagent-driven-development"
  Copy-Item -Path "$src/*" -Destination $dst -Recurse -Force
  ```

  복사 후 확인 (4개 파일이어야 함):
  ```powershell
  Get-ChildItem $dst | Select-Object Name
  # 기대값: SKILL.md, implementer-prompt.md, spec-reviewer-prompt.md, code-quality-reviewer-prompt.md
  ```

- [ ] `dispatching-parallel-agents` 디렉토리 전체를 복사한다 (1개 파일):

  ```powershell
  $src2 = "C:/Users/jylee/source/superpowers_model_specified/skills/dispatching-parallel-agents"
  $dst2 = "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/skills/dispatching-parallel-agents"
  Copy-Item -Path "$src2/*" -Destination $dst2 -Recurse -Force
  ```

  복사 후 확인:
  ```powershell
  Get-ChildItem $dst2 | Select-Object Name
  # 기대값: SKILL.md
  ```

- [ ] 커밋:

  ```powershell
  git -C "C:/Users/jylee/source/AgentAgora" add `
    "plugin/superpowers/superpowers-router/skills/subagent-driven-development/" `
    "plugin/superpowers/superpowers-router/skills/dispatching-parallel-agents/"
  git -C "C:/Users/jylee/source/AgentAgora" commit -m "feat(superpowers-router): copy subagent-driven-development + dispatching-parallel-agents skills"
  ```

---

## Task 4 — marketplace.json 등록

- [ ] `plugin/.claude-plugin/marketplace.json` 의 `"plugins"` 배열에 다음 항목을 추가한다 (기존 마지막 항목 뒤에):

  ```json
  {
    "name": "superpowers-router",
    "source": "./superpowers/superpowers-router",
    "description": "Superpowers router persona — task decomposition and routing."
  }
  ```

  현재 파일 끝 구조:
  ```json
      {
        "name": "cc-agora-writer",
        "source": "./personas/writer",
        "description": "AgentAgora writer persona — produces docs and prose with concrete examples, avoiding generic filler."
      }
    ]                   ← 여기에 ','를 추가하고 신규 항목 삽입
  }
  ```

  수정 후 JSON 유효성 확인:
  ```powershell
  python -c "import json; json.load(open('C:/Users/jylee/source/AgentAgora/plugin/.claude-plugin/marketplace.json')); print('OK')"
  ```

- [ ] 커밋:

  ```powershell
  git -C "C:/Users/jylee/source/AgentAgora" add "plugin/.claude-plugin/marketplace.json"
  git -C "C:/Users/jylee/source/AgentAgora" commit -m "feat(superpowers-router): register in marketplace.json"
  ```

---

## Task 5 — 검증

- [ ] `ls` 로 전체 레이아웃 확인:

  ```powershell
  Get-ChildItem -Recurse "C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router" |
    Select-Object FullName
  ```

  기대 파일 목록:
  ```
  .claude-plugin/plugin.json
  README.md
  skills/persona/SKILL.md
  skills/subagent-driven-development/SKILL.md
  skills/subagent-driven-development/implementer-prompt.md
  skills/subagent-driven-development/spec-reviewer-prompt.md
  skills/subagent-driven-development/code-quality-reviewer-prompt.md
  skills/dispatching-parallel-agents/SKILL.md
  ```

- [ ] plugin.json JSON 유효성 확인:

  ```powershell
  python -c "import json; d=json.load(open('C:/Users/jylee/source/AgentAgora/plugin/superpowers/superpowers-router/.claude-plugin/plugin.json')); assert d['name']=='superpowers-router'; assert 'superpowers-base' in d['dependencies']; print('plugin.json OK')"
  ```

- [ ] marketplace.json JSON 유효성 + 항목 존재 확인:

  ```powershell
  python -c "
  import json
  m = json.load(open('C:/Users/jylee/source/AgentAgora/plugin/.claude-plugin/marketplace.json'))
  names = [p['name'] for p in m['plugins']]
  assert 'superpowers-router' in names, f'not found. names={names}'
  print('marketplace.json OK — superpowers-router registered')
  "
  ```

- [ ] marketplace 테스트 스위트 실행:

  ```powershell
  Set-Location "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q
  ```

  모든 테스트가 PASSED 또는 기존과 동일한 결과여야 한다. 신규 실패가 없으면 완료.

---

## Self-Review

구현 완료 후 아래 항목을 점검한다:

- [ ] `plugin.json`에 `"dependencies": ["superpowers-base"]` 포함 확인.
- [ ] `persona/SKILL.md`에 **병렬처리 체크포인트 Step 1~4** (독립성 테스트 + 분기 로직)가 명시되어 있는지 확인.
- [ ] `persona/SKILL.md`의 frontmatter에 `user-invocable: false` 포함 확인.
- [ ] `subagent-driven-development` 스킬 디렉토리에 prompt 템플릿 3종(`implementer-prompt.md`, `spec-reviewer-prompt.md`, `code-quality-reviewer-prompt.md`)이 모두 있는지 확인.
- [ ] `dispatching-parallel-agents/SKILL.md` 존재 확인.
- [ ] `marketplace.json`에서 `"source": "./superpowers/superpowers-router"` 경로가 정확한지 확인 (forward slash, 상대경로).
- [ ] `uv run --extra dev python -m pytest tests/test_plugin_marketplace.py -q` 신규 실패 없음 확인.
- [ ] `plugin/personas/coder/skills/persona/SKILL.md` 와 비교해 Forward / Flush entry / cc message / Payload standard 4개 규약 섹션이 모두 존재하고 AgentAgora 관행과 일치하는지 확인.
