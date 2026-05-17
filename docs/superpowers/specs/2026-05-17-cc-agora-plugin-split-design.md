# cc-agora 플러그인 split 설계

> 2026-05-17. 단일 `cc-agora` 플러그인을 운영자용·에이전트용 두 플러그인으로 분리하고,
> 채널 기반 반응 모델을 반영하며, 신규 스킬 2종을 추가한다.
> 선행 ground truth: `docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md` (v2.1).

## 1. 배경 / 동기

현 `plugin/cc-agora/`는 단일 플러그인에 슬래시 6개 + spawn 스크립트 + roles/presets/templates를
모두 담는다. 슬래시는 성격이 둘로 갈린다:

- **팀 셋업** — `agora-spawn`, `agora-spawn-team`. 사람(운영자)이 제어 세션에서 팀을 구성한다.
- **런타임 통신** — `invoke`, `broadcast`, `agora-target`, `agora-close`. 워커 에이전트가
  자기 턴 중 동료와 통신·조율한다.

이 둘을 한 플러그인에 두면 워커 환경에 운영자 셋업 도구까지 노출되고, 두 관심사가 한
네임스페이스에 섞인다. v2는 이를 두 플러그인으로 분리한다. 더불어 `agora.wait`→`agora.flush`
+ 채널 모드 전환이 끝났으므로 플러그인 산출물을 채널 wake 모델로 일관시키고, 최근 기능
(채널 모드, comm-matrix v2 + admin 엔드포인트)을 반영한 신규 스킬 2종을 추가한다.

## 2. 두 플러그인 구조

`plugin/cc-agora/` 단일 → 두 플러그인:

- **`cc-agora`** (에이전트용) — **이름을 유지**한다. 워커·참여자가 쓰는 통신 프리미티브.
  `/cc-agora:invoke`·`/cc-agora:broadcast` 등 자주 쓰는 슬래시 네임스페이스가 그대로라
  기존 muscle memory·문서 disruption이 최소화된다. 기존 `plugin/cc-agora/` 디렉토리가
  운영자 콘텐츠를 덜어내고 에이전트 플러그인이 된다.
- **`cc-agora-ops`** (운영자용) — 신규. 팀 셋업·관리. `/cc-agora-ops:agora-spawn` 등.

```
plugin/
  cc-agora/                         # 에이전트 플러그인 (기존 디렉토리에서 운영자 콘텐츠 제거)
    .claude-plugin/plugin.json
    skills/
      invoke/SKILL.md
      broadcast/SKILL.md
      agora-target/SKILL.md
      agora-close/SKILL.md
      agora-protocol/SKILL.md       # 신규 (§5)
    scripts/payload.py
    README.md
  cc-agora-ops/                     # 운영자 플러그인 (신규)
    .claude-plugin/plugin.json
    skills/
      agora-spawn/SKILL.md
      agora-spawn-team/SKILL.md
      agora-comm-matrix/SKILL.md     # 신규 (§6)
    scripts/
      spawn.py
      spawn_team.py
      role_policy.py
      comm_matrix.py                 # 신규 (§6)
    config/roles.json
    templates/
      mcp.json.template
      team.json.example
      presets/{orchestrator,coder,reviewer,tester,writer,planner,general}.md
    README.md
  SMOKE.md                          # 공용 e2e (spawn→invoke 흐름이 양 플러그인 횡단)
```

**공유 코드 없음.** `payload.py`는 `invoke`·`broadcast`만 쓰므로 에이전트 플러그인 전용,
spawn 일체(`spawn.py`·`spawn_team.py`·`role_policy.py`·`config/`·`templates/`)는 운영자
전용이다. 한 파일이 양쪽에 필요한 경우가 없어 깔끔히 분리된다.

`SMOKE.md`는 spawn→invoke가 한 시나리오에 걸치는 e2e 문서라 어느 한 플러그인에 속하지
않는다. `plugin/SMOKE.md`(plugin 디렉토리 최상위)로 옮긴다.

## 3. 슬래시 배분

"라이프사이클 vs 통신" 기준:

| 플러그인 | 슬래시 | 분류 |
|---|---|---|
| `cc-agora` | `invoke` | 통신 — 한 워커에 task dispatch |
| `cc-agora` | `broadcast` | 통신 — 전원 fan-out |
| `cc-agora` | `agora-target` | 통신 — task에 맞는 워커 추천 |
| `cc-agora` | `agora-close` | 통신 — conversation 종결 |
| `cc-agora` | `agora-protocol` | 신규 — 에이전트 운용 규칙 (§5) |
| `cc-agora-ops` | `agora-spawn` | 라이프사이클 — 워커 1명 셋업 |
| `cc-agora-ops` | `agora-spawn-team` | 라이프사이클 — manifest 일괄 셋업 |
| `cc-agora-ops` | `agora-comm-matrix` | 신규 — 운영자 comm-matrix 관리 (§6) |

통신 슬래시를 에이전트 플러그인에 두는 근거: 통신은 *참여자*라면 누구나 하는 행위다.
오케스트레이터(제어 세션)도 워커도 dispatch·broadcast·close를 한다. 운영자 제어 세션은
두 플러그인을 모두 설치하므로(§7), 통신 슬래시를 에이전트 플러그인에 두어도 운영자가
못 쓰게 되지 않는다. 반대로 spawn은 팀을 *만드는* 행위로 제어 세션에서만 일어난다.

**슬래시 이름은 바꾸지 않는다.** `agora-` 접두사 제거 등은 breaking change이며 이번
범위 밖이다 (§9).

## 4. frontmatter

frontmatter는 Claude Code skills frontmatter 레퍼런스
(<https://code.claude.com/docs/en/skills#frontmatter-reference>)를 따른다. 모든 SKILL.md의
**본문·frontmatter를 영어로 작성**한다 (CLAUDE.md 규약 2026-05-17 갱신 — 스킬·서브에이전트
정의는 영어).

| 슬래시 | frontmatter 핵심 | 근거 |
|---|---|---|
| `invoke`·`broadcast`·`agora-target`·`agora-close` | 기본 (모델·사용자 양쪽 invoke 가능) | 워커 에이전트가 턴 중 자동 호출 + 운영자도 수동 호출 |
| `agora-protocol` | `user-invocable: false` | 배경지식 — 명령이 아니라 워커가 따르는 규칙. 사용자가 `/agora-protocol`로 직접 부를 일 없음 |
| `agora-spawn`·`agora-spawn-team` | `disable-model-invocation: true` | 운영자가 명시 트리거하는 셋업 행위. 에이전트가 임의로 워커를 spawn하지 않게 함 |
| `agora-comm-matrix` | `disable-model-invocation: true` | ACL 재작성이라는 부작용. 운영자만, 명시 트리거 |

각 SKILL.md는 기존 frontmatter의 `description`을 유지·정비하고, 위 표의 invocation 제어
필드를 추가한다. `argument-hint`는 인자를 받는 슬래시(`invoke`·`broadcast`·`agora-spawn`
등)에 추가해 자동완성 힌트를 준다.

## 5. 신규 — `agora-protocol` (에이전트 운용 규칙 레퍼런스)

`cc-agora` 플러그인의 `user-invocable: false` 배경지식 스킬. 워커 에이전트의 표준 동작을
**단일 소스**로 모은다. 본문(영어)이 담을 내용:

- **수신 사이클** — 채널 알림으로 턴이 깨어나면 `agora.flush`로 인박스를 즉시 드레인하고
  (논블로킹 — 블로킹 `agora.wait`는 제거됨), 드레인한 메시지를 처리한 뒤 `agora.dispatch`로
  발신자에게 reply한다.
- **payload 규약** — payload의 `type` enum (`task`·`reply`·`closing`·`ack`), `msgtype` 필수,
  `from`·`ts` 자동 채움. envelope 필드(`in_reply_to`·`closing`·`conversation_id`·`cc`·
  `priority`·`deadline_ts`)는 도구 인자로 전달하고 payload에 박지 않는다.
- **comm-matrix 인지** — dispatch가 `comm_denied`로 거부될 수 있음. `flush`는 엣지 weight
  순으로 정렬되므로 인박스 순서가 FIFO가 아닐 수 있음.
- **conversation 예절** — reply 시 `in_reply_to`로 conversation을 잇는다. 대화를 끝낼 땐
  `closing` 또는 `/cc-agora:agora-close`.

프리셋 CLAUDE.md(§7의 `templates/presets/`)는 이 동작 규칙을 중복 기술하지 않고
`agora-protocol`을 가리키도록 슬림화한다 — 운용 규칙의 단일 진실은 이 스킬이다.

## 6. 신규 — `agora-comm-matrix` (운영자 comm-matrix 관리)

`cc-agora-ops` 플러그인의 `disable-model-invocation: true` 스킬. comm-matrix v2 + 토큰
게이트 `/admin/comm-matrix` 엔드포인트(spec `2026-05-17-comm-matrix-governance-design.md`)를
운영자가 쓰게 해 준다.

- **`scripts/comm_matrix.py`** (신규) — `AGORA_ADMIN_TOKEN` 환경변수를 읽어
  `Authorization: Bearer <token>` 헤더로 admin 엔드포인트를 호출한다:
  - `POST /admin/comm-matrix` — CSV 본문으로 in-memory 매트릭스를 재기동 없이 교체.
  - `GET /admin/comm-matrix` — 현재 매트릭스·active 상태 조회.
- **슬래시 인자** — CSV 파일 경로를 받으면 `POST`, 인자 없거나 조회 모드면 `GET`.
  서버 URL은 `--server-url`로 오버라이드(기본 `http://127.0.0.1:8420`).
- 토큰 미설정·401·400(CSV 오류)은 한국어 안내 메시지로 사용자에게 전달한다.

## 7. 채널 반응 모델 반영 + 정리

- **잔존 stale 표현 정리** — 블로킹 wait 어휘가 남은 곳을 채널 wake + `flush`로 고친다.
  알려진 예: `agora-close/SKILL.md`의 "수신자가 wait를 못 따라가는 중" → "메시지를 못
  따라가는 중". split 작업 중 양 플러그인의 SKILL.md·README를 훑어 동일 표현을 정리한다.
- **워커 동작 모델 중앙화** — 프리셋·README가 폴링/wait 모델을 따로 설명하지 않고
  `agora-protocol`을 참조하게 한다.
- **README 분리** — 각 플러그인이 자기 README.md를 갖는다. 한국어 산출물 문서(README)는
  유지하되 스킬 본문·frontmatter는 영어. 운영자 README는 spawn·comm-matrix 흐름을,
  에이전트 README는 통신 슬래시·`agora-protocol`을 다룬다.
- **`plugin.json`** — 두 플러그인 각각 `name`·`description`·`version`을 갖는다.
  `cc-agora` description은 에이전트 통신, `cc-agora-ops`는 운영자 셋업으로 갱신.

## 8. 설치 모델 / 테스트

- **`cc-agora`** (에이전트) — 모든 워커 환경에 전역 설치(`~/.claude/plugins/`). 워커는
  전역 설치된 에이전트 플러그인으로 통신 슬래시·`agora-protocol`을 얻는다.
- **`cc-agora-ops`** (운영자) — 제어 세션 환경에만 설치. 오케스트레이터 세션은 두 플러그인을
  모두 설치한다(팀 spawn + 통신 참여).
- **테스트** — `tests/test_plugin_*.py`가 `spawn.py`·`spawn_team.py`·`role_policy.py`·
  `payload.py`를 import한다. 스크립트가 새 디렉토리(`cc-agora-ops/scripts/`,
  `cc-agora/scripts/`)로 이동하므로 테스트의 import 경로·`sys.path` 셋업을 갱신한다.
  신규 `comm_matrix.py`에는 단위 테스트를 추가한다(토큰 헤더 구성, GET/POST 분기).

## 9. 비목표 (YAGNI)

- **슬래시 이름 변경** — `agora-` 접두사 제거 등. breaking change이며 범위 밖.
- **HTML+JS 팀 현황 대시보드** — 별도 설계 항목. `cc-agora-ops`가 미래 주거지이나 표시
  데이터·레이아웃·갱신 방식은 자체 설계가 필요하다.
- **워커 프리셋 폴더화** — `templates/presets/*.md` → 폴더 단위 전환은 별도 설계 항목.
  이번 split에서는 프리셋을 `cc-agora-ops/templates/presets/`로 *이동*만 한다.

## 10. 구현 플랜 분할 (독립 머지 가능)

- **Plan 1 — 운영자 플러그인 추출.** `cc-agora-ops/` 신설, spawn 스킬·스크립트·config·
  templates 이동, `plugin.json`·README, `tests/test_plugin_*.py` import 경로 갱신.
  `agora-protocol`·`agora-comm-matrix`는 아직 없음 — 순수 이동 + 디렉토리 분리.
- **Plan 2 — 에이전트 플러그인 정비 + `agora-protocol`.** `cc-agora`에서 운영자 콘텐츠
  제거, 통신 4종 frontmatter 정비, 신규 `agora-protocol` 스킬, stale wait 표현 정리,
  프리셋 슬림화.
- **Plan 3 — `agora-comm-matrix` 스킬.** `cc-agora-ops`에 `comm_matrix.py` + 스킬 + 테스트.

Plan 1이 먼저(디렉토리 구조 확정). Plan 2·3은 Plan 1 위에서 독립적.
