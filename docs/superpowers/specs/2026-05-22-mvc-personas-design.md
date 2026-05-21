# MVC 페르소나 — 설계

- 작성일: 2026-05-22
- 상태: 직접 실행 (운영자 "별도 승인 없이" 결정)
- 관련: `plugin/superpowers/superpowers-{model,view,controller}/` (신규), `plugin/.claude-plugin/marketplace.json`, `plugin/cc-agora-ops/config/roles.json`, `plugin/cc-agora-ops/templates/team-mvc.json.example` (신규), `plugin/cc-agora-ops/skills/agora-spawn-impl/SKILL.md` (신규)

## 1. 배경 / 문제

기존 superpowers 페르소나는 `implementer` 하나가 모든 구현 코드를 담당했다. UI를 가진 작업에서는 모델·뷰·컨트롤러를 한 워커가 동시에 만져 변경이 섞이고, 책임이 흐려지며, TDD 핑퐁의 단위도 거칠어진다. MVC 책임 분리를 페르소나 수준에서 강제하면:

- 각 워커의 구현 범위가 명확 — 한 layer만 만진다.
- comm-matrix를 통해 layer 간 직접 dispatch 흐름을 제한 가능.
- 운영자가 단순 작업엔 단일 implementer로, UI 복잡도 큰 작업엔 MVC 3종으로 토폴로지를 선택.

## 2. 목표 / 비목표

**목표** — 3개 신규 페르소나(model·view·controller) + 운영자가 스폰 시 단일 implementer / MVC 3종을 선택하는 슬래시.

**비목표** — implementer 폐지(공존). 자동 토폴로지 추론(운영자 선택). 영구 layer 위반 차단(comm-matrix는 별도 운영자 결정). cc-agora-ops가 아닌 cc-agora-* 페르소나 추가(superpowers 트랙만).

## 3. 페르소나 책임 분담

세 페르소나 모두 implementer의 TDD 핑퐁 워크플로(tester ↔ reviewer ↔ improver)를 그대로 따른다. 차이는 **편집 범위**.

### superpowers-model

데이터·상태·persistence·도메인 규칙 전담.

- 담당: 데이터 구조·dataclass·schema 정의, DB/persistence 레이어, 검증 로직, 도메인 모델, model 단위 테스트.
- 비담당: UI 렌더링·템플릿, 라우트 핸들러(routing만), 프레젠테이션.
- forward: 프레젠테이션 필요 → view, 조율 필요 → controller.

### superpowers-view

프레젠테이션 전담.

- 담당: HTML/템플릿, CSS, 클라이언트 JS(presentational), CLI output 포맷팅, 접근성, 시각 컴포넌트, view 단위 테스트.
- 비담당: persistence, 도메인 규칙, 라우팅, 비즈니스 로직.
- forward: 데이터 필요 → model, 상태 전이/라우팅 → controller.

### superpowers-controller

조율 전담.

- 담당: 라우트 핸들러, 요청 처리, command dispatch, 상태 머신, model↔view 통합, controller 단위 테스트.
- 비담당: 데이터 구조 정의(model), 시각 표현(view).
- forward: 데이터 변경/검증 → model, 출력 형식 → view.

## 4. 플러그인 구조

각 페르소나는 기존 `superpowers-implementer`와 동일 구조:

```
plugin/superpowers/superpowers-{model,view,controller}/
  .claude-plugin/plugin.json   # dependencies: ["superpowers-base"]
  README.md                     # 한국어
  skills/persona/SKILL.md       # 영어, frontmatter user-invocable: false
```

추가 스킬(executing-plans·using-git-worktrees·finishing-a-development-branch)은 implementer와 동일하게 owned로 표기 — 같은 파일을 vendor copy하지 않고, persona SKILL.md에서 base + implementer의 skill 표면을 참조한다.

## 5. roles.json·marketplace 등록

`plugin/cc-agora-ops/config/roles.json`에 3행 추가:

```json
"sp-model":      { "plugin": "superpowers-model" },
"sp-view":       { "plugin": "superpowers-view" },
"sp-controller": { "plugin": "superpowers-controller" }
```

`plugin/.claude-plugin/marketplace.json`에 3 entry 추가 — 기존 superpowers-* 패턴 그대로.

## 6. 운영자 스폰 선택

신규 슬래시 `/cc-agora-ops:agora-spawn-impl`:

1. `AskUserQuestion`으로 **단일 implementer** vs **MVC 3종** 제시.
2. 단일 → `do_spawn(role="sp-implementer", ...)` 한 번 호출.
3. MVC → `do_spawn_team(manifest="team-mvc.json.example", ...)` — 3 워커(model·view·controller) 한 번에.

또는 기존 `agora-spawn-team`에 `team-mvc.json.example` 매니페스트를 사용해도 동등. 슬래시는 운영자가 매니페스트를 외우지 않도록 묶음.

**team-mvc.json.example** (`plugin/cc-agora-ops/templates/team-mvc.json.example`):

```json
{
  "version": 1,
  "team": [
    {"id": "Model1", "role": "sp-model", "description": "데이터·상태·persistence·도메인 규칙 전담"},
    {"id": "View1", "role": "sp-view", "description": "프레젠테이션·UI·템플릿 전담"},
    {"id": "Controller1", "role": "sp-controller", "description": "라우팅·요청 처리·model↔view 조율 전담"}
  ]
}
```

## 7. 파일 영향

| 파일 | 변경 |
|---|---|
| `plugin/superpowers/superpowers-model/.claude-plugin/plugin.json` | 신규 |
| `plugin/superpowers/superpowers-model/README.md` | 신규 (한국어) |
| `plugin/superpowers/superpowers-model/skills/persona/SKILL.md` | 신규 (영어) |
| `plugin/superpowers/superpowers-view/.claude-plugin/plugin.json` | 신규 |
| `plugin/superpowers/superpowers-view/README.md` | 신규 |
| `plugin/superpowers/superpowers-view/skills/persona/SKILL.md` | 신규 |
| `plugin/superpowers/superpowers-controller/.claude-plugin/plugin.json` | 신규 |
| `plugin/superpowers/superpowers-controller/README.md` | 신규 |
| `plugin/superpowers/superpowers-controller/skills/persona/SKILL.md` | 신규 |
| `plugin/.claude-plugin/marketplace.json` | 3 entry 추가 |
| `plugin/cc-agora-ops/config/roles.json` | 3 row 추가 |
| `plugin/cc-agora-ops/templates/team-mvc.json.example` | 신규 |
| `plugin/cc-agora-ops/skills/agora-spawn-impl/SKILL.md` | 신규 |
| `tests/test_plugin_marketplace.py` | 신규 3 plugin 검증 |
| `tests/test_role_policy.py` (있으면) | 신규 3 role 검증 |

## 8. 테스트

- 마켓플레이스에 신규 3 plugin entry 존재·source 경로 유효성.
- `roles.json`에 `sp-model`·`sp-view`·`sp-controller`가 올바른 plugin 매핑.
- 각 페르소나 플러그인 `plugin.json` 유효 JSON + `dependencies: ["superpowers-base"]`.
- `team-mvc.json.example` 매니페스트 스키마 유효성 (`spawn_team.py`가 파싱 가능).
- 슬래시 SKILL.md 존재 + AskUserQuestion 분기 검증 (정적 텍스트 검사 수준).

## 9. 미해결

없음. comm-matrix를 통한 layer 간 dispatch 흐름 강제(예: model↔view 직접 dispatch 금지)는 운영자가 별도 작성·적용한다 (본 spec 범위 외).
