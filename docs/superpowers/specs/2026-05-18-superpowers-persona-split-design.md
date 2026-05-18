# superpowers를 AgentAgora 페르소나로 분리 — 설계

- 작성일: 2026-05-18
- 상태: 설계 보강(컴포넌트·CLI/MCP 점검 반영) → 유저 검토 대기
- 참고: `superpowers_model_specified`(원본 플러그인 v5.1.0), `ouroboros-loops`(자가개선 루프 — `docs/superpowers-ouroboros-mapping.md` 포함)

## 1. 배경 / 문제

superpowers 플러그인은 14개 스킬을 담은 단일 플러그인이다 — brainstorming·writing-plans·test-driven-development·systematic-debugging·코드 리뷰·subagent 디스패치 등 개발 워크플로 전반의 스킬 라이브러리. 모든 스킬이 한 플러그인에 있고, 한 Claude 인스턴스가 전 단계를 수행한다.

AgentAgora는 다중 에이전트 메시지 라우팅 브로커다 — 워커(Claude Code 인스턴스)들이 서로 task를 dispatch한다. superpowers의 워크플로 단계들을 **개별 페르소나-워커**로 분리하면, 각 단계가 전용 컨텍스트·전용 모델로 돌고, 단계 간 핸드오프가 브로커를 통한 명시적 위임이 된다.

## 2. 목표 / 비목표

**목표**

- superpowers 14개 스킬을 워크플로 단계별 페르소나 플러그인으로 분리, `plugin/superpowers/`에 배치한다.
- 각 페르소나는 AgentAgora 워커. 단계 간 핸드오프 = comm-matrix로 게이팅되는 `agora.dispatch`.
- 자가 개선 루프 — 구현 완료 후 개선 기회를 검토해 워크플로를 순환시킨다(ouroboros).

**비목표**

- superpowers 스킬 *내용*의 재작성. 스킬 본문은 원본을 잘라붙이고 위임 메타만 추가한다.
- `claude -p` 기반 실행. 별도 요금체계를 쓰므로 전면 제거한다.
- AgentAgora `dispatcher`·메시지 라우팅 시맨틱 변경. 신규 MCP 도구·CLI 명령 추가(§10).

## 3. 페르소나 집합 & 스킬 분배

원본 14개 스킬을 워크플로 단계로 묶는다.

| 페르소나 플러그인 | 보유 스킬 (원본 superpowers) |
|---|---|
| `superpowers-base` | using-superpowers, verification-before-completion, writing-skills |
| `superpowers-planner` | brainstorming, writing-plans |
| `superpowers-implementer` | test-driven-development, executing-plans, using-git-worktrees, finishing-a-development-branch |
| `superpowers-debugger` | systematic-debugging |
| `superpowers-reviewer` | requesting-code-review, receiving-code-review |
| `superpowers-router` | subagent-driven-development, dispatching-parallel-agents |
| `superpowers-improver` | improvement-review (신규 — §7) |

`superpowers-base`의 3개 스킬은 워크플로 단계에 안 묶이는 공통 스킬 — 모든 페르소나 플러그인이 `dependencies`로 의존한다. 원본 스킬의 `model`/`effort` frontmatter는 그대로 보존한다(페르소나-워커가 스킬에 맞는 모델로 돌 수 있도록).

## 4. 플러그인 레이아웃

`plugin/superpowers/<persona>/` — AgentAgora `plugin/personas/` 패턴(`.claude-plugin/plugin.json` + `skills/persona/SKILL.md` + `README.md`)을 따른다.

```
plugin/superpowers/
  superpowers-base/        .claude-plugin/plugin.json + README.md + hooks/ + skills/{using-superpowers,verification-before-completion,writing-skills}/
  superpowers-planner/     .claude-plugin/plugin.json + README.md + skills/{persona,brainstorming,writing-plans}/ + tests/
  superpowers-implementer/ .claude-plugin/plugin.json + README.md + skills/{persona,test-driven-development,executing-plans,using-git-worktrees,finishing-a-development-branch}/ + tests/
  superpowers-debugger/    .claude-plugin/plugin.json + README.md + skills/{persona,systematic-debugging}/ + tests/
  superpowers-reviewer/    .claude-plugin/plugin.json + README.md + skills/{persona,requesting-code-review,receiving-code-review}/ + tests/
  superpowers-router/      .claude-plugin/plugin.json + README.md + skills/{persona,subagent-driven-development,dispatching-parallel-agents}/ + tests/
  superpowers-improver/    .claude-plugin/plugin.json + README.md + skills/{persona,improvement-review}/ + tests/
```

각 페르소나 플러그인 구성:

- `.claude-plugin/plugin.json` — 이름·버전·`dependencies: ["superpowers-base"]`.
- `README.md` — 플러그인 한 줄 설명 + 페르소나 역할 (AgentAgora 플러그인 관행 — `plugin/personas/*`에 모두 존재).
- `skills/persona/SKILL.md` — 페르소나 정의. AgentAgora persona 스킬 관행을 따른다: mission, 워크플로상 위치, 위임 대상, 그리고 AgentAgora 운용 규약(forward·flush entry·cc message·payload 규약). 단순 역할 설명이 아니라 `plugin/personas/*/skills/persona/`와 같은 형식.
- 보유 스킬들 — 원본 superpowers에서 **디렉토리째** 잘라붙인다. supporting 파일(brainstorming의 visual-companion Node 서버 `scripts/*`, systematic-debugging의 보조 문서 10종, subagent-driven-development의 prompt 템플릿 3종, writing-skills 보조 문서 등)이 함께 따라온다.
- `tests/` — 해당 스킬의 테스트(§8).

`superpowers-base`는 추가로 **`hooks/`**를 가진다 — 원본 superpowers의 SessionStart 훅(`hooks.json` + `run-hook.cmd` + `session-start`)을 이식한 것. 이 훅이 매 세션 시작 시 `using-superpowers` SKILL.md를 컨텍스트에 주입한다. `session-start` 스크립트 내부의 SKILL.md 경로를 새 레이아웃(`${CLAUDE_PLUGIN_ROOT}/skills/using-superpowers/SKILL.md`)에 맞게 조정한다. (`superpowers-base`는 라이브러리이므로 persona 스킬은 없다.)

7개 플러그인을 `plugin/.claude-plugin/marketplace.json`에 등록한다.

## 5. 위임 — 브로커 · 라우팅 봇 · comm-matrix

페르소나는 AgentAgora 워커로 등록된다(`X-Agora-*` 헤더 자동 등록). 단계 간 핸드오프:

- **스킬 내 subagent 디스패치 지점 → `agora.dispatch`.** 원본 스킬은 Task 도구로 subagent를 디스패치한다(예: `subagent-driven-development`의 "implementer subagent 디스패치", `requesting-code-review`의 "code reviewer subagent 디스패치"). 페르소나 모델에서 이 지점은 대상 페르소나-워커로의 `agora.dispatch`가 된다.
- **`delegation_request` 스키마** — 위임 메시지 스키마. `.agentagora/schemas.jsonl`에 등록한다. 필드: `from_persona`·`to_persona`(또는 역할 `to_capability`)·`payload`·`context_summary`.
- **라우팅 봇** — 새 `AgoraBot` 서브클래스 스크립트다(`examples/echo_bot` 패턴 — `agent_agora.bot`의 `AgoraBot`을 상속, `handle()`만 구현, 별도 프로세스로 기동). `delegation_request` 스키마를 구독하는 handler 봇으로, 페르소나가 다른 역할이 필요할 때 이 스키마로 emit하면 봇이 대상 페르소나를 골라 `agora.dispatch`한다(AgentAgora schema-routed dispatch 모델). 대상이 명확한 핸드오프는 페르소나가 직접 `agora.dispatch`해도 된다.
- **comm-matrix** — 페르소나 간 위임 ACL. AgentAgora 기존 `comm-matrix.csv` 메커니즘으로 표현한다(§9 워크플로의 엣지가 곧 매트릭스의 허용 셀; 정규식 헤더 — `comm-matrix-file-policy-regex` 설계).
- **`cc-agora-ops/config/roles.json`** — `agora-spawn`이 role→플러그인을 해석하는 매핑. 7개 페르소나 role 항목을 추가한다(`planner`→`superpowers-planner` 등).
- **스킬 본문 위임 메타** — 각 스킬에 다음 단계 위임 대상 페르소나를 명시한다. 원본 스킬의 `superpowers:<skill>` cross-reference는 스킬이 플러그인별로 흩어지면서 cross-plugin 참조가 된다 — 워커에 두 플러그인이 함께 활성화돼 있으면 이름으로 resolve되어 대부분 무해하나, `writing-skills`(base) → `superpowers:test-driven-development`(implementer)처럼 끊길 수 있는 케이스는 통합 플랜의 위임 배선에서 처리한다.

## 6. 병렬처리 체크포인트

planner → 실행 핸드오프 지점에 배치한다. `writing-plans` 완료 후 "이 플랜의 task들이 독립적이라 병렬 실행 가능한가?"를 확인한다:

- 병렬 가능 → router가 `dispatching-parallel-agents` 경로.
- 순차(상호 의존) → router가 `subagent-driven-development` 경로.

이 판단은 router 페르소나가 수행하며, planner의 핸드오프를 받은 직후의 분기점이다. router의 `skills/persona/SKILL.md`에 이 체크포인트 로직을 명시한다.

## 7. 자가 개선 루프 (ouroboros)

`ouroboros-loops` 플러그인을 설계 참고로 한다. ouroboros 철학 — *"됐지만 더 좋아질 수 있으니 다시"*(성공 후에도 계속 개선) — 를 워크플로에 닫힌 루프로 들인다.

`superpowers-improver` 페르소나, 스킬 `improvement-review`(원본에 없는 신규 스킬 — 작성 필요):

- **트리거**: implementer의 `finishing-a-development-branch` 완료 후.
- **유저 게이트**: 유저에게 "구현 결과를 검토해 개선·리팩토링·추가 아이디어를 찾을까요?"를 묻는다. 거부 시 워크플로 종료.
- **검토**: 승인 시 빌드된 결과물을 검토해 (a) 기능 개선, (b) 리팩토링, (c) 추가 기능 아이디어를 findings로 정리한다. ouroboros의 `research→analyze→enhance-식별` 패턴을 압축 적용.
- **핸드오프**: findings를 `superpowers-planner`로 `agora.dispatch`. planner가 이를 새 플랜으로 전환 → 워크플로 재순환.

이 improver→planner 엣지가 워크플로를 자기 순환(ouroboros) 루프로 닫는다.

## 8. `claude -p` 제거 & 테스트

원본 superpowers의 `claude -p`(헤드리스 Claude) 호출은 ~32곳 전부 `tests/`의 테스트 하네스다 — 런타임 워크플로에는 `claude -p`가 없다(전수 조사 결과). `claude -p`는 별도 요금체계를 쓰므로 전면 제거한다.

- 워커에 플러그인을 주입하는 경우는 `settings.local.json`(`extraKnownMarketplaces`·`enabledPlugins`)으로 처리한다 — AgentAgora `agora-spawn` 방식.
- 각 스킬의 테스트는 해당 페르소나 플러그인의 `tests/`로 분배한다. `claude -p` 의존을 제거하고 테스트 방식을 재설계한다. `--max-turns` 등 `claude -p` 전용 개념은 제외한다.

## 9. 워크플로 전체

```
planner (brainstorming → writing-plans)
   │
   ▼  [병렬처리 체크포인트 — §6]
router (subagent-driven-development | dispatching-parallel-agents)
   │
   ▼
implementer (test-driven-development → executing-plans)
   ├──▶ debugger (systematic-debugging)               ← 버그 발생 시
   └──▶ reviewer (requesting / receiving-code-review)  ← 리뷰 시
   │
   ▼
implementer (finishing-a-development-branch)
   │
   ▼  [유저 게이트 — §7]
improver (improvement-review)
   │
   └──▶ planner ↻  (개선 있으면 재순환)  /  종료 (개선 없거나 유저 거부)
```

각 엣지 = comm-matrix로 게이팅되는 `agora.dispatch`(필요 시 라우팅 봇 경유). `superpowers-base`의 공통 스킬은 모든 페르소나가 보유한다.

## 10. CLI · MCP 영향

신규 MCP 도구·CLI 명령은 **필요 없다.** 이 설계는 AgentAgora의 기존 표면으로 충족된다:

- 위임 = 기존 `agora.dispatch`. 워커 등록 = `X-Agora-*` 자동 등록. 라우팅 봇 = `agora.register_bot` + `agora.bot_emit`. `delegation_request` 스키마 = `agora.register_schema`(또는 `schemas.jsonl` 로드). 인박스 드레인 = `agora.flush`. — 모두 현존 도구(`agora.*` 21종).
- 라우팅 봇은 새 *아티팩트*이지 새 CLI/MCP 프리미티브가 아니다 — `examples/echo_bot`처럼 `AgoraBot` 스크립트 + 런처(`run-*.bat`/`.sh`). 선택적으로 `pyproject.toml [project.scripts]`에 편의 엔트리(예: `agora-routing-bot`)를 둘 수 있으나 필수는 아니다.
- 라우팅 봇은 서버·워커와 별개 프로세스다 — 배포 시 함께 기동해야 한다. `agora-setup` 흐름에 라우팅 봇 기동을 더하는 것은 통합 플랜에서 다룬다.

## 11. 파일 영향 / 산출물

| 경로 | 변경 |
|---|---|
| `plugin/superpowers/superpowers-base/` | 신규 — plugin.json·README·`hooks/`(session-start 이식)·공통 스킬 3종 |
| `plugin/superpowers/superpowers-{planner,implementer,debugger,reviewer,router,improver}/` | 신규 — 페르소나 플러그인 6종 (plugin.json·README·persona 스킬·보유 스킬·tests) |
| `plugin/superpowers/superpowers-improver/skills/improvement-review/` | 신규 — 자가 개선 스킬(원본에 없음, 작성) |
| `plugin/.claude-plugin/marketplace.json` | 7개 플러그인 등록 |
| `plugin/cc-agora-ops/config/roles.json` | 7개 페르소나 role 매핑 추가 |
| `.agentagora/schemas.jsonl` | `delegation_request` 스키마 |
| `comm-matrix.csv` | 페르소나 간 위임 ACL |
| 라우팅 봇 | 신규 `AgoraBot` 스크립트 + 런처 (위치는 통합 플랜에서 확정 — `plugin/superpowers/` 또는 `examples/` 하위 후보) |

원본 superpowers 스킬은 디렉토리째 잘라붙이되 위임 메타를 추가한다. `model`/`effort` frontmatter는 보존한다.

## 12. 구현 플랜 분해

규모가 크므로 **플러그인 7 + 라우팅 봇 1 + 통합 1**, 총 9개 플랜으로 분해한다.

**플러그인별 플랜 7개** — 각 플랜이 한 플러그인을 완성한다(plugin.json·README·persona 스킬·스킬 복사·tests·marketplace 자기 항목 등록):

1. `superpowers-base` — + `hooks/`(session-start) 이식·경로 조정.
2. `superpowers-planner` — brainstorming·writing-plans (visual-companion 서버 포함).
3. `superpowers-implementer` — test-driven-development·executing-plans·using-git-worktrees·finishing-a-development-branch.
4. `superpowers-debugger` — systematic-debugging.
5. `superpowers-reviewer` — requesting-code-review·receiving-code-review.
6. `superpowers-router` — subagent-driven-development·dispatching-parallel-agents + persona 스킬에 병렬 체크포인트(§6).
7. `superpowers-improver` — `improvement-review` 스킬 신규 작성(§7).

**라우팅 봇 플랜 1개** — 신규 코드이므로 독립 플랜:

8. 라우팅 봇 — `delegation_request` 스키마 정의, `AgoraBot` 서브클래스 구현(`delegation_request` 구독 → `agora.find`로 대상 페르소나 워커 resolve → `agora.dispatch`), 런처 스크립트(`run-*.bat`/`.sh`), 봇 단위 테스트. 배치 위치 확정.

**통합 플랜 1개** — 1~8이 존재한 뒤 실행:

9. 통합 — `comm-matrix.csv` 작성, `cc-agora-ops/config/roles.json`에 7개 역할 추가, `marketplace.json` 7개 등록 확인, 스킬 본문 위임 메타·cross-plugin 참조 배선, 라우팅 봇 기동 wiring(`agora-setup` 흐름).

플러그인별 플랜 1~7은 서로 독립이다(어느 순서로도 가능, base를 먼저 두면 의존 검증이 쉽다). 라우팅 봇 플랜 8은 `delegation_request` 스키마만 정해지면 독립 구현 가능. 통합 플랜 9는 1~8에 의존한다. 각 플랜은 자체 검증 가능하다 — 플러그인 플랜은 marketplace 검증, 봇 플랜은 봇 단위 테스트, 통합 플랜은 위임 동작 검증.

## 13. 미해결 / 후속

- `claude -p` 없는 테스트 방식의 구체안 — 각 플러그인 플랜의 `tests/` 작성 시 확정.
- `comm-matrix.csv`의 정확한 셀 값(위임 weight) — §9 워크플로 엣지를 기준으로 통합 플랜에서 확정.
- `improvement-review` 스킬 본문 — `ouroboros-loops`(`C:/Users/jylee/.claudemanager/marketplace/jylee_claude_marketplace/ouroboros-loops`)의 `research`/`analyze`/`enhance` SKILL.md를 참고해 플랜 7에서 작성.
- 라우팅 봇의 배치 위치(`plugin/superpowers/` vs `examples/` 등) — 플랜 8(라우팅 봇)에서 확정.
- 페르소나-워커의 spawn·기동 — AgentAgora 기존 `agora-spawn`(cc-agora-ops) + `roles.json` 매핑을 쓴다.
