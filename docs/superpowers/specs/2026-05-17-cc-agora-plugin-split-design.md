# cc-agora 플러그인 생태계 재편 설계

> 2026-05-17. 단일 `cc-agora` 플러그인을 코어·운영자·역할별 페르소나 플러그인으로
> 재편하고, 마켓플레이스·플러그인 의존성·워커별 활성화 모델을 도입한다.
> 선행 ground truth: `docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md` (v2.1).

## 1. 배경 / 동기

현 `plugin/cc-agora/`는 단일 플러그인에 통신 슬래시·spawn 스크립트·역할 프리셋을
모두 담는다. 두 가지 문제가 있다.

- **관심사 혼재** — 팀을 *만드는* 운영자 도구(spawn)와 워커가 *런타임에 쓰는* 통신
  프리미티브가 한 네임스페이스에 섞여 있다.
- **역할 = 정적 텍스트** — 역할 페르소나가 `templates/presets/*.md`로 존재하고
  spawn이 워커 `CLAUDE.md`에 통째로 stamp한다. 역할이 배포·버전 관리 단위가 아니다.

재편안은 플러그인을 세 갈래로 나눈다 — 통신 **코어**, **운영자** 도구, 역할별
**페르소나** 플러그인. 페르소나는 코어에 의존하는 독립 배포 단위가 되고, 워커는
자기 디렉토리 스코프에서 자기 역할 플러그인만 활성화한다. 더불어 채널 모드 전환
(`agora.wait`→`agora.flush`)을 반영하고 신규 스킬 2종을 추가한다.

## 2. 플러그인 3종

| 플러그인 | 역할 | 슬래시 / 콘텐츠 | 의존성 |
|---|---|---|---|
| `cc-agora` | 통신 코어 (베이스) | `invoke`·`broadcast`·`agora-target`·`agora-close` + `agora-protocol`(워커 운용 규칙) | 없음 |
| `cc-agora-ops` | 운영자 도구 | `agora-spawn`·`agora-spawn-team`·`agora-comm-matrix` | 없음 (`cc-agora`와 무관) |
| `cc-agora-<role>` | 역할 페르소나 ×7 | 역할 정의 스킬(`persona`) | `["cc-agora"]` |

역할 7종: `orchestrator`·`coder`·`reviewer`·`tester`·`writer`·`planner`·`general`
(현 `templates/presets/`와 동일). 페르소나 플러그인 7개 — 역할당 1개.

**의존성 관계.** 페르소나 플러그인만 `cc-agora`에 의존한다. 페르소나를 활성화하면
코어가 자동 동반된다. `cc-agora-ops`는 어느 쪽과도 의존성이 없는 독립 플러그인이다 —
운영자가 통신도 하고 싶으면 `cc-agora`(또는 페르소나)를 따로 활성화한다.

## 3. 마켓플레이스

AgentAgora 저장소가 마켓플레이스를 발행한다 — `.claude-plugin/marketplace.json`
(저장소 루트). 위 9개 플러그인(코어 1 + 운영자 1 + 페르소나 7)을 `plugins` 배열에
등재하고, 각 `source`는 저장소 내 플러그인 디렉토리 상대경로다.

페르소나 플러그인의 `plugin.json`은 `dependencies: ["cc-agora"]`를 선언한다. 의존성은
선언 플러그인과 *같은 마켓플레이스* 안에서 해소되므로(plugin-dependencies 규약),
`cc-agora`가 같은 마켓플레이스에 있어 cross-marketplace 허용 설정은 불필요하다.

버전 제약은 이번 범위에서 두지 않는다 — 모든 플러그인이 한 저장소에서 함께
버전되므로 bare 이름 의존(`"cc-agora"`)으로 충분하다.

## 4. spawn 재설계 — 워커 `.claude/` 세팅

`cc-agora-ops`의 `agora-spawn`이 워커 디렉토리에 생성하는 산출물이 바뀐다. 더 이상
역할 페르소나를 `CLAUDE.md`에 통째로 stamp하지 않는다.

```
<worker>/
  CLAUDE.md              # thin — 정체성 + 페르소나 스킬 적용 지시 (§5)
  .mcp.json              # 2-서버 (HTTP + agora-channel stdio) — 기존 유지
  run.bat                # 채널 모드 기동 — 기존 유지
  .claude/
    settings.local.json  # 워커별 플러그인 활성화 (아래)
```

`.claude/settings.local.json`은 워커 디렉토리 스코프로 플러그인을 켠다 — 전역 활성화가
아니다:

- `extraKnownMarketplaces` — AgentAgora 마켓플레이스를 등록한다(소스: AgentAgora
  저장소). spawn은 이 소스를 알아야 하며, `--marketplace` 인자 또는 `config`의 기본값
  으로 결정한다(기본값은 AgentAgora 저장소).
- `enabledPlugins` — 워커의 역할 페르소나 플러그인(`cc-agora-<role>`)을 켠다.
  `cc-agora` 코어는 페르소나의 `dependencies`로 자동 동반되므로 따로 적지 않아도 된다.

`settings.local.json`의 정확한 JSON 스키마(`extraKnownMarketplaces`·`enabledPlugins`
키 형태)는 Claude Code settings 레퍼런스를 따르며 플랜 단계에서 확정한다.

spawn은 워커 `.claude/`에 *설정*을 쓴다 — 스킬 파일을 `.claude/skills/`로 복사하지
않는다. 로컬 스킬 파일은 향후 필요에 따라 별개로 다룬다(이번 범위 밖).

`config/roles.json`은 역할 → 페르소나 플러그인 이름 매핑이 된다(현재는 역할 →
preset). 미정의 role은 `general` 페르소나로 fallback + stderr 경고(현 §4.1 동작 유지).

## 5. 페르소나 전달 — 플러그인 스킬 + thin CLAUDE.md

역할 정체성은 두 조각으로 전달된다:

- **페르소나 스킬** — 페르소나 플러그인 안의 `skills/persona/SKILL.md`. frontmatter
  `user-invocable: false`(명령이 아니라 정체성 정의). 본문은 역할 페르소나 전문 —
  현 `templates/presets/<role>.md` 내용을 영어 스킬로 옮긴 것. `agora-protocol`을
  참조해 채널 모드 동작 규칙을 잇는다.
- **thin CLAUDE.md** — spawn이 워커 디렉토리에 stamp. 짧다. 담는 것: 워커 정체성
  (`instance_id`, `role`), "자기 역할 페르소나 스킬을 적용하라"는 지시, `agora-protocol`
  준수 지시. 역할 페르소나 본문은 담지 않는다 — 그건 스킬에 거주한다.

워커는 기동 시 thin CLAUDE.md(항상 로드)의 지시에 따라 첫 턴에 페르소나 스킬을
적용한다. 페르소나 본문이 플러그인에 거주하므로 역할이 배포·버전 관리 단위가 된다.

## 6. `cc-agora` 코어

기존 `plugin/cc-agora/`가 운영자·페르소나 콘텐츠를 덜어내고 통신 코어가 된다.

- 슬래시: `invoke`·`broadcast`·`agora-target`·`agora-close`. 기존 SKILL.md를
  영어로 옮기고 frontmatter를 정비한다(§9).
- 신규 `agora-protocol` 스킬 (§7).
- `scripts/payload.py` — `invoke`·`broadcast`가 쓰는 payload 헬퍼. 코어 전속.
- `.claude-plugin/plugin.json`(의존성 없음)·README.

## 7. 신규 — `agora-protocol` (코어, 워커 운용 규칙)

`cc-agora` 코어의 `user-invocable: false` 배경지식 스킬. 워커 에이전트 표준 동작의
단일 소스. 모든 페르소나가 코어에 의존하므로 모든 워커가 이 규칙을 공유한다. 본문
(영어)이 담을 내용:

- **수신 사이클** — 채널 알림으로 턴이 깨어나면 `agora.flush`로 인박스를 즉시
  드레인(논블로킹 — 블로킹 `agora.wait`는 제거됨), 처리 후 `agora.dispatch`로 reply.
- **payload 규약** — `type` enum(`task`·`reply`·`closing`·`ack`), `msgtype` 필수,
  `from`·`ts` 자동 채움. envelope 필드(`in_reply_to`·`closing`·`conversation_id`·
  `cc`·`priority`·`deadline_ts`)는 도구 인자로 전달, payload에 박지 않음.
- **comm-matrix 인지** — dispatch가 `comm_denied`로 거부될 수 있음. `flush`는 엣지
  weight 순 정렬이라 인박스가 FIFO가 아닐 수 있음.
- **conversation 예절** — reply 시 `in_reply_to`로 대화를 잇고, 종결은 `closing` 또는
  `/cc-agora:agora-close`.

## 8. `cc-agora-ops` (운영자)

신규 `plugin/cc-agora-ops/`. 운영자 제어 세션 전용.

- 슬래시: `agora-spawn`(§4 재설계 반영)·`agora-spawn-team`·신규 `agora-comm-matrix`.
- `scripts/`: `spawn.py`·`spawn_team.py`·`role_policy.py`·신규 `comm_matrix.py`.
- `config/roles.json` — 역할 → 페르소나 플러그인 매핑.
- `templates/`: `mcp.json.template`(워커 2-서버)·`team.json.example`·신규
  `run-server.bat`(로컬 서버 기동)·신규 `.mcp.json.example`(로컬 서버 접속 예시).
- `.claude-plugin/plugin.json`(의존성 없음)·README.

### 신규 — 로컬 서버 실행

`cc-agora-ops`가 로컬 AgentAgora 서버 기동을 패키징한다 — 운영자가 서버를 손으로
조립하지 않아도 되게.

- `templates/run-server.bat` — 서버 런처. `agent-agora` 콘솔 스크립트가 PATH에 있으면
  그것을, 없으면 `py -3.13 -m agent_agora`를 fallback으로 `--dir <스크립트 디렉토리>
  --port 8420 --no-tls`로 띄운다(서버가 `--dir` 하위에 `.agentagora`를 만든다). 종료는
  스폰된 창에서 Ctrl+C. **CRLF + ASCII**, `REM` 주석은 영어 — 한글 `REM`은 cmd.exe
  파서를 깨뜨린다(기존 `run.bat` 회귀에서 확인된 제약).
- `templates/.mcp.json.example` — 운영자/클라이언트 세션이 그 로컬 서버에 붙는 예시
  `.mcp.json`(서버 URL `http://127.0.0.1:8420/mcp`).

운영자는 `run-server.bat`을 복사·실행해 서버를 띄우고 `.mcp.json.example`로 세션을
붙인다. AgentAgora 서버는 여전히 별도 HTTP 프로세스다 — `.mcp.json`이 서버를 띄우지
않는다.

### 신규 — `agora-comm-matrix`

`disable-model-invocation: true` 스킬(ACL 재작성 부작용 — 운영자 명시 트리거).
comm-matrix v2 + 토큰 게이트 `/admin/comm-matrix` 엔드포인트
(spec `2026-05-17-comm-matrix-governance-design.md`)를 운영자가 쓰게 해 준다.

- `scripts/comm_matrix.py` — `AGORA_ADMIN_TOKEN` 환경변수를 읽어
  `Authorization: Bearer <token>`로 admin 엔드포인트 호출: `POST`(CSV로 매트릭스
  교체)·`GET`(현황 조회). 서버 URL은 `--server-url`(기본 `http://127.0.0.1:8420`).
- 토큰 미설정·401·400(CSV 오류)은 한국어 안내 메시지로 전달.

## 9. frontmatter / 언어 규약

frontmatter는 Claude Code skills 레퍼런스
(<https://code.claude.com/docs/en/skills#frontmatter-reference>)를 따른다. 모든
SKILL.md의 **본문·frontmatter는 영어**(CLAUDE.md 규약 2026-05-17 갱신).

| 슬래시 / 스킬 | frontmatter 핵심 | 근거 |
|---|---|---|
| `invoke`·`broadcast`·`agora-target`·`agora-close` | 기본 (모델·사용자 양쪽) | 워커가 턴 중 호출 + 사용자 수동 호출 |
| `agora-protocol` | `user-invocable: false` | 배경지식 — 명령 아님 |
| 페르소나 `persona` 스킬 | `user-invocable: false` | 정체성 정의 — 명령 아님 |
| `agora-spawn`·`agora-spawn-team`·`agora-comm-matrix` | `disable-model-invocation: true` | 운영자 명시 트리거하는 부작용 행위 |

인자 받는 슬래시(`invoke`·`agora-spawn` 등)에는 `argument-hint`를 추가한다.
README 등 산출물 문서는 한국어 우선(규약 유지).

## 10. 채널 반응 모델 반영 / 정리

- 잔존 stale wait 어휘 정리 — 예: `agora-close` SKILL.md의 "수신자가 wait를 못
  따라가는 중" → "메시지를 못 따라가는 중". 양 플러그인의 SKILL.md·README를 훑어
  채널 wake + `flush` 어휘로 일관시킨다.
- 워커 동작 모델은 `agora-protocol`에 중앙화. thin CLAUDE.md·페르소나 스킬은 폴링/
  wait 모델을 재기술하지 않고 `agora-protocol`을 참조한다.

## 11. 디렉토리 레이아웃

```
.claude-plugin/marketplace.json     # AgentAgora 마켓플레이스 (저장소 루트)
plugin/
  cc-agora/                         # 통신 코어
    .claude-plugin/plugin.json
    skills/{invoke,broadcast,agora-target,agora-close,agora-protocol}/SKILL.md
    scripts/payload.py
    README.md
  cc-agora-ops/                     # 운영자
    .claude-plugin/plugin.json
    skills/{agora-spawn,agora-spawn-team,agora-comm-matrix}/SKILL.md
    scripts/{spawn.py,spawn_team.py,role_policy.py,comm_matrix.py}
    config/roles.json
    templates/{mcp.json.template,team.json.example,run-server.bat,.mcp.json.example}
    README.md
  personas/
    <role>/                         # ×7 — orchestrator·coder·reviewer·tester·writer·planner·general
      .claude-plugin/plugin.json    # name cc-agora-<role>, dependencies ["cc-agora"]
      skills/persona/SKILL.md       # 역할 페르소나 (현 templates/presets/<role>.md 이관)
      README.md
  SMOKE.md                          # 공용 e2e
```

현 `templates/presets/*.md`는 페르소나 플러그인의 `skills/persona/SKILL.md`로 이관
되며 디렉토리 자체가 사라진다. `templates/mcp.json.template`·`team.json.example`은
spawn이 쓰므로 `cc-agora-ops/templates/`에 남는다.

## 12. 설치 / 테스트

- **워커** — 자기 디렉토리 `.claude/settings.local.json`으로 자기 역할 페르소나
  플러그인을 활성화(코어는 의존성 동반). 전역 설치가 아니다.
- **운영자 제어 세션** — `cc-agora-ops`를 활성화(전역 또는 디렉토리 스코프).
  통신도 하려면 페르소나/코어를 추가로 활성화.
- **테스트** — `tests/test_plugin_*.py`가 `spawn.py`·`spawn_team.py`·`role_policy.py`·
  `payload.py`를 import한다. 스크립트가 새 디렉토리로 이동하므로 import 경로·
  `sys.path` 셋업을 갱신한다. spawn 산출물 검증 테스트는 thin CLAUDE.md +
  `.claude/settings.local.json` 생성으로 기대값을 바꾼다. 신규 `comm_matrix.py`에
  단위 테스트(토큰 헤더, GET/POST 분기)를 추가한다.

## 13. 비목표 (YAGNI)

- **슬래시 이름 변경** — `agora-` 접두사 제거 등. breaking change, 범위 밖.
- **의존성 버전 제약** — bare 이름 의존으로 충분(§3).
- **HTML+JS 팀 현황 대시보드** — 별도 설계 항목. `cc-agora-ops`가 미래 주거지.
- **워커 로컬 스킬 파일** — `.claude/skills/`에 스킬을 두는 방식은 향후 필요에 따라
  별개로 다룬다. spawn은 이번 범위에서 `.claude/`에 *설정*만 쓴다.
- **아고라 통한 파일 공유** — 별도 설계 항목.

## 14. 구현 플랜 분할 (독립 머지 가능)

- **Plan 1 — `cc-agora` 코어 플러그인.** 통신 4종 슬래시 + `payload.py`를 정비
  (영어화·frontmatter), 신규 `agora-protocol` 스킬, `plugin.json`·README. 기존
  `plugin/cc-agora/`에서 운영자·페르소나 콘텐츠 제거.
- **Plan 2 — `cc-agora-ops` 플러그인.** spawn/spawn-team 스킬·스크립트 이동,
  spawn 재설계(thin CLAUDE.md + `.claude/settings.local.json`), `roles.json` 매핑
  변경, 신규 `agora-comm-matrix` + `comm_matrix.py`, `tests/test_plugin_*.py` import
  경로·spawn 산출물 기대값 갱신.
- **Plan 3 — 마켓플레이스 + 페르소나 플러그인.** `.claude-plugin/marketplace.json`,
  7개 페르소나 플러그인(`plugin.json` `dependencies:["cc-agora"]` + `persona` 스킬 —
  현 preset .md를 영어 스킬로 이관).

Plan 1(코어)이 먼저 — Plan 3의 페르소나가 `cc-agora`에 의존하고 Plan 2의 spawn이
페르소나 플러그인 이름을 참조한다. Plan 2·3은 Plan 1 위에서 진행한다.
