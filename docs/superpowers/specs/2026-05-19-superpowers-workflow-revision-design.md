# superpowers 워크플로 개정 — 설계 (테스터 추가 · 사일런트 모드 · 에이전트 팀)

- 작성일: 2026-05-19
- 상태: 설계 작성 → 유저 검토 대기
- 관련: `plugin/superpowers/*`, `plugin/superpowers/routing-bot/comm-matrix.csv`, `plugin/cc-agora-ops/config/roles.json`, `plugin/.claude-plugin/marketplace.json`, `plugin/superpowers/README.md`

## 1. 배경 / 문제

UeT3DRay 배포 테스트에서 드러난 문제:

- **디버거·리뷰어가 안정적으로 호출되지 않음** — 현재 구현자가 "버그를 못 풀 때"·"리뷰가 필요할 때"를 *자체 판단*으로만 디스패치해, 실제로는 건너뛰어진다.
- **테스터 역할 부재** — 구현자가 `test-driven-development`로 TDD를 직접 수행. 테스트 작성·실행·결과 분석을 전담하는 멤버가 없다.
- **리뷰어 책임 모호** — 현재 리뷰어 책임에 "test coverage"가 포함돼, 테스터 도입 시 테스트 영역과 겹친다.

## 2. 목표 / 비목표

**목표** — 7번째 페르소나 `sp-tester` 추가, 디버거·리뷰어를 흐름에 안정적으로 배선, 리뷰어 책임 재정의(겹침 제거), 멤버별 사일런트/리액티브 모드, 에이전트 팀 분할 규칙. **신규 스킬 작성도 범위에 포함** — 기존 컴포넌트 이전·수정에 한정하지 않고, 새 역할이 요구하는 스킬을 페르소나별로 식별해 새로 작성한다.

**비목표** — planner·router·improver의 핵심 책임 변경. `agora.dispatch`·라우팅 봇 메커니즘 변경. cc-agora(비-superpowers) 페르소나 변경.

## 3. 개정 워크플로

```
planner ─▶ router ─▶ implementer
                        ⇅                TDD 핑퐁 (task마다)
                     tester
                        │ 어려운 실패
                        ▼
                     debugger ─▶ tester (재검증)   |   ─▶ planner (3+ 실패 = 구조 문제)
            (전 task green)
   implementer ─▶ reviewer ─┬─▶ implementer            (코드 레벨 이슈 → 수정 후 재루프)
                            ├─▶ planner                 (구조 문제 → 재기획)
                            └─(승인)▶ implementer ─▶ finishing-a-development-branch
                                                              ─▶ improver ─▶ planner ↻ / 종료
```

TDD 핑퐁 한 사이클(task 단위): 테스터가 실패 테스트 작성·실행(실패 확인) → 구현자가 최소 구현으로 통과 → 테스터가 실행·결과 분석 → green이면 다음 task, red면 분석(단순하면 구현자에게, 어려우면 디버거에게).

## 4. 페르소나 변경

### 4.1 신규 — `sp-tester`

- **미션**: 모든 테스트 코드의 작성·실행·결과 분석을 전담한다. 구현자와 핑퐁하며 TDD 사이클을 구동한다.
- **이전 스킬**: `test-driven-development` — `superpowers-implementer`에서 **이전**한다. "실패하는 테스트를 먼저 쓰고 실패를 직접 확인한다"는 원칙의 주체가 테스터가 된다.
- **신규 스킬**: `analyzing-test-results` — 테스트 실행 결과를 읽고 실패를 분류(실제 버그 / 잘못된 테스트 / 플래키 / 환경 요인)하며, 단순 수정(→ 구현자) vs 원인 추적 필요(→ 디버거)를 판단한다. 테스터의 디버거 라우팅 결정이 이 스킬에 근거한다. 이전받은 `test-driven-development`만으로는 결과 분석·트리아지 역량이 비어 있어 신규 작성한다.
- **수신**: 구현자(테스트 요청·구현 완료 통보), 디버거(수정 후 재검증 요청).
- **발신**: 구현자(실패 테스트 준비 통보·테스트 결과), 디버거(어려운 실패 — 원인 불명/구조적).
- 디버거로 보낼지 판단하는 주체 = 테스터(실패 분석 주체). 이로써 디버거가 확실히 호출된다.

### 4.2 `implementer`

- `test-driven-development` 소유 **제거** — 테스터로 이전. 구현자는 **구현 코드만** 작성한다.
- 유지 스킬: `executing-plans`, `using-git-worktrees`, `finishing-a-development-branch`.
- task마다 테스터와 핑퐁. 전 task green이면 리뷰어로 디스패치.
- 핸드오프 엣지 개정: 더 이상 디버거로 직접 보내지 않는다(테스터 경유). `→ reviewer`(리뷰 요청), `→ improver`(리뷰 승인 + `finishing-a-development-branch` 완료 후).

### 4.3 `reviewer` (재정의)

- **테스터 = "동작하나?"(실행·경험적) / 리뷰어 = "잘 만들었나?"(판독)**. 겹침 0.
- 미션: 코드를 *읽고* 판단한다 — 정확성(추론), 가독성, 유지보수성, **코드 구조/아키텍처**. 테스트 결과는 입력 컨텍스트로만 참고하며, 커버리지 분석은 하지 않는다(테스터 영역).
- 소유 스킬: `requesting-code-review`, `receiving-code-review` (불변).
- 출력 분기:
  - **코드 레벨 이슈**(국소 수정 가능) → 구현자 (`type=reply`, Critical/Important/Minor + file:line).
  - **구조/아키텍처 문제**(국소 수정 불가) → 플래너 (`type=task`, 구조 문제 요약). **신규 엣지.**
  - **승인** → 구현자 (`type=reply`). 구현자가 `finishing-a-development-branch` 진행.

### 4.4 `debugger`

- **수신**: 테스터(어려운 실패). **복귀**: 수정·검증 후 **테스터**로(`type=reply`) — 테스터가 전체 테스트를 재검증하고 루프를 잇는다.
- "3+ 수정 실패 = 구조 문제" 발견 시 → **플래너**로 에스컬레이션(`type=task`). 기존 "구현자에게 redesign flag" 규칙을 플래너 직행으로 변경(리뷰어의 구조 에스컬레이션과 동일 경로).

### 4.5 `planner`

- 진입점 확장: 기존 "유저 아이디어 / improver findings"에 더해 **reviewer·debugger의 구조 에스컬레이션**도 진입 트리거. 구조 에스컬레이션 수신 시 brainstorming의 "아이디어"로 취급해 새 사이클을 연다.
- 또한 플래너는 라우터에 플랜을 넘긴 뒤에도 스펙에 미계획 범위가 남으면 순서대로 다음 슬라이스의 플랜을 작성·디스패치한다(파이프라인 플래닝) — 다운스트림 워커가 쉬지 않게 한다.

router·improver는 책임 변경 없음(§6·§7의 공통 규칙은 적용).

## 5. comm-matrix (8×8)

`sp-tester` 열/행 추가 + 신규 엣지. `plugin/superpowers/routing-bot/comm-matrix.csv`:

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

행 = 수신자, 열 = 발신자. 신규 엣지: implementer⇄tester, tester→debugger, debugger→tester, debugger→planner, reviewer→planner. (reviewer→implementer·implementer→reviewer·implementer→improver·improver→planner·planner→router·router→implementer는 유지.)

## 6. 사일런트 / 리액티브 모드

모든 페르소나(7종)에 적용하는 멤버별 응답 모드.

- **설정 파일**: `<배포 루트>/.superpower/response.json`. 배포 루트 = 워커 디렉터리의 부모. 워커는 cwd의 부모에서 이 파일을 읽는다.
- **포맷**: `{ "<instance-id>": "silent" | "reactive", ... }` — 멤버 instance-id를 키로 한다.
- **기본값**: 파일이 없거나 자기 instance-id 키가 없으면 → `silent`.
- **`silent`** — `AskUserQuestion`을 사용하지 않는다. 사용자 입력 없이 진행하고, 결정 분기는 추천 선택지로 자동 선택한다.
- **`reactive`** — `AskUserQuestion`을 적극 사용해 사용자에게 묻는다.
- **사용자 게이트 귀결**: silent 모드는 페르소나의 사용자 게이트를 덮어쓴다 — planner의 spec 승인·plan 확정 게이트, improver의 "검토할까요?" 게이트가 silent에선 추천 선택지로 자동 결정된다. 기본(silent)에선 전 워크플로가 사람 개입 0으로 자율 실행되고, 특정 멤버를 `reactive`로 올려야 그 멤버에서 사용자에게 묻는다. 페르소나 SKILL.md의 "never skip the user gate" 문구는 "reactive면 게이트, silent면 자동결정"으로 개정한다.
- **구현**: 각 페르소나 SKILL.md에 "Response mode" 섹션을 추가 — 기동 시 워커가 `Read`로 파일을 확인하고 그 모드로 동작한다. 페르소나 프롬프트 레벨 처리이며 서버/CLI 코드 변경은 없다.

## 7. 에이전트 팀 분할

모든 페르소나에 적용하는 공통 규칙:

- 환경변수 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` 값이 `1`이고, 맡은 임무가 병렬 분해 가능하면 → 에이전트 팀으로 분할해 실행한다.
- `1`이 아니면 단일 에이전트로 진행한다.
- 각 페르소나 SKILL.md에 규칙을 추가한다. router는 이미 `dispatching-parallel-agents`를 보유하므로, 이 규칙은 그 전제(env 게이트)를 명문화하고 전 페르소나로 확장하는 것이다.

## 8. 파일 영향

| 파일 | 변경 |
|---|---|
| `plugin/superpowers/superpowers-tester/` | **신규** 플러그인 — `.claude-plugin/plugin.json`, `README.md`, `skills/persona/SKILL.md` |
| `plugin/superpowers/superpowers-implementer/skills/test-driven-development/` | `superpowers-tester/skills/`로 **이전** |
| `plugin/superpowers/superpowers-tester/skills/analyzing-test-results/` | **신규** 스킬 — 테스트 결과 분석·실패 분류·디버거 에스컬레이션 판단 |
| `plugin/superpowers/superpowers-implementer/skills/persona/SKILL.md` | TDD 소유 제거, 핸드오프 개정(⇄tester, →reviewer) |
| `plugin/superpowers/superpowers-reviewer/skills/persona/SKILL.md` | 책임 재정의, →planner 엣지 추가 |
| `plugin/superpowers/superpowers-debugger/skills/persona/SKILL.md` | 수신·복귀를 tester로, 구조 문제 →planner |
| `plugin/superpowers/superpowers-planner/skills/persona/SKILL.md` | reviewer·debugger 구조 에스컬레이션 진입점 추가 |
| 7개 페르소나 `skills/persona/SKILL.md` 전부 | §6 "Response mode" 섹션 + §7 에이전트 팀 규칙 추가 |
| `plugin/superpowers/routing-bot/comm-matrix.csv` | 8×8 재작성 (§5) |
| `plugin/cc-agora-ops/config/roles.json` | `"sp-tester": { "plugin": "superpowers-tester" }` 추가 |
| `plugin/.claude-plugin/marketplace.json` | `superpowers-tester` 등록 |
| `plugin/superpowers/README.md` | 워크플로 다이어그램·구성 표 갱신 |

## 9. 배포 마이그레이션 (UeT3DRay)

레포 변경 후 배포 측 후속 작업(별도):

- `sp-tester-1` 워커 spawn (`sp-tester` role).
- `.agentagora/comm-matrix.csv`를 §5의 8×8로 교체.
- `run-agora.ps1` — 테스터 워커 패널 추가, 모델/effort 배정.
- `<배포 루트>/.superpower/response.json` 생성 (기본 전 멤버 silent — 필요 멤버만 reactive).

## 10. 검증 / 테스트

- comm-matrix — 신규 엣지(implementer⇄tester, tester→debugger, debugger→tester, debugger→planner, reviewer→planner) 허용 확인; `sp-tester-1`이 `sp-tester-.*` 패턴에 fullmatch; 8×8 로드 무오류.
- 각 페르소나 플러그인 — `superpowers-tester` 포함 7종이 마켓플레이스에서 로드되고 `persona` 스킬이 보임.
- `test-driven-development` 스킬이 `superpowers-tester`에서 발견되고 `superpowers-implementer`에는 없음.
- `roles.json` — `sp-tester` → `superpowers-tester` 매핑.
- Response mode — `.superpower/response.json` 부재 시 silent, 항목 존재 시 해당 모드로 동작(페르소나 프롬프트 레벨이므로 워커 기동 테스트로 확인).

## 11. 미해결

없음 — 범위·결정이 모두 확정됐다.
