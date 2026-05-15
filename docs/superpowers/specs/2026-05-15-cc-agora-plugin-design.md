# cc-agora Claude Code Plugin — Design Spec

- 날짜: 2026-05-15 (v2 — v3 서버 코드 대조 보강 + batch spawn + 한국어 우선 정책)
- 대상 코드: `AgentAgora/plugin/cc-agora/` (신규)
- 베이스: 없음 (신규 플러그인)
- 입력 문서: [feature-proposals-2026-05-15.md](../../feature-proposals-2026-05-15.md)
- 결정 방식: v1 — Inst1 brainstorming + 워커 6명(Inst2/4/5/6/7/8) 디테일 두 라운드. v2 — v3 서버 (`src/agent_agora/dispatcher.py`, `auto_register.py`, `server.py`) 대조 + 사용자 직접 결정.

## 1. 배경

AgentAgora MCP 서버를 사용하는 Claude Code 인스턴스(orchestrator + 워커들)의 셋업·통신은 현재 손작업 비중이 크다. 본 세션에서 직접 실측된 보일러플레이트:

- **셋업**: 새 워커 추가 시 디렉토리 + `CLAUDE.md`(페르소나) + `.mcp.json`(instance_id/role/description 헤더) + `.claude/settings.local.json`(Stop hook)을 손으로 4파일 생성·정합성 유지.
- **통신**: `agora.dispatch` / `agora.broadcast` 호출은 자연어 부탁("Inst3에게 X 보내")보다 짧은 슬래시가 토큰 효율적이고 의도가 명확. target 선택은 사용자/orchestrator의 머릿속 매칭에 의존.
- **wait 제어**: Stop hook은 강제 진입만 있고 fine-grain 제어(timeout, from_sources 필터, 일시 비활성)는 직접 도구 호출.

이 빈 자리를 Claude Code 플러그인으로 채운다.

## 2. 목표 / Non-goals

### 목표

1. **개별 + 일괄 spawn** — `/agora-spawn`(개별)과 `/agora-spawn-team`(manifest 기반 일괄)로 새 워커 인스턴스 셋업.
2. **통신 슬래시 7개**로 일상 통신을 짧게 — `/agora-target`, `/agora-wait`, `/agora-unwait`, `/agora-rewait`, `/broadcast`, `/invoke`, `/agora-close`.
3. **Role 기반 hook 자동 분기** — `roles.json` single source of truth + 미정의 role은 hook 미설치 + 경고. `wait_mode`는 hook policy에서 derive.
4. **워커 페르소나 공통 규약** — 응답 시 다른 멤버에 forward 가능, wait 진입 시 페르소나 규칙 비적용.
5. **산출물 한국어 우선** — 플러그인 산출물(`commands/*.md`, `templates/presets/*.md`, README, `team.json.example`)은 한국어로 작성. 영어 번역은 별도 작업으로 일정 시점에 일괄. 코드·식별자·MCP 도구 이름은 영어 유지.

### Non-goals (명시 제외)

- **`/agora-target` 자동 dispatch** — 사용자 결정으로 제외. *워커 6명 만장일치(X1: `--auto` 플래그 옵트인)는 추후 재도입 시 권장 형태로 §6 결정 트레일에 보존*.
- **Observability 슬래시** (`/agora-transcript`, `/agora-coverage`) — 어제 brainstorming 결과의 P1 server-side 도구 도입에 종속. 클라이언트 슬래시는 P1 후속.
- **LLM 자동 페르소나 초안** — Inst6(Writer) 우려: 자동 초안은 일반론·형용사 나열로 빠져 워커 톤 평탄화. 프리셋 큐레이션으로 floor 확보, 추가 작성은 사용자.
- **그룹 conversation 시맨틱** (multi-target dispatch) — 어제 brainstorming 결론(YAGNI) 따름.
- **자동 등록·healthcheck** — 워커가 실제로 시작되면 `.mcp.json` 헤더로 자동 등록되는 기존 메커니즘이 충분.
- **전체 의회 reset 슬래시** — 등록된 모든 인스턴스를 한 번에 unregister 하는 슬래시는 제외. 서버 재시작이 간결한 대안이고, stale entry는 dead-session sweep(`dispatcher.dead_session_sweep`)이 자동 정리.
- **`/invoke --priority=high`의 자동 분기** — `priority`는 envelope 인자로 전달만, 워커 페르소나 측 처리는 *권장*에 그침 (실제 sort는 `/agora-wait --sort=priority`에서만 활성).
- **`cc` observers의 페르소나 강제** — `delivered_as='cc'`인 메시지에 워커가 자동 응답하지 않도록 페르소나 규약에 한 줄 추가하되, 강제 hook은 없음.

## 3. 패키지 형태

### 위치

`AgentAgora/plugin/cc-agora/` — AgentAgora 모노레포에 공존. 별도 repo 안 함(사용자 확정). Python 서버와 디렉토리만 분리, 같은 git 트리.

### 표준 Claude Code 플러그인 컨벤션

```
plugin/cc-agora/
  .claude-plugin/
    plugin.json             # plugin manifest (name, description, version)
  README.md                 # 한국어
  skills/                   # user-invokable slash skills — 각 폴더 = 슬래시 1개
    agora-spawn/SKILL.md
    agora-spawn-team/SKILL.md
    agora-target/SKILL.md
    agora-wait/SKILL.md
    agora-unwait/SKILL.md
    agora-rewait/SKILL.md
    agora-close/SKILL.md
    broadcast/SKILL.md
    invoke/SKILL.md
  scripts/
    spawn.py                # /agora-spawn 본체
    spawn_team.py           # /agora-spawn-team 본체 (manifest 로더)
    role_policy.py          # roles.json 로더 + wait_mode derive
    payload.py              # payload 표준 (type enum, 기본 필드)
  config/
    roles.json              # 확장 가능한 role-policy single source of truth
  templates/
    mcp.json.template       # X-Agora-Wait-Mode, X-Agora-Wait-Timeout-Ms 헤더 포함
    settings.local.json.template  # type:"prompt" Stop hook (별도 .py 파일 없음)
    team.json.example       # /agora-spawn-team manifest 예시 (한국어 description)
    presets/                # 한국어. 골격은 §5.5 참조.
      orchestrator.md
      coder.md
      reviewer.md
      tester.md
      writer.md
      planner.md
      general.md
```

**slash 호출 형식 (Claude Code plugin 컨벤션)**: 슬래시는 plugin namespace prefix가 붙어 호출된다. 예 — `skills/agora-spawn/SKILL.md` → `/cc-agora:agora-spawn`. 본 spec 본문은 가독성을 위해 짧은 형태(`/agora-spawn`) 표기를 유지하되, 실제 호출은 `/cc-agora:agora-spawn`. SKILL.md 본문은 한국어, frontmatter는 영어 키(`description` 필수). skill 본문에서 외부 Python 스크립트를 호출하려면 Bash 도구로 `python scripts/<name>.py $ARGUMENTS` 패턴 — plugin root 기준 상대 경로로 실행된다.

**`commands/` 폴더 미사용 이유**: `commands/`는 Claude Code 레거시 평면 Markdown 컨벤션. `skills/`는 폴더 단위로 보조 파일·references를 둘 수 있는 신규 표준. 사용자 정정 ("실행 가능한 커맨드는 user-invokable 스킬이다") 적용. §6 결정 11 참조.

플러그인 install이 *사용자 환경 전체*에 hook을 박지 않는다는 점이 중요. Inst7의 우려("spawn했더니 인스턴스가 안 멈춰요" 디버깅 경로) 차단.

## 4. 컴포넌트

### 4.1 `config/roles.json` — Role-Policy 설정 파일

확장 가능한 single source of truth. 사용자 편집 가능.

```json
{
  "orchestrator": { "hook": "none",           "preset": "orchestrator" },
  "coder":        { "hook": "stop-auto-wait", "preset": "coder" },
  "reviewer":     { "hook": "stop-auto-wait", "preset": "reviewer" },
  "tester":       { "hook": "stop-auto-wait", "preset": "tester" },
  "writer":       { "hook": "stop-auto-wait", "preset": "writer" },
  "planner":      { "hook": "stop-auto-wait", "preset": "planner" },
  "general":      { "hook": "stop-auto-wait", "preset": "general" }
}
```

**Hook 정책 enum**:

- `"stop-auto-wait"` — Stop hook으로 `agora.wait(timeout_ms=0)` 자동 호출. Inst2/.claude/settings.local.json 패턴.
- `"none"` — settings.local.json을 만들지 않거나 빈 hooks.

**`wait_mode` derive (v3 코드 대조 보강)**: 서버는 `X-Agora-Wait-Mode: auto|manual` 헤더로 wait_mode를 등록 (`src/agent_agora/auto_register.py:11`). 본 플러그인은 hook policy에서 derive해 별도 설정 항목을 두지 않는다.

| hook | derived wait_mode |
| ---- | ----------------- |
| `stop-auto-wait` | `auto` |
| `none` | `manual` |
| (미정의 role) | 헤더 미박음 → 서버가 `unknown`으로 기록 |

이 매핑은 `scripts/role_policy.py`가 단일 함수(`wait_mode_for(role)`)로 노출한다. roles.json에 명시적 `wait_mode` 필드를 두는 옵션은 폐기 — 두 곳이 갈라지면 정합성 사고 위험(전회 SessionCloseMiddleware false-fire 패턴 재현 가능).

**미정의 role 처리 (v2 명세 보강)**:

- spawn은 **진행한다** (abort 아님).
- 디렉토리 + `CLAUDE.md`(general preset 디폴트 적용) + `.mcp.json`은 생성한다.
- `.claude/settings.local.json`은 **생성하지 않는다** (hook 미설치).
- stderr에 한국어 경고 한 줄: `[cc-agora] 경고: role '<x>'는 roles.json에 정의되지 않음. hook 미설치. roles.json 편집 가이드: config/roles.json에 {"<x>": {"hook":"stop-auto-wait","preset":"general"}} 항목 추가 후 settings.local.json 수동 보강.`
- 종료 코드는 성공(0). 워커 자체는 정상 동작.

### 4.2 `/agora-spawn <id> <role> <description> [--preset=<role>] [--dir=<path>]`

1. `roles.json` 조회 → hook/preset/wait_mode 결정. 미정의 role이면 §4.1 미정의 처리 적용.
2. `<id>/` 디렉토리 생성. **디폴트 경로 결정 순서** (먼저 매칭되는 것 채택):
   1. `--dir=<path>` 명시 오버라이드.
   2. 환경변수 `AGORA_HOME` (예: `~/AgoraTest`).
   3. 슬래시 호출 시점의 cwd가 `<parent>/<some-instance>/` 패턴(즉 `.mcp.json`을 가진 워커 디렉토리)이면 그 부모 = `<parent>`.
   4. 그 외에는 cwd 자체. (orchestrator가 임의 디렉토리에서 실행 시 의도와 어긋날 수 있으므로 stderr 경고 + 생성 경로 명시 출력.)
3. 파일 생성:
   - `<id>/CLAUDE.md` — `templates/presets/<preset>.md` 복사 + description 헤더 치환.
   - `<id>/.mcp.json` — `mcp.json.template`에 다음 헤더를 치환·자동 박음 (모두 forward slash + ASCII 인용 안전):
     - `X-Agora-Instance-Id: <id>`
     - `X-Agora-Role: <role>`
     - `X-Agora-Description: <description>`
     - `X-Agora-Wait-Mode: <derived>` (§4.1 표. 미정의 role이면 헤더 생략)
     - `X-Agora-Wait-Timeout-Ms: 0` (unbounded 디폴트. 서버가 `--no-timeout` 미적용 상태여도 워커 측에서 unbounded 요청.)
   - `<id>/.claude/settings.local.json` — `stop-auto-wait`일 때만 생성. `type:"prompt"` Stop hook(인라인 prompt 텍스트, 별도 `.py` 파일 없음). `none`이거나 미정의 role이면 생략.
4. `--preset=<role>` 명시 시 그 role의 preset 강제. 미명시 시 roles.json의 preset 사용.
5. 등록은 자동 안 함 — 사용자가 `<id>/`에서 `claude` 실행하면 .mcp.json 헤더로 자동 등록되는 기존 메커니즘.
6. **이미 존재하는 `<id>/`** — 에러로 실패 (덮어쓰기 금지). `--force`로만 덮어쓰기 허용 (미존재 시 옵션 효과 없음).

### 4.3 `/agora-target "<task>"`

1. **1차 필터** — `agora.find(query=<task>의 키워드)` 호출 (`src/agent_agora/server.py:131`). instance_id/role/description 중 키워드를 포함하는 후보만 추림. 토큰 절약.
2. **2차 필터** — 1차 결과가 비면 `agora.instances`로 전체 목록을 받아 LLM이 매칭.
3. LLM이 task와 매칭한 **1순위 추천 워커** + 짧은 사유(1~3문장; 인스턴스 수가 많으면 1문장으로 줄임)를 표시.
4. **자동 발사 X (chaining)** — 슬래시 결과로 `/invoke <recommended-instance> "<task>"` 형태의 다음 명령 *제안 문자열*을 화면에 출력한다. Claude Code의 슬래시 응답이 다음 입력을 자동으로 prefill 하는 표준 메커니즘은 없으므로, 사용자가 그 문자열을 복사·수정·확정 후 Enter. (UX 가정 명시.)

자동 발사 재도입 시 권장 형태는 §6 결정 트레일에 보존.

### 4.4 `/agora-wait [--timeout=<ms>] [--from=<id>,...] [--conv=<id>]`

`agora.wait` 래퍼. Stop hook이 디폴트 폴링(timeout=0 unbounded)을 담당하므로 이 슬래시는 fine-grain 제어용. 인자 없으면 동일하게 unbounded.

### 4.5 `/agora-unwait`

자기 인스턴스의 Stop hook을 일시 비활성. 동작:

1. `<.claude/settings.local.json>`을 `<.claude/settings.local.json.bak>`로 복사 (기존 `.bak`은 덮어쓰기 — 백업의 백업은 두지 않음, 한 단계 deep 복원만 지원).
2. 원본의 `hooks` 섹션을 제거하거나 빈 객체로 치환.
3. 사용자에 한 줄 안내: "다음 wait는 호출되지 않습니다. 복원은 `/agora-rewait`."
4. orchestrator (`hook: none`)는 no-op + "orchestrator는 hook이 없습니다" 안내.
5. `.bak`이 이미 있으면 (이전 unwait 이후 rewait 안 함) 두 번째 unwait는 no-op + 경고.

### 4.5b `/agora-rewait`

`/agora-unwait`의 짝. `<.claude/settings.local.json.bak>`을 원본으로 복원하고 `.bak` 삭제. `.bak`이 없으면 no-op + "복원할 백업 없음" 안내. 사용자가 hook이 즉시 발화하길 원하면 다음 턴에 자연스럽게 wait 진입.

### 4.6 `/broadcast "<message>" [--closing] [--priority=<level>] [--conv=<id>] [--expect]`

`agora.broadcast` 래퍼. payload는 §5.3 표준 — `{from, type, ts, message}` 자동 채움 (`type="task"` 디폴트, `--closing`이면 `type="closing"`). 옵션은 `/invoke`와 의미 동일.

`--closing`은 서버 측에서 announcement 패턴으로 즉시 대화를 닫는 의미 (`dispatcher.py:394-397`). 일상 fan-out에는 쓰지 않는다 — 회의 종료, 시스템 셧다운 알림 등 한 방향 종결 신호.

### 4.7 `/invoke <instance> "<message>" [--reply-to=<cmd>] [--conv=<id>] [--expect] [--cc=<ids>] [--closing] [--priority=<level>] [--deadline=<iso>]`

`agora.dispatch` 래퍼. payload §5.3 표준 자동 채움. 옵션:

- `--reply-to=<cmd_id>` → `in_reply_to` 명시 (서버의 in_flight tracking 해제 연결).
- `--conv=<id>` → `conversation_id` 명시 (계속 이어지는 스레드).
- `--expect` → `expect_result=true`. 워커 페르소나가 응답을 요구받는 신호.
- `--cc=<id1>,<id2>` → 관찰자 (observer). `delivered_as='cc'`로 전달되며 응답 의무 없음. payload §5.3에 `type="cc-observe"`는 두지 않음 — `delivered_as` 메타가 이미 cc임을 표시. 워커 페르소나가 `cc` 메시지에 자동 응답하지 않도록 §5.1 공통 규약에 명시.
- `--closing` → `closing=true`. 직접 대화 한쪽 종결. 양쪽 모두 closing 보내면 `closed`로 자동 transition (`dispatcher.py:_maybe_close`).
- `--priority=<low|normal|high>` → 큐 정렬용 메타. 디폴트 `normal`. 실제 sort는 수신자가 `/agora-wait --sort=priority`로 켤 때만 활성.
- `--deadline=<iso>` → advisory ISO 8601 deadline. 서버는 검증만, 강제 X.

**inbox_full 에러 처리** — 서버 `dispatcher.dispatch`가 `ValueError("inbox_full: <target> has <N> pending")`을 발생시킬 수 있다. 슬래시 wrapper는 이 메시지를 그대로 사용자에 출력 + "수신자가 wait를 못 따라가고 있습니다. `/agora-wait`로 직접 깨우거나 인스턴스 상태를 확인하세요." 보조 한 줄 추가.

### 4.8 (신규) `/agora-spawn-team <manifest.json> [--dir=<path>] [--launch]`

manifest 파일 한 개로 다수 워커를 일괄 spawn. 어제 Inst1~Inst8 손작업의 짝.

**manifest 스키마** (`templates/team.json.example` 기반, JSON Schema는 `scripts/spawn_team.py`에 내장):

```json
{
  "version": 1,
  "team": [
    {
      "id": "Coder1",
      "role": "coder",
      "description": "프런트엔드 React 코딩 담당. 컴포넌트·훅·상태관리."
    },
    {
      "id": "Reviewer1",
      "role": "reviewer",
      "description": "코드 리뷰 및 PR 코멘트.",
      "preset": "reviewer"
    }
  ]
}
```

- `version`: 정수. 현재 `1`. 미래 호환 필드.
- `team`: 객체 배열. 각 객체는 `/agora-spawn`의 인자 그대로.
  - `id` (필수, 문자열, 영숫자·하이픈·언더스코어만, 1~32자).
  - `role` (필수, 문자열, roles.json 키 또는 임의 — 미정의 role은 §4.1 처리).
  - `description` (필수, 문자열, 한국어 권장).
  - `preset` (선택, 문자열, 미명시 시 role 기반 derive).

**동작**:

1. manifest 파일을 로드·검증 (스키마 + id 중복 + id 형식). 검증 실패 시 abort, 어느 항목이 문제인지 출력.
2. 디렉토리 디폴트는 `/agora-spawn`과 동일 (§4.2의 4단계 결정).
3. 각 항목에 대해 `/agora-spawn`을 차례로 실행. **부분 실패 정책**: 한 항목이 실패하면 직전까지 생성된 디렉토리는 그대로 두고 (롤백 X), 실패 지점 + 나머지 미수행 항목을 사용자에 보고. 사용자가 manifest를 수정 후 재실행하면 이미 만든 디렉토리는 위 §4.2의 "이미 존재" 규칙으로 건너뛰거나 `--force`.
4. **`--launch` 옵션 (Windows 우선)**: 각 spawn 직후 Windows Terminal로 `wt.exe new-tab -d <id> -- claude` 같은 명령으로 자식 탭을 열어 워커를 자동 기동. 디폴트 비활성 (Inst7 디버깅 경로 차단 정신 동일). `--launch=manual`은 안내 문자열만 출력. POSIX는 후속.
5. 종료 시 한국어 요약: "spawn 성공 N건 / 실패 M건. 워커 시작: `claude` 실행 (또는 --launch=auto)."

**미정의 role 처리**: §4.1을 항목별로 적용 (각 항목이 독립). manifest 전체 abort 아님.

### 4.9 (신규) `/agora-close <conversation-id> [--reason="<text>"]`

`agora.close_thread` 래퍼 (`server.py:247`). 자기가 참여한 conversation을 명시적으로 종결. 서버가 다른 primary participant에 `closing=true` payload를 자동 dispatch. 응답 메시지 + 종결 상태를 한국어로 출력.

`--reason`은 closing payload에 들어가 `{type:"closing", from, reason, ts}` 형태로 전달 — §5.3 payload 표준.

## 5. 운영 규약 (preset 공통)

### 5.1 워커 preset 공통 단락

`templates/presets/{coder,reviewer,tester,writer,planner,general}.md` 모두에 공통 포함:

#### Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"`로 forward 가능. 원 발신자에 **"X에게 위임함" 한 줄 acknowledgment 권장** (orphan 방지) — 절대 의무 아님, 페르소나가 자율 판단.

#### wait 진입 규약

Stop hook이 자동으로 `agora.wait(timeout_ms=0)`를 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.

### 5.2 orchestrator preset 별도 단락

`templates/presets/orchestrator.md`:

dispatch는 본업. 사용자 자연어 요청을 받아 적합한 워커를 골라 위임. 모호하면 한 줄로 사용자에 확인 후 dispatch. Stop hook은 박지 않음 (사용자가 깨움). `/agora-target`으로 워커 추천을 받을 수 있으나 최종 발사는 사용자 confirm.

### 5.3 (신규) payload 표준

모든 슬래시 wrapper가 자동 채우는 payload 형식:

```json
{
  "type": "task|reply|closing|ack",
  "from": "<sender-instance-id>",
  "ts":   "<ISO 8601 UTC>",
  "message": "<자연어 본문>",
  "...": "type별 부가 필드"
}
```

**`type` enum 의미**:

| type | 발화 슬래시 | 부가 필드 | 워커 페르소나 처리 |
| ---- | ------------ | --------- | ----------------- |
| `task` | `/invoke`, `/broadcast` (기본) | `message` | 작업 수행 후 `type="reply"` 응답 |
| `reply` | 워커가 명시적으로 만듦 | `message`, `in_reply_to` (envelope 인자로도 동시 전달) | 추가 응답 X (대화 추가 턴 없으면) |
| `closing` | `/invoke --closing`, `/broadcast --closing`, `/agora-close` | `reason` | "확인" ack 외 추가 작업 없음 |
| `ack` | 워커 페르소나 자율 (예: forward 시 원 발신자 통지) | `ack_for: <cmd_id>` | 정보성 — 추가 응답 X |

**envelope 인자 vs payload 필드 — 중복 시 envelope 우선**: `in_reply_to`, `closing`, `conversation_id`, `cc`, `priority`, `deadline_ts`, `reply_to`는 envelope (서버 메타) 인자로 전달되며 payload에 굳이 박지 않는다. payload의 `reason`/`ack_for`/`message`만 자유서술 필드.

이 표준 덕에 Stop hook의 워커 페르소나는 `payload.type`으로 분기 + `payload.message` 일관 키 사용. 어제 Inst2/Inst3가 `payload.action` vs `payload.message`로 갈리던 사고는 차단.

### 5.4 (신규) cc 메시지 처리 규약

워커가 `delivered_as='cc'`인 envelope을 받으면:

- **응답 X** — 페르소나의 forward·reply 규칙이 적용되지 않는다. 관찰자 신호.
- 페르소나의 작업 상태(컨텍스트)에 정보로 흡수만 한다.
- Stop hook은 wait를 계속 부르되, cc 메시지만 받았다면 별도 응답 없이 다음 wait로 진입.

이 규약은 `templates/presets/*.md` 공통 단락에 명시.

### 5.5 (신규) preset 파일 골격

`templates/presets/<role>.md` 일관성을 위한 표준 단락 (한국어):

```markdown
# <역할 이름> 페르소나

## 미션
<1~3문장. 이 역할이 책임지는 핵심 가치.>

## 응답 규약 (공통)
### Forward 규약
<§5.1.Forward 규약 인용 또는 동일 본문.>
### Wait 진입 규약
<§5.1.wait 진입 규약 인용 또는 동일 본문.>
### cc 메시지 규약
<§5.4 인용 — 응답 X, 정보 흡수.>
### payload 표준
<§5.3 type enum 요약 1~2줄.>

## 역할별 지식
<이 role 고유의 도메인 지식. coder = 코드 스타일/도구, reviewer = 리뷰 체크리스트, writer = 문체 가이드 등. 자유 분량.>

## 다른 멤버
<현재 알려진 다른 인스턴스 매핑이 있으면 짧게. 없으면 "agora.instances / agora.find 로 동적으로 확인".>
```

orchestrator preset (`orchestrator.md`)은 "## 미션 / ## 위임 규약 / ## 워커 추천 절차" 같이 위 골격을 부분 적용 + 추가 단락. 워커 preset 7개 (`coder, reviewer, tester, writer, planner, general` + orchestrator)는 모두 한국어로 작성. 어조 한 가지 — "~한다" 평서체. 큐레이션 책임자는 spec 작성자 (Inst1) + Writer 페르소나 검토 (구현 단계, 별도 작업으로 분리 가능).

### 5.6 (신규) 슬래시 에러 응답 정책

서버 도구 호출이 실패할 수 있는 케이스 + 한국어 메시지 표준:

| 케이스 | 발화 슬래시 | 한국어 메시지 |
| ------ | ------------- | -------------- |
| `inbox_full` | `/invoke`, `/broadcast`, `/agora-close` | `[cc-agora] 수신자 <id> 받은편지함이 가득 찼습니다 (N개 대기). 수신자가 wait를 못 따라가는 중입니다.` |
| `NotRegisteredError` | `/invoke`, `/agora-close` | `[cc-agora] 대상 <id>는 현재 등록되어 있지 않습니다. agora.instances로 확인하세요.` |
| `unknown_conversation` | `/agora-close` | `[cc-agora] 대화 <conv>를 찾을 수 없습니다.` |
| `not_a_participant` | `/agora-close` | `[cc-agora] 본인은 대화 <conv>의 참여자가 아닙니다.` |
| manifest 검증 실패 | `/agora-spawn-team` | `[cc-agora] manifest 항목 <i> 검증 실패: <원인>` |
| 이미 존재하는 `<id>/` | `/agora-spawn`, `/agora-spawn-team` | `[cc-agora] '<id>/' 디렉토리가 이미 존재합니다. --force로 덮어쓰기 가능.` |

## 6. 결정 트레일

설계 결정의 동기·근거·반대 의견을 보존 (v3 spec 컨벤션).

### 결정 1: `/agora-target` 자동 dispatch 여부

- **확정**: 비활성. `/agora-target`은 추천만 + `/invoke` chaining (1c).
- **트레일**: 1라운드 워커 의견 — (1a) 3명(Inst5/6/7), (1c) 2명(Inst4/8), (1b) 1명(Inst2). 사용자가 "자동 invoke도 되면 좋겠다" 추가 의견. 2라운드 절충안 의견 — **6명 만장일치 (X1) 디폴트=수동 chaining + `--auto` 플래그 옵트인** (Inst2 갈아탐). 사용자 최종 결정 — 자동 invoke 취소.
- **재도입 트리거**: 운영 중 추천 정확도 누적 측정 + 사용자가 자동 발사 가치를 명확히 인식 시. 재도입 형태는 워커 6명 만장일치로 권장된 **"디폴트 = 수동 chaining, `--auto` 플래그로 자동 옵트인"**. 비추천 대안 — (i) 디폴트를 자동으로 두고 `--draft`/`--dry-run`으로 옵트아웃: 깜빡한 한 번이 silent fire. (ii) 별도 슬래시(`/agora-dispatch-auto` 등)로 분리: 본체와 옵션 표준화가 점차 어긋남, 같은 의도에 슬래시 두 개 표면적 증가. (iii) 인스턴스 수 기반 컨텍스트 분기: 같은 명령이 환경에 따라 다르게 동작 → mental model 깨짐 + 회귀 테스트 어려움. (iv) 추천 신뢰도 임계값 자동: 점수 calibration 부담 + 임계값 자체가 외부 노출 안 돼 디버깅 불가.

### 결정 2: 페르소나 생성 정책

- **확정**: `(2a) 빈 템플릿 default + --preset=<role>로 큐레이션 프리셋 선택`. LLM 자동 초안 비활성.
- **트레일**: Inst6(Writer)이 유일하게 답 — (2c) 프리셋. 자동 LLM 초안(2b)은 일반론·형용사 나열로 빠져 워커 톤이 서로 닮은 평탄한 산문이 됨. 다른 5명은 자기 영역 아니라 자제.

### 결정 3: Hook 정책

- **확정**: (3a) role 기반 자동 분기 + Inst5 보강 — `roles.json` 명시 상수 파일, 미정의 role = hook 미설치 + 경고.
- **트레일**: 4명 (3a), 1명 (3c, Inst7) — Inst7 우려는 "role 분류가 worker/orchestrator 둘만이라는 전제 깨질 위험". 보강 채택으로 차단 — roles.json이 single source of truth, 새 role 추가 = 파일 항목 추가. 사용자가 "확장 가능한 온라인 목록" 명시.
- **추가 안전선**: 플러그인 install 자체에는 hook 없음 — spawn 단위로만 워커 settings.local.json에 박힘 (Inst7의 "spawn 직후 안 멈춤" 디버깅 경로 차단).

### 결정 4: 패키지 위치

- **확정**: AgentAgora 모노레포 안 `plugin/cc-agora/`. Python 서버와 디렉토리만 분리, 같은 git 트리.
- **트레일**: 사용자 직접 확정 (별도 repo 안 함).

### 결정 5: Forward ack 의무

- **확정**: 페르소나 권장, 절대 의무 아님.
- **트레일**: 강제·생략 옵션 중 권장. 사용자 직접 결정.

### 결정 6 (v2): 산출물 한국어 우선

- **확정**: 플러그인 산출물(`commands/*.md`, `templates/presets/*.md`, README, `team.json.example`)을 한국어로 작성. 영어 번역은 일정 시점에 일괄.
- **트레일**: 사용자 직접 결정. 이유 — 본 환경의 운영자/워커 협업이 한국어로 진행되며, 한국어 톤 큐레이션을 1차 산출물로 잡고 검증된 톤을 영어로 옮기는 편이 일반론 평탄화를 피한다 (Inst6 Writer 우려와 같은 정신). 코드/식별자/MCP 도구 이름은 영어 유지.

### 결정 7 (v2): wait_mode 매핑 위치

- **확정**: roles.json은 hook policy만 보관. `wait_mode`는 `scripts/role_policy.py::wait_mode_for(role)`이 derive (§4.1 표).
- **트레일**: 후보 (i) roles.json에 두 필드 — 정합성 사고 위험. (ii) `.mcp.json.template`에 하드코딩 — role 추가 시 두 곳 편집. (iii) derive — 단일 ground truth. 사용자 결정.

### 결정 8 (v2): batch spawn 인터페이스

- **확정**: manifest 파일 (`team.json`). CLI 인자 일괄 미채택.
- **트레일**: 후보 (a) manifest (b) `/agora-spawn-team Coder1=coder ...` CLI 인자 (c) 둘 다. 사용자 (a) 결정. 이유 추정 — 팀 구성이 재현·버전관리 가치가 있고, description 한국어 본문이 CLI 인자로 들어가면 따옴표·공백 escape 부담. manifest는 git에 박혀 변경 이력도 자연스러움.

### 결정 9 (v2): 전체 의회 reset 슬래시 도입 여부

- **확정**: 도입 안 함 (§2 Non-goals 등재).
- **트레일**: 사용자 "의회원 초기화" 의도 명확화 결과 — "팀 일괄 초기 셋업"(=batch spawn)이 본 의미. cleanup은 서버 재시작이 깔끔하고 stale entry는 `dispatcher.dead_session_sweep`이 30분 디폴트로 자동 정리. 재도입 트리거 — 운영 중 stale entry가 wait 미응답으로 노출되는 빈도가 누적되고 서버 재시작 비용이 무거워지는 시점.

### 결정 10 (v2): preset 한국어 작성·골격 정의

- **확정**: §5.5 골격을 표준으로 박음. 7개 preset 모두 한국어 평서체.
- **트레일**: spec v1은 §5.1 공통 단락만 정의, 골격 미정. preset 톤 일관성 보강 위해 v2에서 골격 표준화.

### 결정 11 (v2.1): 슬래시 = user-invokable skill (commands/ → skills/)

- **확정**: 슬래시를 `commands/<name>.md` 평면 파일 대신 `skills/<name>/SKILL.md` 폴더 구조로 구현. `.claude-plugin/plugin.json`을 manifest로 둠.
- **트레일**: v2 spec 초안은 Claude Code 레거시 `commands/` 컨벤션을 가정. 사용자가 "실행 가능한 커맨드는 user-invokable 스킬이다"로 정정. claude-code-guide subagent로 정확한 구조 확인 후 적용 — `skills/<name>/SKILL.md` + `.claude-plugin/plugin.json` 자동 발견 패턴. 슬래시 호출은 `/cc-agora:<name>` namespace prefix 포함.
- **부수 효과**: SKILL.md 본문에서 Bash 도구로 `python scripts/<name>.py $ARGUMENTS`를 호출하는 표준 패턴. 본 spec §4의 슬래시 동작은 그대로 — 구현체만 SKILL.md + Bash + Python script로 매핑.

## 7. 의문점·후속 작업

- **`/agora-target`의 추천 사유 길이**: §4.3 — 인스턴스 수가 적으면 1~3문장, 많으면 1문장. 구현 단계 튜닝.
- **roles.json 위치 우선순위 (cascading)**: 플러그인 디폴트 `config/roles.json` vs 사용자 오버라이드 `~/.claude/cc-agora/roles.json`. 현 단계는 플러그인 디폴트만. cascading은 후속. 재도입 트리거 — 다수 프로젝트에서 role 정의가 갈리는 경우.
- **Observability 슬래시** (`/agora-transcript`, `/agora-coverage`) — server-side P1 도구 도입(어제 brainstorming 결과) 후 클라이언트 래퍼로 추가. 이 spec 외 범위. `agora.conversations_list`/`agora.conversation_status`는 이미 v3 서버에 있으므로 P0 readonly wrapper도 검토 가능 (예: `/agora-threads`) — 단 본 spec엔 미등재.
- **`--launch` POSIX 지원**: 현 단계는 Windows Terminal (`wt.exe`)만. macOS는 `osascript` 또는 `open -na Terminal`, Linux는 `gnome-terminal`/`tmux` 등 — 후속.
- **`/agora-target --auto` 재도입**: §6 결정 1의 권장 형태. 추천 정확도가 누적 검증되면 옵트인 플래그로 재도입.
- **roles.json 자동 편집 보조**: 미정의 role 경고 시 사용자 결정에 따라 자동 추가 슬래시(`/agora-roles add <role>`?) — 후속.
- **영어 번역 시점·범위**: 결정 6 단서 — 본격 외부 공개나 사용자 외 합류자가 늘어나는 시점에 일괄. 코드 식별자는 영어 유지 중이므로 마이그레이션 범위 = 한국어 본문 텍스트만.
- **영속화 관련 슬래시 미정**: v3는 SQLite 백업·재시작 복구를 dispatcher가 자동 수행. 명시적 dump/restore 슬래시는 운영 빈도 낮아 본 spec 외.

## 8. 구현 우선순위 (writing-plans 인풋)

1. **기반** — `config/roles.json` + `scripts/role_policy.py` (`wait_mode_for`, `hook_for`, `preset_for`, 미정의 role 처리).
2. **템플릿** — `templates/mcp.json.template` (Wait-Mode + Wait-Timeout-Ms 헤더 포함), `settings.local.json.template`, `stop-hook.py` 본문, `team.json.example` (한국어 description).
3. **payload 표준** — `scripts/payload.py` (`type` enum, `make_payload(type, from, message=..., reason=..., ack_for=...)`).
4. **preset 7개 (한국어, §5.5 골격)** — orchestrator/coder/reviewer/tester/writer/planner/general. 큐레이션 검토 별도 작업으로 분리 가능.
5. **spawn 본체** — `scripts/spawn.py` (`/agora-spawn` 1개 단위) + `scripts/spawn_team.py` (manifest 로더 + 부분 실패 보고).
6. **통신 슬래시 9개** (`skills/<name>/SKILL.md`, 한국어 본문 + 영어 frontmatter): `agora-spawn`, `agora-spawn-team`, `agora-target`, `agora-wait`, `agora-unwait`, `agora-rewait`, `agora-close`, `broadcast`, `invoke`. `/agora-target`이 가장 복잡(agora.find + LLM 매칭), 나머지는 thin wrapper — 본문에서 Bash 도구로 `python scripts/<name>.py $ARGUMENTS` 호출. `.claude-plugin/plugin.json` manifest 동시 작성.
7. **README (한국어)** + `team.json.example` + 실제 사용 시나리오 1개 (예: "Coder1 + Reviewer1 셋업 → orchestrator가 작업 분배").
8. **통합 테스트**:
   - 골든 패스: spawn → 워커 시작 → broadcast 수신 → `/invoke`로 응답.
   - manifest 일괄: 3명 spawn-team → 동시 등록 → orchestrator의 `/agora-target` → 매칭 → `/invoke` → 응답.
   - 부분 실패: manifest 한 항목 id 중복 → 검증 단계 abort, 어떤 디렉토리도 생성 X.
   - 미정의 role: spawn 진행 + hook 미설치 + stderr 경고 + 워커는 정상 등록.
   - hook 충돌: 기존 `settings.local.json`이 다른 hook을 갖고 있을 때 `--force` 없이는 fail, `--force`로 덮어쓰기.
   - 같은 instance_id 중복 spawn: 디렉토리 존재 → fail, `--force`로 덮어쓰기.
   - `/agora-unwait` + `/agora-rewait` 왕복: .bak 생성/복원 정확.
   - `/agora-close`: 두 참여자 conversation 종결 후 양쪽 closed_by에 등재, `agora.conversation_status`가 `status='closed'` 보고.

## 9. (v2 신규) 본 spec의 자기 모순·구현 시 충돌 가능 지점

리뷰 시 점검할 자체 약점. 구현 단계에서 마지막으로 점검.

- **9.1 `/agora-target`의 chaining UX 가정**: §4.3은 "Claude Code 슬래시가 다음 입력을 자동 prefill 하는 표준 메커니즘은 없다"고 전제하고 사용자 수동 복사를 가정. 실제로 Claude Code가 슬래시 응답을 prefill 하는 메커니즘이 있다면 spec 본문 갱신 필요. 구현 진입 직전 한 번 더 확인.
- **9.2 `--launch=auto`의 Windows Terminal 의존**: `wt.exe`가 설치돼 있지 않은 환경에서 fail. `wt.exe`가 PATH에 없으면 `--launch=manual`로 자동 강등 + 안내 — 명세에 박을지 옵션.
- **9.3 `roles.json` 단일 위치 가정 vs `--dir` 비표준 cwd**: 임의 `--dir`에서 spawn한 워커가 같은 `roles.json`을 참조하므로 OK이지만, manifest가 다른 위치에서 실행되면 어떤 `roles.json`이 적용되는지 우선순위는 §4.1·§4.2에서 도출됨 (플러그인 디폴트 `config/roles.json` 한 곳).
- **9.4 manifest 부분 실패 후 재실행 UX**: 디폴트로 생성된 디렉토리는 두 번째 실행에서 "이미 존재" 에러로 막힘. 사용자 경험상 "남은 항목만 이어 spawn" 모드가 필요할 수 있음 (`--resume`?). 본 spec 미등재 — 운영 빈도 보고 후속.
- **9.5 payload `type=ack`의 발화 주체 모호**: §5.3 표는 "워커 페르소나 자율"이라 했지만, 명시적 슬래시는 없음. forward 시 원 발신자 통지가 진짜 자주 일어나면 `/ack <cmd_id>` 슬래시 도입 검토.
- **9.6 cc 메시지의 `agora.wait` 노출**: `delivered_as='cc'`도 `agora.wait`로 같이 드레인된다 (`dispatcher.py:495` — 필터 없음). 워커가 cc/primary를 envelope 메타로 구분해야 함 — §5.4 규약이 이를 가정하지만, 메시지가 한꺼번에 도달하면 페르소나가 둘을 묶어 처리할 위험. 워커 페르소나에 "envelope.delivered_as 검사" 한 줄 추가 명시.
