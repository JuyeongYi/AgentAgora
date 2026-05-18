# superpowers 페르소나 분리 — 통합 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 플랜 1–8 산출물(7개 페르소나 플러그인 + 라우팅 봇)을 하나로 묶어, `roles.json` 매핑·`comm-matrix.csv` ACL·위임 메타·라우팅 봇 기동 wiring을 완성하고, 전체 워크플로 위임 흐름이 동작하는 상태를 만든다.

**Architecture:** 설계 spec §5·§9·§12(플랜 9) 기준. 7개 페르소나 워커는 AgentAgora 브로커를 경유해 `agora.dispatch`로 핸드오프한다. 허용 엣지는 spec §9 워크플로(planner→router→implementer↔debugger/reviewer→improver→planner)만이며 나머지 페르소나 간 엣지는 모두 `comm-matrix.csv`로 차단한다. 라우팅 봇은 `delegation_request` 스키마를 구독해 `to_capability` 기반 대상 resolve를 담당하며, `agora-setup` 흐름에 기동 단계가 추가된다.

**Tech Stack:** AgentAgora comm-matrix·comm-matrix.csv·roles.json·schemas, Claude Code 플러그인.

---

## 파일 구조

```
.agentagora/
  comm-matrix.csv                       신규 생성 — 페르소나 간 위임 ACL
  schemas.jsonl                         수정 — delegation_request 스키마 추가

plugin/cc-agora-ops/config/
  roles.json                            수정 — 7개 페르소나 role 항목 추가

plugin/.claude-plugin/
  marketplace.json                      검증 — 7개 superpowers-* 플러그인 모두 등록돼 있어야 함

plugin/superpowers/
  superpowers-base/skills/writing-skills/SKILL.md      수정 — 위임 메타 추가
  superpowers-planner/skills/brainstorming/SKILL.md    수정 — 위임 메타 추가
  superpowers-planner/skills/writing-plans/SKILL.md    수정 — 위임 메타 추가
  superpowers-router/skills/persona/SKILL.md           수정 — 병렬 체크포인트 위임 분기 명시
  superpowers-implementer/skills/test-driven-development/SKILL.md  수정 — 위임 메타 추가
  superpowers-implementer/skills/finishing-a-development-branch/SKILL.md  수정 — 위임 메타 추가
  superpowers-debugger/skills/systematic-debugging/SKILL.md   수정 — 위임 메타 추가
  superpowers-reviewer/skills/requesting-code-review/SKILL.md  수정 — 위임 메타 추가
  superpowers-improver/skills/improvement-review/SKILL.md      수정 — 위임 메타 추가

plugin/cc-agora-ops/skills/agora-setup/SKILL.md        수정 — 라우팅 봇 기동 단계 추가

examples/routing_bot/ (or plugin/superpowers/routing-bot/)   플랜 8 산출물 — 위치 확인만
```

---

## Task 1: `roles.json` — 7개 페르소나 role 항목 추가

`plugin/cc-agora-ops/config/roles.json`의 현재 포맷(키 = role 이름, 값 = `{ "plugin": "<plugin-name>" }`)을 그대로 따라 7개 항목을 추가한다.

- [ ] `plugin/cc-agora-ops/config/roles.json`을 읽어 현재 내용을 확인한다.

- [ ] 다음 7개 항목을 기존 마지막 항목(`"general"`) 뒤에 추가한다. **전체 결과 파일 내용:**

  ```json
  {
    "orchestrator": { "plugin": "cc-agora-orchestrator" },
    "coder":        { "plugin": "cc-agora-coder" },
    "reviewer":     { "plugin": "cc-agora-reviewer" },
    "tester":       { "plugin": "cc-agora-tester" },
    "writer":       { "plugin": "cc-agora-writer" },
    "planner":      { "plugin": "cc-agora-planner" },
    "general":      { "plugin": "cc-agora-general" },
    "sp-planner":   { "plugin": "superpowers-planner" },
    "sp-implementer": { "plugin": "superpowers-implementer" },
    "sp-debugger":  { "plugin": "superpowers-debugger" },
    "sp-reviewer":  { "plugin": "superpowers-reviewer" },
    "sp-router":    { "plugin": "superpowers-router" },
    "sp-improver":  { "plugin": "superpowers-improver" },
    "sp-base":      { "plugin": "superpowers-base" }
  }
  ```

  role 이름 설계 근거: `sp-` 접두사로 기존 `planner`/`reviewer`와 충돌 없이 공존한다. `sp-base`는 라이브러리이지만 `agora-spawn`으로 standalone 기동이 필요한 경우를 위해 등록한다.

- [ ] JSON 유효성 확인:
  ```bash
  python -c "
  import json
  with open('plugin/cc-agora-ops/config/roles.json') as f:
      d = json.load(f)
  required = ['sp-planner','sp-implementer','sp-debugger','sp-reviewer','sp-router','sp-improver','sp-base']
  for r in required:
      assert r in d, f'missing role: {r}'
      assert 'plugin' in d[r], f'missing plugin key for: {r}'
  print('roles.json OK — 14 roles:', list(d.keys()))
  "
  ```

- [ ] 커밋:
  ```bash
  git add plugin/cc-agora-ops/config/roles.json
  git commit -m "feat: roles.json에 superpowers 페르소나 7개 role 추가 (sp-planner 등)"
  ```

---

## Task 2: `comm-matrix.csv` — 페르소나 간 위임 ACL

spec §9 워크플로 엣지를 허용 셀(weight > 0)로, 나머지를 0으로 인코딩한다. 헤더·행 라벨은 `re.fullmatch` 패턴이다.

**엣지 목록 (from → to, spec §9):**
- planner → router
- router → implementer
- implementer → debugger
- implementer → reviewer
- debugger → implementer
- reviewer → implementer
- implementer → improver
- improver → planner

**Weight 결정:** 모든 허용 엣지를 weight `1`로 동일하게 설정한다. 우선순위 차등이 필요한 경우(예: debugger→implementer 복귀가 더 급박) 향후 `POST /admin/comm-matrix`로 런타임 조정한다. 이 플랜에서는 단순 허용/차단만 구분한다.

**인스턴스 id 패턴 결정:** `agora-spawn`이 생성하는 워커 인스턴스 id는 `<role>-<suffix>` 형태(예: `sp-planner-0`, `sp-planner-abc123`)이므로, 패턴은 `sp-planner-.*` 형식을 사용한다. `.*` catch-all 행·열도 추가해 비-페르소나 워커(기존 `coder`, `orchestrator` 등) 간 디스패치는 영향받지 않도록 폴백 weight를 `1`로 설정한다.

**CSV 형식 설명:** 첫 행 = from 패턴(열 헤더, 첫 셀은 행 라벨 자리로 빈칸). 이후 각 행 = to 패턴(행 라벨), 각 셀 = `matrix[to][from]` weight.

- [ ] `.agentagora/` 디렉토리가 없으면 생성한다:
  ```bash
  mkdir -p "C:/Users/jylee/source/AgentAgora/.agentagora"
  ```

- [ ] `.agentagora/comm-matrix.csv`를 다음 내용으로 생성한다. **전체 CSV 내용:**

  ```
  ,sp-planner-.*,sp-router-.*,sp-implementer-.*,sp-debugger-.*,sp-reviewer-.*,sp-improver-.*,.*
  sp-planner-.*,0,0,0,0,0,1,0
  sp-router-.*,1,0,0,0,0,0,0
  sp-implementer-.*,0,1,0,1,1,0,0
  sp-debugger-.*,0,0,1,0,0,0,0
  sp-reviewer-.*,0,0,1,0,0,0,0
  sp-improver-.*,0,0,1,0,0,0,0
  .*,0,0,0,0,0,0,1
  ```

  행렬 해석:
  - `(to=sp-router-.*,    from=sp-planner-.*)` = 1 → planner→router 허용
  - `(to=sp-implementer-.*,from=sp-router-.*)`  = 1 → router→implementer 허용
  - `(to=sp-debugger-.*,  from=sp-implementer-.*)` = 1 → implementer→debugger 허용
  - `(to=sp-reviewer-.*,  from=sp-implementer-.*)` = 1 → implementer→reviewer 허용
  - `(to=sp-implementer-.*,from=sp-debugger-.*)`  = 1 → debugger→implementer 허용
  - `(to=sp-implementer-.*,from=sp-reviewer-.*)` = 1 → reviewer→implementer 허용
  - `(to=sp-improver-.*,  from=sp-implementer-.*)` = 1 → implementer→improver 허용
  - `(to=sp-planner-.*,   from=sp-improver-.*)` = 1 → improver→planner 허용 (ouroboros)
  - `(to=.*,              from=.*)` = 1 → 비-페르소나 워커 간 폴백 허용
  - 나머지 페르소나 간 조합 = 0 → 차단

  **주의:** `.*` catch-all 행·열은 (N+1)×(N+1) 정사각을 만든다. 현재 CSV는 7개 페르소나 패턴 + 1개 catch-all = 8×8.

- [ ] CSV 파싱 검증:
  ```bash
  python -c "
  import sys
  sys.path.insert(0, 'src')
  from agent_agora.comm_matrix import load_comm_matrix
  from pathlib import Path
  cm = load_comm_matrix(Path('.agentagora/comm-matrix.csv'))
  assert cm.active, 'matrix not active'

  # 허용 엣지 검증
  allowed = [
      ('sp-planner-0',     'sp-router-0'),
      ('sp-router-0',      'sp-implementer-0'),
      ('sp-implementer-0', 'sp-debugger-0'),
      ('sp-implementer-0', 'sp-reviewer-0'),
      ('sp-debugger-0',    'sp-implementer-0'),
      ('sp-reviewer-0',    'sp-implementer-0'),
      ('sp-implementer-0', 'sp-improver-0'),
      ('sp-improver-0',    'sp-planner-0'),
  ]
  for frm, to in allowed:
      assert cm.is_allowed(frm, to), f'FAIL allowed: {frm} -> {to}'
      print(f'  OK  {frm} -> {to}')

  # 차단 엣지 검증 (예: planner→implementer 직통은 차단)
  blocked = [
      ('sp-planner-0',     'sp-implementer-0'),
      ('sp-planner-0',     'sp-debugger-0'),
      ('sp-router-0',      'sp-planner-0'),
      ('sp-debugger-0',    'sp-router-0'),
      ('sp-improver-0',    'sp-debugger-0'),
  ]
  for frm, to in blocked:
      assert not cm.is_allowed(frm, to), f'FAIL blocked: {frm} -> {to}'
      print(f'  OK blocked: {frm} -> {to}')

  # catch-all: 비-페르소나 워커 간 허용
  assert cm.is_allowed('coder-0', 'orchestrator-0'), 'FAIL: non-persona fallback'
  print('  OK non-persona fallback')
  print('comm-matrix OK')
  "
  ```

- [ ] 커밋:
  ```bash
  git add .agentagora/comm-matrix.csv
  git commit -m "feat: comm-matrix.csv — superpowers 페르소나 워크플로 ACL (spec §9 엣지)"
  ```

---

## Task 3: `schemas.jsonl` — `delegation_request` 스키마 등록

플랜 8(라우팅 봇)에서 스키마가 이미 추가됐는지 확인하고, 없으면 추가한다.

- [ ] `.agentagora/schemas.jsonl` 파일이 존재하는지 확인한다:
  ```bash
  python -c "
  from pathlib import Path
  p = Path('.agentagora/schemas.jsonl')
  if p.exists():
      lines = [l.strip() for l in p.read_text('utf-8').splitlines() if l.strip()]
      print(f'schemas.jsonl exists — {len(lines)} schema(s)')
      for l in lines:
          import json; d=json.loads(l); print(' -', d['name'])
  else:
      print('schemas.jsonl NOT FOUND — will create')
  "
  ```

- [ ] `delegation_request` 스키마가 없으면 `.agentagora/schemas.jsonl`에 다음 줄을 추가한다(파일이 없으면 신규 생성):

  ```json
  {"name":"delegation_request","kind":"bot-task","purpose":"페르소나 워커가 다른 역할/역량이 필요할 때 라우팅 봇으로 위임 요청을 emit하는 스키마. to_capability 미지정 시 봇이 agora.find로 대상 resolve.","body":{"type":"object","required":["msgtype","from_persona","payload","context_summary"],"properties":{"msgtype":{"type":"string","const":"delegation_request"},"from_persona":{"type":"string","description":"발신 페르소나 role (예: sp-planner)"},"to_persona":{"type":"string","description":"명시적 대상 인스턴스 id (선택 — 지정 시 봇이 직접 dispatch)"},"to_capability":{"type":"string","description":"대상 역할/역량 (예: sp-implementer). to_persona 미지정 시 봇이 agora.find로 resolve."},"payload":{"type":"object","description":"위임 내용. 수신 페르소나에 전달되는 task 본문."},"context_summary":{"type":"string","description":"현재까지 진행 상황 요약 — 수신 페르소나가 컨텍스트 없이도 이어받을 수 있도록."}},"additionalProperties":false}}
  ```

- [ ] 스키마 등록 확인:
  ```bash
  python -c "
  import json
  from pathlib import Path
  lines = [l for l in Path('.agentagora/schemas.jsonl').read_text('utf-8').splitlines() if l.strip()]
  schemas = [json.loads(l) for l in lines]
  names = [s['name'] for s in schemas]
  assert 'delegation_request' in names, 'delegation_request schema not found'
  dr = next(s for s in schemas if s['name'] == 'delegation_request')
  assert dr['kind'] == 'bot-task'
  required = dr['body']['required']
  assert 'from_persona' in required and 'payload' in required and 'context_summary' in required
  print('delegation_request schema OK — required fields:', required)
  "
  ```

- [ ] 커밋:
  ```bash
  git add .agentagora/schemas.jsonl
  git commit -m "feat: schemas.jsonl에 delegation_request 스키마 등록"
  ```

---

## Task 4: `marketplace.json` 등록 확인 (7개 플러그인)

플랜 1–7이 각자 자기 항목을 marketplace.json에 추가했는지 검증한다. 누락 항목은 여기서 추가한다.

- [ ] 7개 플러그인 등록 상태 검증:
  ```bash
  python -c "
  import json
  with open('plugin/.claude-plugin/marketplace.json') as f:
      data = json.load(f)
  names = {p['name'] for p in data['plugins']}
  required = [
      'superpowers-base',
      'superpowers-planner',
      'superpowers-implementer',
      'superpowers-debugger',
      'superpowers-reviewer',
      'superpowers-router',
      'superpowers-improver',
  ]
  missing = [r for r in required if r not in names]
  if missing:
      print('MISSING from marketplace.json:', missing)
  else:
      print('OK — all 7 superpowers-* plugins registered')
      print('All plugins:', sorted(names))
  "
  ```

- [ ] 누락 항목이 있으면 다음 형식으로 `plugins` 배열에 추가한다 (없는 항목만):
  ```json
  { "name": "superpowers-base",        "source": "./superpowers/superpowers-base",        "description": "Superpowers persona base — shared skills every persona needs." },
  { "name": "superpowers-planner",     "source": "./superpowers/superpowers-planner",     "description": "Superpowers planner persona — brainstorming and writing plans." },
  { "name": "superpowers-implementer", "source": "./superpowers/superpowers-implementer", "description": "Superpowers implementer persona — TDD, plan execution, git worktrees, branch finishing." },
  { "name": "superpowers-debugger",    "source": "./superpowers/superpowers-debugger",    "description": "Superpowers debugger persona — systematic debugging." },
  { "name": "superpowers-reviewer",    "source": "./superpowers/superpowers-reviewer",    "description": "Superpowers reviewer persona — requesting and receiving code review." },
  { "name": "superpowers-router",      "source": "./superpowers/superpowers-router",      "description": "Superpowers router persona — subagent dispatch and parallel agent orchestration." },
  { "name": "superpowers-improver",    "source": "./superpowers/superpowers-improver",    "description": "Superpowers improver persona — improvement review and ouroboros loop trigger." }
  ```

- [ ] JSON 유효성 최종 확인:
  ```bash
  python -c "
  import json
  with open('plugin/.claude-plugin/marketplace.json') as f:
      data = json.load(f)
  print('marketplace.json valid — total plugins:', len(data['plugins']))
  "
  ```

- [ ] 변경사항이 있으면 커밋:
  ```bash
  git add plugin/.claude-plugin/marketplace.json
  git commit -m "feat: marketplace.json superpowers-* 7개 플러그인 등록 확인·보완"
  ```

---

## Task 5: 위임 메타 추가 — 스킬 본문 annotation

spec §5 "스킬 본문 위임 메타" 요구사항: 각 스킬에 다음 단계 위임 대상 페르소나를 명시한다. `writing-skills`(base)→`superpowers:test-driven-development`(implementer) cross-plugin 참조 끊김 케이스도 처리한다.

**annotation 형식:** 각 SKILL.md의 frontmatter에 `delegation-target` 키를 추가하고, 스킬 본문 마지막에 `## Handoff` 섹션을 붙인다. 기존 본문은 수정하지 않는다.

### 5-a: `writing-skills` cross-plugin 참조 수정

`superpowers-base/skills/writing-skills/SKILL.md`에서 `superpowers:test-driven-development` 참조가 있으면 플러그인 분리로 인해 끊길 수 있다. 두 플러그인이 동시에 활성화된 워커에서는 이름으로 resolve되므로 대부분 무해하지만, 명시적 힌트를 추가해 둔다.

- [ ] `plugin/superpowers/superpowers-base/skills/writing-skills/SKILL.md`의 frontmatter에 아래 키를 추가한다:
  ```yaml
  delegation-note: "superpowers:test-driven-development is in superpowers-implementer plugin. Ensure that plugin is active in the same worker, or dispatch to sp-implementer persona."
  ```

- [ ] `writing-skills` SKILL.md 파일 끝에 다음 섹션을 추가한다:
  ```markdown
  ## Cross-plugin reference note

  `superpowers:test-driven-development` is defined in the `superpowers-implementer` plugin.
  If skill resolution fails (worker does not have `superpowers-implementer` active),
  dispatch to the `sp-implementer` persona via `agora.dispatch` instead of invoking the skill directly.
  ```

### 5-b: `writing-plans` → router 위임 메타

- [ ] `plugin/superpowers/superpowers-planner/skills/writing-plans/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-router"
  delegation-schema: "delegation_request"
  ```

- [ ] 파일 끝에 추가:
  ```markdown
  ## Handoff

  When the plan is finalized, emit a `delegation_request` to `sp-router` (or dispatch directly with `agora.dispatch`).
  Payload: `{ "plan": "<plan content or file path>", "tasks": [...] }`.
  `context_summary`: brief statement of what was planned and the top-level goal.
  ```

### 5-c: `brainstorming` → planner 내부 연결 메타

- [ ] `plugin/superpowers/superpowers-planner/skills/brainstorming/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "superpowers:writing-plans"
  delegation-note: "brainstorming completes in-persona; invoke writing-plans next within the same planner worker."
  ```

### 5-d: `subagent-driven-development` / `dispatching-parallel-agents` → implementer 위임 메타

- [ ] `plugin/superpowers/superpowers-router/skills/subagent-driven-development/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-implementer"
  delegation-schema: "delegation_request"
  ```

- [ ] `plugin/superpowers/superpowers-router/skills/dispatching-parallel-agents/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-implementer"
  delegation-schema: "delegation_request"
  delegation-note: "Dispatch one delegation_request per parallel implementer subagent."
  ```

### 5-e: `test-driven-development` / `executing-plans` → implementer 내부; `finishing-a-development-branch` → improver

- [ ] `plugin/superpowers/superpowers-implementer/skills/test-driven-development/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-note: "in-persona skill; no cross-persona dispatch. Proceed to executing-plans within the same implementer worker."
  ```

- [ ] `plugin/superpowers/superpowers-implementer/skills/finishing-a-development-branch/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-improver"
  delegation-schema: "delegation_request"
  ```

- [ ] `finishing-a-development-branch` SKILL.md 끝에 추가:
  ```markdown
  ## Handoff

  After branch finishing is complete, emit a `delegation_request` to `sp-improver`.
  Payload: `{ "branch": "<branch name>", "summary": "<what was built>" }`.
  `context_summary`: summary of the implementation just completed.
  ```

### 5-f: `systematic-debugging` → implementer 위임 메타

- [ ] `plugin/superpowers/superpowers-debugger/skills/systematic-debugging/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-implementer"
  delegation-schema: "delegation_request"
  ```

- [ ] 파일 끝에 추가:
  ```markdown
  ## Handoff

  When root cause is identified and fix is ready, emit a `delegation_request` back to `sp-implementer`.
  Payload: `{ "fix": "<description or patch>", "root_cause": "<analysis>" }`.
  `context_summary`: what bug was found and what fix is proposed.
  ```

### 5-g: `requesting-code-review` → implementer 위임 메타

- [ ] `plugin/superpowers/superpowers-reviewer/skills/requesting-code-review/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-implementer"
  delegation-schema: "delegation_request"
  delegation-note: "requesting-code-review initiates the review; receiving-code-review handles the result. After review is complete, dispatch review findings back to sp-implementer."
  ```

- [ ] 파일 끝에 추가:
  ```markdown
  ## Handoff

  After review is complete, emit a `delegation_request` to `sp-implementer`.
  Payload: `{ "review_result": "<approved|changes_requested>", "comments": [...] }`.
  `context_summary`: code reviewed, key findings, and recommended next action.
  ```

### 5-h: `improvement-review` → planner 위임 메타

- [ ] `plugin/superpowers/superpowers-improver/skills/improvement-review/SKILL.md` frontmatter에 추가:
  ```yaml
  delegation-target: "sp-planner"
  delegation-schema: "delegation_request"
  delegation-note: "If user approves another cycle, dispatch findings to sp-planner to restart the workflow loop."
  ```

- [ ] 파일 끝에 추가:
  ```markdown
  ## Handoff

  If the user approves a new improvement cycle, emit a `delegation_request` to `sp-planner`.
  Payload: `{ "findings": { "improvements": [...], "refactoring": [...], "new_features": [...] } }`.
  `context_summary`: what was reviewed, what opportunities were found.

  If the user declines, end the workflow. Do not emit a dispatch.
  ```

- [ ] 위임 메타 추가된 SKILL.md 파일들 일괄 커밋:
  ```bash
  git add plugin/superpowers/
  git commit -m "feat: 페르소나 스킬에 위임 메타(delegation-target, Handoff 섹션) 추가 — spec §5"
  ```

---

## Task 6: `agora-setup` SKILL.md — 라우팅 봇 기동 wiring

spec §10: 라우팅 봇은 서버·워커와 별개 프로세스 — 배포 시 함께 기동해야 한다. `agora-setup` 흐름의 "Closing" 섹션에 라우팅 봇 기동 안내를 추가한다.

- [ ] `plugin/cc-agora-ops/skills/agora-setup/SKILL.md`의 `## Closing` 섹션을 다음 내용으로 교체한다:

  기존:
  ```markdown
  ## Closing

  Tell the operator the launch order: first run `run-cc-agora` to start the server
  and confirm it is up, then run each worker's `run.ps1`/`run.sh` from inside its
  directory. The server must be up before any worker connects — a worker registers
  with the server when its MCP client connects at session start, and Claude Code
  connects MCP servers before it runs any `SessionStart` hook, so a hook cannot
  bring the server up in time. A standalone launch script run first is the only
  reliable ordering.
  ```

  교체 후:
  ```markdown
  ## Closing

  Tell the operator the launch order:

  1. Run `run-cc-agora` (or `run-cc-agora.ps1` on Windows) to start the AgentAgora server.
     Confirm it is up (it prints the listening port).
  2. If a routing bot is deployed (e.g. `examples/routing_bot/run-routing-bot.ps1`), start it next.
     The routing bot subscribes to `delegation_request` and must be running before persona workers
     begin emitting delegation requests.
  3. Run each worker's `run.ps1`/`run.sh` from inside its directory.

  The server must be up before any worker connects — a worker registers with the server when its
  MCP client connects at session start, and Claude Code connects MCP servers before it runs any
  `SessionStart` hook, so a hook cannot bring the server up in time. A standalone launch script
  run first is the only reliable ordering. The routing bot has the same constraint — it connects
  at startup, so it must come up after the server but before the persona workers.

  ### Superpowers persona deployment note

  If deploying superpowers persona workers (`sp-planner`, `sp-router`, `sp-implementer`, etc.),
  also confirm:
  - `.agentagora/comm-matrix.csv` is present (enforces §9 workflow ACL).
  - `.agentagora/schemas.jsonl` contains the `delegation_request` schema.
  - `plugin/cc-agora-ops/config/roles.json` has `sp-planner`, `sp-router`, etc. mapped to
    their `superpowers-*` plugins.
  - The routing bot is running before persona workers start.
  ```

- [ ] 변경 확인:
  ```bash
  python -c "
  content = open('plugin/cc-agora-ops/skills/agora-setup/SKILL.md').read()
  assert 'routing bot' in content.lower(), 'routing bot mention missing'
  assert 'delegation_request' in content, 'delegation_request mention missing'
  assert 'comm-matrix.csv' in content, 'comm-matrix.csv mention missing'
  print('agora-setup SKILL.md OK')
  "
  ```

- [ ] 커밋:
  ```bash
  git add plugin/cc-agora-ops/skills/agora-setup/SKILL.md
  git commit -m "feat: agora-setup에 라우팅 봇 기동 순서 및 superpowers 배포 체크리스트 추가"
  ```

---

## Task 7: 라우팅 봇 산출물 위치 확인 (플랜 8 의존성)

플랜 8 산출물이 올바르게 배치됐는지 확인한다. 이 태스크는 실행이 아닌 검증이다.

- [ ] 라우팅 봇 스크립트 위치 확인:
  ```bash
  python -c "
  from pathlib import Path
  # 플랜 8에서 확정된 위치 후보
  candidates = [
      'examples/routing_bot/routing_bot.py',
      'plugin/superpowers/routing-bot/routing_bot.py',
  ]
  found = [c for c in candidates if Path(c).exists()]
  if found:
      print('Routing bot found at:', found)
  else:
      print('ERROR: routing bot script not found. Plan 8 must be complete before Plan 9.')
      raise SystemExit(1)
  "
  ```

- [ ] 라우팅 봇 런처 스크립트 확인 (Windows `.ps1` 또는 Unix `.sh`):
  ```bash
  python -c "
  from pathlib import Path
  import glob
  launchers = glob.glob('examples/routing_bot/run-*.ps1') + \
              glob.glob('examples/routing_bot/run-*.sh') + \
              glob.glob('plugin/superpowers/routing-bot/run-*.ps1') + \
              glob.glob('plugin/superpowers/routing-bot/run-*.sh')
  if launchers:
      print('Routing bot launcher(s):', launchers)
  else:
      print('ERROR: no routing bot launcher found.')
      raise SystemExit(1)
  "
  ```

- [ ] 라우팅 봇이 `delegation_request` 스키마를 구독하는지 확인:
  ```bash
  python -c "
  from pathlib import Path
  import glob
  bot_files = glob.glob('examples/routing_bot/*.py') + \
              glob.glob('plugin/superpowers/routing-bot/*.py')
  for f in bot_files:
      content = Path(f).read_text('utf-8')
      if 'delegation_request' in content:
          print(f'OK: {f} subscribes to delegation_request')
          break
  else:
      print('ERROR: no routing bot file subscribes to delegation_request')
      raise SystemExit(1)
  "
  ```

  라우팅 봇이 없으면 플랜 8을 먼저 실행한다. 이 태스크는 플랜 8 완료를 전제로 한다.

---

## Task 8: 종단 통합 검증

모든 아티팩트가 일관성 있게 맞물리는지 확인한다.

- [ ] `roles.json` × `marketplace.json` 일관성 확인 — roles의 모든 `plugin` 값이 marketplace에 등록돼 있는지:
  ```bash
  python -c "
  import json
  roles = json.load(open('plugin/cc-agora-ops/config/roles.json'))
  market = json.load(open('plugin/.claude-plugin/marketplace.json'))
  market_names = {p['name'] for p in market['plugins']}
  for role, cfg in roles.items():
      plugin = cfg['plugin']
      if plugin not in market_names:
          print(f'MISSING in marketplace: role={role} plugin={plugin}')
      else:
          print(f'OK  role={role} -> plugin={plugin}')
  "
  ```

- [ ] `comm-matrix.csv` 로드 및 shape 확인:
  ```bash
  python -c "
  import sys; sys.path.insert(0, 'src')
  from agent_agora.comm_matrix import load_comm_matrix
  from pathlib import Path
  cm = load_comm_matrix(Path('.agentagora/comm-matrix.csv'))
  assert cm.active
  snap = cm.snapshot()
  print(f'comm-matrix loaded: {len(snap)} to-patterns')
  assert len(snap) == 8, f'expected 8 rows (7 persona + .* catch-all), got {len(snap)}'
  print('shape OK')
  "
  ```

- [ ] `schemas.jsonl` — `delegation_request` 스키마 필수 필드 검증:
  ```bash
  python -c "
  import json
  from pathlib import Path
  schemas = [json.loads(l) for l in Path('.agentagora/schemas.jsonl').read_text('utf-8').splitlines() if l.strip()]
  dr = next((s for s in schemas if s['name'] == 'delegation_request'), None)
  assert dr is not None, 'delegation_request schema missing'
  body = dr['body']
  assert 'from_persona' in body['required']
  assert 'payload' in body['required']
  assert 'context_summary' in body['required']
  print('delegation_request schema OK')
  "
  ```

- [ ] `agora-setup` SKILL.md에 routing bot 기동 안내 포함 확인:
  ```bash
  python -c "
  content = open('plugin/cc-agora-ops/skills/agora-setup/SKILL.md').read()
  checks = ['routing bot', 'delegation_request', 'comm-matrix.csv', 'sp-planner']
  for c in checks:
      assert c in content, f'missing: {c}'
  print('agora-setup SKILL.md contains all required sections')
  "
  ```

- [ ] pytest 전체 실행 (회귀 없음 확인):
  ```bash
  cd "C:/Users/jylee/source/AgentAgora"
  uv run --extra dev python -m pytest tests/ -v --tb=short
  ```
  기대: 모든 기존 테스트 PASSED, 새 실패 없음.

- [ ] 최종 커밋:
  ```bash
  git add .agentagora/ plugin/ examples/
  git commit -m "chore: superpowers 페르소나 분리 통합 검증 완료 (plan 9)"
  ```

---

## Self-Review

spec §5·§9·§11·§12 플랜 9 커버리지 점검:

| 요구사항 | 처리 | 비고 |
|---|---|---|
| `roles.json` 7개 role 추가 | Task 1 | `sp-` 접두사로 기존 role과 충돌 없이 공존 |
| `comm-matrix.csv` §9 워크플로 엣지 인코딩 | Task 2 | weight=1 단일 tier; 런타임 조정은 `POST /admin/comm-matrix`로 |
| `marketplace.json` 7개 등록 확인 | Task 4 | 검증만 — 누락 시 보완 추가 |
| `delegation_request` 스키마 등록 | Task 3 | 플랜 8 중복 방지 — 존재 확인 후 없으면 추가 |
| 스킬 본문 위임 메타 (`delegation-target`, Handoff) | Task 5 a~h | `writing-skills` cross-plugin 참조 끊김 케이스 5-a에서 처리 |
| 라우팅 봇 기동 wiring (`agora-setup`) | Task 6 | Closing 섹션 교체, superpowers 배포 체크리스트 추가 |
| 라우팅 봇 산출물 위치 확인 | Task 7 | 플랜 8 의존 — 봇 미존재 시 명시적 오류 |
| 종단 일관성 검증 | Task 8 | roles × marketplace 교차 확인, comm-matrix shape, pytest |

**플랜 8 의존 사항 (명시적 dependency):**
- Task 7은 플랜 8 라우팅 봇이 완료돼 있어야 실행 가능하다. 봇 배치 경로(`examples/routing_bot/` vs `plugin/superpowers/routing-bot/`)는 플랜 8에서 확정되므로, Task 7의 검증 스크립트는 두 후보를 모두 탐색한다.
- `.agentagora/schemas.jsonl`의 `delegation_request` 스키마는 플랜 8에서 먼저 추가했을 수 있다 — Task 3이 중복 등록 없이 idempotent하게 처리한다.

**comm-matrix 인스턴스 id 패턴 전제:**
- `agora-spawn`이 `<role>-<suffix>` 형식의 인스턴스 id를 생성한다고 가정한다. id 형식이 다르면 `sp-planner-.*` 패턴이 매칭되지 않아 모든 페르소나 간 dispatch가 catch-all(`.*→.*=1`)로 폴백돼 차단 의도가 무력화된다. 실제 spawn 시 인스턴스 id를 확인하고 필요 시 패턴을 수정한다.

**플랜 1–7 전제:**
- `plugin/superpowers/superpowers-*/` 디렉토리들이 존재하고 각 스킬 SKILL.md가 있어야 Task 5가 동작한다. 없으면 해당 플랜을 먼저 실행한다.
