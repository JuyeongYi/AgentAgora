# superpowers를 AgentAgora 페르소나로 분리 — 설계

- 작성일: 2026-05-18
- 상태: 설계 작성 → 유저 검토 대기
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
- AgentAgora `dispatcher`·메시지 라우팅 시맨틱 변경.

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

`plugin/superpowers/<persona>/` — AgentAgora `plugin/personas/` 패턴을 따른다.

```
plugin/superpowers/
  superpowers-base/        .claude-plugin/plugin.json + skills/{using-superpowers,verification-before-completion,writing-skills}/
  superpowers-planner/     .claude-plugin/plugin.json + skills/{persona,brainstorming,writing-plans}/ + tests/
  superpowers-implementer/ .claude-plugin/plugin.json + skills/{persona,...}/ + tests/
  superpowers-debugger/    ...
  superpowers-reviewer/    ...
  superpowers-router/      ...
  superpowers-improver/    .claude-plugin/plugin.json + skills/{persona,improvement-review}/ + tests/
```

각 페르소나 플러그인 구성:

- `.claude-plugin/plugin.json` — 이름·버전·`dependencies: ["superpowers-base"]`.
- `skills/persona/SKILL.md` — 페르소나 역할 정의(AgentAgora `plugin/personas/` 패턴). 워크플로상 위치, 위임 대상, 운용 규칙. (`superpowers-base`는 라이브러리이므로 persona 스킬 없음.)
- 보유 스킬들 — 원본 superpowers에서 잘라붙임.
- `tests/` — 해당 스킬의 테스트(§8).

7개 플러그인을 `plugin/.claude-plugin/marketplace.json`에 등록한다.

## 5. 위임 — 브로커 · 라우팅 봇 · comm-matrix

페르소나는 AgentAgora 워커로 등록된다(`X-Agora-*` 헤더 자동 등록). 단계 간 핸드오프:

- **스킬 내 subagent 디스패치 지점 → `agora.dispatch`.** 원본 스킬은 Task 도구로 subagent를 디스패치한다(예: `subagent-driven-development`의 "implementer subagent 디스패치", `requesting-code-review`의 "code reviewer subagent 디스패치"). 페르소나 모델에서 이 지점은 대상 페르소나-워커로의 `agora.dispatch`가 된다.
- **라우팅 봇** — AgentAgora handler 봇(`agora.register_bot`). `delegation_request` 스키마를 구독한다. 페르소나가 다른 역할을 필요로 할 때 이 스키마로 메시지를 emit하면, 봇이 대상 페르소나를 골라 `agora.dispatch`한다(AgentAgora schema-routed dispatch 모델). 대상이 명확한 핸드오프는 페르소나가 직접 `agora.dispatch`해도 된다.
- **comm-matrix** — 페르소나 간 위임 ACL. AgentAgora 기존 `comm-matrix.csv` 메커니즘으로 표현한다. §9 워크플로의 엣지가 곧 매트릭스의 허용 셀이다.
- 각 스킬에 **위임 대상 메타**를 추가한다 — 스킬이 다음 단계로 넘어갈 때 어느 페르소나로 가는지 명시.

## 6. 병렬처리 체크포인트

planner → 실행 핸드오프 지점에 배치한다. `writing-plans` 완료 후 "이 플랜의 task들이 독립적이라 병렬 실행 가능한가?"를 확인한다:

- 병렬 가능 → router가 `dispatching-parallel-agents` 경로.
- 순차(상호 의존) → router가 `subagent-driven-development` 경로.

이 판단은 router 페르소나가 수행하며, planner의 핸드오프를 받은 직후의 분기점이다.

## 7. 자가 개선 루프 (ouroboros)

`ouroboros-loops` 플러그인을 설계 참고로 한다. ouroboros 철학 — *"됐지만 더 좋아질 수 있으니 다시"*(성공 후에도 계속 개선) — 를 워크플로에 닫힌 루프로 들인다.

`superpowers-improver` 페르소나, 스킬 `improvement-review`:

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

## 10. 파일 영향 / 산출물

| 경로 | 변경 |
|---|---|
| `plugin/superpowers/superpowers-base/` | 신규 — 공통 스킬 3종 + plugin.json |
| `plugin/superpowers/superpowers-{planner,implementer,debugger,reviewer,router,improver}/` | 신규 — 페르소나 플러그인 6종 (plugin.json + persona 스킬 + 보유 스킬 + tests) |
| `plugin/superpowers/superpowers-improver/skills/improvement-review/` | 신규 — 자가 개선 스킬 |
| `plugin/.claude-plugin/marketplace.json` | 7개 플러그인 등록 |
| comm-matrix (`comm-matrix.csv`) | 페르소나 간 위임 ACL |
| 라우팅 봇 | `delegation_request` 스키마 + handler 봇 |

원본 superpowers 스킬은 잘라붙이되 위임 메타를 추가한다. `model`/`effort` frontmatter는 보존한다.

## 11. 구현·테스트 순서

규모가 크므로 단계 분해한다:

1. `superpowers-base` + 페르소나 플러그인 6종 스캐폴딩 — 원본 스킬 잘라붙이기, `plugin.json`·persona 스킬·`marketplace.json` 등록. `claude -p` 제거.
2. 위임 배선 — 스킬 내 디스패치 지점을 `agora.dispatch`로, 위임 대상 메타 추가, `comm-matrix.csv` 작성.
3. 라우팅 봇 — `delegation_request` 스키마 + handler 봇 구현.
4. improver 페르소나 + `improvement-review` 스킬 + 유저 게이트 + planner 루프백.
5. 병렬처리 체크포인트 배선.
6. 테스트 재설계(`claude -p` 없이) — 페르소나별 분배.

각 단계는 독립 검증 가능하다.

## 12. 미해결 / 후속

- `claude -p` 없는 테스트 방식의 구체안 — 구현 플랜 6단계에서 확정.
- `comm-matrix.csv`의 정확한 셀 값(위임 weight) — §9 워크플로 엣지를 기준으로 구현 시 확정.
- `improvement-review` 스킬 본문 — `ouroboros-loops`의 `research`/`analyze`/`enhance` SKILL.md를 참고해 구현 4단계에서 작성.
- 페르소나-워커의 spawn·기동 — AgentAgora 기존 `agora-spawn`(cc-agora-ops)을 그대로 쓴다. 본 설계 범위 밖.
