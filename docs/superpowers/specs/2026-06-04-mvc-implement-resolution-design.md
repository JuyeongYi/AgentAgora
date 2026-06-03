# MVC implement 노드 해소 (라우터 해소 + controller 리드) 설계

**상태**: 설계 (2026-06-04, 브랜치 feat/mvc-implement-resolution)
**토픽**: MVC 토폴로지(model·view·controller)에서 워크플로의 추상 "implement 노드"(=implementer 자리)를 라우터가 레이어로 해소하고, controller를 브랜치 리드 겸 단일 face로 고정해 나머지 council의 "→ implementer" 엣지를 일관되게 잇는다.

## 배경 / 문제

`agora-spawn-impl` 스킬의 의도는 **택일**이다 — implement 슬롯을 *단일 implementer 1명* 또는 *MVC 3종(model·view·controller)* 중 하나로 채운다(공존 아님). 그런데 MVC 커밋(`2cfe1e1`)이 페르소나·`roles.json`·`marketplace.json`만 추가하고 주변을 맞추지 않아, implement 노드가 **절반만 교체**된 상태다:

1. **comm-matrix에 MVC가 없음(배선 버그).** 배포되는 `routing-bot/comm-matrix.csv`는 `sp-planner·sp-router·sp-implementer·sp-tester·sp-debugger·sp-reviewer·sp-improver` + operator catch-all 8열뿐이다. ACL은 allow-list라, MVC를 고르면 워커는 떠도 router→model, model⇄tester, controller→reviewer 등 **직접 `agora.dispatch`가 전부 거부**된다. (라우팅봇 `agora.bot_emit` 경로만 ACL을 우회하지만, 페르소나 간 직접 dispatch는 ACL을 탄다.)
2. **복귀 엣지가 "→ implementer"로 하드네이밍.** tester(실패 라우팅)·reviewer(코드이슈)·improver(loop-back)가 문자열로 `implementer`를 가리킨다. MVC 팀에선 `agora.find("implementer")`가 실체가 없다.
3. **브랜치/워크트리 주인 분산.** model·view·controller가 각자 worktree에서 `finishing-a-development-branch`를 선언해, 한 기능에 브랜치 마무리가 셋으로 쪼개지고 단일 리드가 없다.

## 목표 / 비목표

**목표**
- MVC 모드에서 implement 노드를 **라우터가 레이어 소유자로 해소**(file footprint 기준)하도록 router 페르소나에 분기 추가.
- **controller = 브랜치 리드 겸 단일 face**: 통합·`finishing-a-development-branch`·review/improver 핸드오프를 controller가 단독 수행. model/view는 controller에 보고하는 sub-implementer.
- comm-matrix에 model·view·controller 엣지 신설 → MVC 토폴로지가 ACL상 실제로 동작.
- 나머지 council의 "→ implementer" 엣지는 **그대로 두고**, MVC 팀에선 controller로 해소됨을 페르소나에 명시.

**비목표 (YAGNI)**
- 단일 implementer 토폴로지 변경(그대로 유지 — MVC 미스폰 시 implementer 행/열은 비활성으로 남음).
- reviewer가 세 레이어 워커를 각각 리뷰하는 방식(엣지·왕복 증가 → controller 단일 face로 회피).
- 라우팅봇 코드 변경(role 기반 `agora.find`는 model/view/controller도 이미 resolve 가능 — 등록만 되면 됨).
- 레이어별 worktree 자동 병합 도구. controller가 통합 책임을 지되, 통합 메커니즘(서브브랜치 머지 vs 패치 핸드오프)은 controller 판단에 맡긴다.

## 핵심 결정

1. **라우터가 추상 implement 노드를 해소.** router는 planner 플랜의 병렬 체크포인트 후, 팀에 MVC가 있으면 각 task를 **소유 레이어**(data/persistence/도메인규칙→model, presentation/템플릿/CSS→view, route/요청처리/상태/조율→controller)로 dispatch한다. 단일 팀이면 기존대로 implementer 1명에게.
2. **controller = 리드/face/브랜치 소유자.** all-green→reviewer, reviewer 코드이슈, 승인→`finishing-a-development-branch`→improver는 controller가 단독으로 수행/수신한다. model/view는 자기 레이어 작업을 끝내면 controller에 보고하고, controller가 통합 후 리뷰·마무리를 주도한다.
3. **tester만 레이어 워커 각각과 per-task TDD 핑퐁.** tester는 발신자에게 reply하므로 role 해소가 불필요하다. model/view/controller 각자가 자기 task에 대해 tester와 핑퐁한다.

## 구조 / 위치

| 파일 | 변경 |
|------|------|
| `plugin/superpowers/routing-bot/comm-matrix.csv` | 8×8 → 11×11. model·view·controller 행·열 신설 + 엣지(아래 §comm-matrix). |
| `plugin/superpowers/superpowers-router/skills/persona/SKILL.md` | MVC 분기: 팀에 MVC 있으면 task를 레이어 소유자로 dispatch(아니면 implementer). |
| `plugin/superpowers/superpowers-controller/skills/persona/SKILL.md` | 리드/브랜치 소유자/단일 face 명시: model/view 위임·완료 수합·통합·review/finishing/improver 단독 주도. |
| `plugin/superpowers/superpowers-model/skills/persona/SKILL.md` | 독립 브랜치 생애주기 엣지(→reviewer/finishing/→improver) 제거 → "완료를 controller에 보고; 브랜치는 controller 소유". tester 핑퐁·크로스레이어 유지. |
| `plugin/superpowers/superpowers-view/skills/persona/SKILL.md` | model과 동일 편집(레이어만 presentation). |
| `superpowers-reviewer`·`superpowers-improver`·`superpowers-tester` persona | "MVC 팀에선 'implementer' = controller(리드)" 한 줄 주석. |
| `plugin/superpowers/README.md` | §워크플로에 "implement 노드 = {implementer | MVC, 리드=controller}" 주석. |
| `plugin/cc-agora-ops/skills/agora-spawn-impl/SKILL.md` | MVC 결과에 "controller = 브랜치 리드/단일 face" 명시. |
| `tests/test_superpowers_comm_matrix.py` | MVC 엣지 케이스(router→layer, layer⇄tester, controller→reviewer/improver 허용; model/view→reviewer 불허 등). |

## comm-matrix (11×11)

행=수신자, 열=발신자. 열·행 순서:
`sp-planner-.* , sp-router-.* , sp-implementer-.* , sp-tester-.* , sp-debugger-.* , sp-reviewer-.* , sp-improver-.* , sp-model-.* , sp-view-.* , sp-controller-.* , (?!sp-).*`

```
sp-planner-.*,sp-router-.*,sp-implementer-.*,sp-tester-.*,sp-debugger-.*,sp-reviewer-.*,sp-improver-.*,sp-model-.*,sp-view-.*,sp-controller-.*,(?!sp-).*
0,0,0,0,1,1,1,0,0,0,0
1,0,0,0,0,0,0,0,0,0,0
0,1,0,1,0,1,0,0,0,0,0
0,0,1,0,1,0,0,1,1,1,0
0,0,0,1,0,0,0,0,0,0,0
0,0,1,0,0,0,0,0,0,1,0
0,0,1,0,0,0,0,0,0,1,0
0,1,0,1,0,0,0,0,0,1,0
0,1,0,1,0,0,0,0,0,1,0
0,1,0,1,1,1,0,1,1,0,0
0,0,0,0,0,0,0,0,0,0,1
```

행별 의미(추가/변경분):
- **row3 (수신=tester)**: 기존 implementer·debugger + **model·view·controller** 추가 → 세 레이어 워커가 tester에 핑퐁 요청.
- **row5 (수신=reviewer)**: implementer + **controller** → MVC에선 controller만 리뷰 요청.
- **row6 (수신=improver)**: implementer + **controller** → controller만 종결 핸드오프.
- **row7 (수신=model)**: router(task)·tester(핑퐁 reply)·controller(크로스레이어/통합 지시).
- **row8 (수신=view)**: model과 동일.
- **row9 (수신=controller)**: router(task)·tester(핑퐁)·debugger(수정 라우팅)·reviewer(코드이슈)·model·view(완료 보고).

single-implementer 토폴로지(implementer 행/열)는 불변 — MVC 미스폰 시 inert.

## 데이터 흐름 (MVC 모드)

1. planner → router (승인된 플랜).
2. router 병렬 체크포인트 → 각 task를 소유 레이어로 dispatch (model/view/controller). 인스턴스 미상이면 `delegation_request`로 라우팅봇이 role resolve.
3. 각 레이어 워커: 자기 task별 tester와 TDD 핑퐁. 크로스레이어 필요 시 controller(또는 상대 레이어) 경유. 완료 시 controller에 보고(레이어 커밋/패치 핸드오프).
4. controller: 전 레이어 통합 → all-green이면 reviewer에 dispatch(diff/PR).
5. reviewer 코드이슈 → controller 수신 → 소유 레이어로 재라우팅(controller↔model/view) → 재검증.
6. reviewer 승인 → controller가 `finishing-a-development-branch` → improver(`type=closing`).
7. improver → 개선 발견 시 planner로 loop-back(ouroboros).

## 에러 / 엣지

- MVC 미배포(implementer만)인데 reviewer/improver가 "→ implementer" → 기존대로 implementer로 해소. 변경 없음.
- MVC인데 controller 미스폰 → 리드 부재. `agora-spawn-impl`의 MVC 경로는 항상 3종을 함께 스폰하므로 정상 경로에선 발생 안 함. 부분 스폰은 운영자 책임(문서 경고).
- 레이어 경계 모호한 task(여러 레이어 동시) → router가 controller(리드)에 배정, controller가 분해·위임.

## 테스트 (TDD)

- `test_superpowers_comm_matrix.py`: 11×11 파싱; 허용 — router→{model,view,controller}, {model,view,controller}→tester, controller→reviewer, controller→improver, model→controller, reviewer→controller; **불허** — model→reviewer, view→improver, router→(reviewer 직행 아님 등 기존 불변 엣지).
- 헤더 11열 순서·열수=행수 일치 검증.
- 기존 single-implementer 엣지(row2·row5 implementer 등) 회귀 없음.

## 호환 / 마이그레이션

- 단일 implementer 토폴로지·기존 7종 워크플로 불변.
- comm-matrix는 setup 스크립트가 `.agentagora/comm-matrix.csv`로 복사 → 재배포 시 자동 반영. 기배포 환경은 setup 재실행 필요(문서 주석).
- 페르소나 편집은 텍스트(행동 규칙)뿐 — 코드/스키마 변경 없음.

## 미해결 / 구현 시 확인

- **레이어 통합 메커니즘**: controller가 model/view의 레이어 커밋을 (a) 서브브랜치 머지로 모을지 (b) 패치 핸드오프로 받을지 — 분산(워커별 독립 클론) 환경 가정상 (a) 서브브랜치 머지가 현실적. 페르소나엔 "controller가 통합 책임"만 명시하고 구체 방식은 controller 판단에 위임(YAGNI). 운용하며 굳어지면 후속 spec.
- **debugger↔레이어 직결 여부**: v1은 tester→debugger→controller(리드 경유)로 단순화. 레이어 직결 디버깅이 필요해지면 row7/row8에 debugger 열 추가.
- comm_matrix.py 파서가 11열을 그대로 수용하는지(헤더 정규식 수 = 행 수 가정) 구현 시 확인.
