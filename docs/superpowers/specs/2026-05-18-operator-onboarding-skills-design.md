# 운영자 온보딩 스킬 설계 — `agora-design-worker` · `agora-setup`

> 2026-05-18. `cc-agora-ops`에 인터랙티브 운영자 스킬 2종을 추가한다. 기존
> `agora-spawn`·`agora-spawn-team`·7개 페르소나 플러그인·`roles.json`은 무변경.

## 1. 배경 / 동기

현 `agora-spawn`은 `<role>`을 `config/roles.json`에서 조회해 7개 사전 정의 페르소나
플러그인(`cc-agora-coder`·`cc-agora-reviewer` …) 중 하나를 워커에 활성화한다. 워커의
페르소나가 항상 그 7개 중 하나로 고정된다 — 팀에 맞춘 새 역할을 세우려면 페르소나
플러그인을 손수 추가해야 한다.

또한 AgentAgora 배치를 처음 세울 때 운영자가 해야 할 일(포트·TLS 등 서버 설정, 생성
예정 에이전트 계획, 등록할 스키마, comm-matrix·file-policy 권한)이 흩어져 있어, 한
번에 안내하는 진입점이 없다.

두 인터랙티브 스킬을 추가한다:

- **`agora-design-worker`** — 운영자와 대화하며 **커스텀 페르소나**를 공동 작성하고
  워커 디렉토리를 스캐폴딩한다. 7개 사전 정의에 매이지 않는다.
- **`agora-setup`** — AgentAgora 배치 전체를 한 번에 부트스트랩하는 end-to-end 스킬.
  서버 설정·스키마·권한을 정하고, 계획된 각 에이전트마다 `agora-design-worker`를
  돌려 워커까지 생성한다.

두 스킬 모두 `agora-make-comm-matrix`처럼 백킹 스크립트 없이 SKILL.md 본문이 절차인
대화형 스킬이다(`disable-model-invocation: true`). 워커 디렉토리 스캐폴딩의 기계적
부분만 기존 `spawn.py`를 재사용한다.

## 2. `agora-design-worker`

### 2.1 인터페이스

```
/cc-agora-ops:agora-design-worker [<id>] [--dir=<path>] [--force] [--server-url=<url>]
```

- `<id>` (선택) — 워커 instance_id. 생략 시 대화 첫 질문으로 묻는다. `agora-setup`이
  호출할 때는 로스터에서 받은 id를 넘긴다.
- `--dir` / `--force` / `--server-url` — `agora-spawn`과 동일 의미.

### 2.2 대화 (한 번에 한 질문)

1. **워커 id** — `<id>` 미지정 시에만.
2. **미션** — 이 워커가 받은 입력을 무엇으로 바꾸는가. 핵심 책임 한두 문장.
3. **역할 라벨** — `.mcp.json`·헤더에 쓸 짧은 역할 단어(예: `db-migrator`).
4. **작업 스타일·역할별 지식** — 구체적 운용 규칙. 7개 페르소나의 "Role-specific
   knowledge" 불릿에 해당하는 내용.
5. **handoff 규약 세부** — 도메인 밖 작업을 forward하는가, 기본 위임 대상이 있는가.

공통 응답 규약 — **Response conventions**(forward / flush entry / cc message /
payload standard)와 **Finding other members** — 은 7개 페르소나에 글자 그대로 동일한
보일러플레이트다. 질문하지 않고 스킬이 자동 스탬프한다.

루트 `CLAUDE.md`에 들어갈 **한 줄 책임**은 미션(2단계) 답변에서 한 문장으로 뽑아
쓴다. `agora-setup`이 호출할 때는 로스터 항목의 한 줄 책임을 그대로 쓴다.

대화 후 작성된 페르소나 전문을 운영자에게 보여주고 확인을 받은 뒤 스캐폴딩한다.

### 2.3 산출 — 워커 디렉토리 `<parent>/<id>/`

| 파일 | 내용 | 출처 |
| --- | --- | --- |
| `CLAUDE.md` (루트) | thin 정체성 — id, 한 줄 책임, 통신 안내 | 기존 `_render_thin_claude_md` 변형 |
| `.claude/CLAUDE.md` | 공동 설계한 페르소나 전문(Mission / Response conventions / Role-specific knowledge / Finding other members) | 신규 |
| `.mcp.json` | 2-서버 채널 템플릿 | 기존 `mcp.json.template` (불변) |
| `run.bat` | 채널 모드 런처 | 기존 (불변) |
| `.claude/settings.local.json` | `cc-agora`(통신 코어)만 활성화 — **페르소나 플러그인 없음** | 기존 변형 |

- `<worker>/.claude/CLAUDE.md`는 Claude Code가 프로젝트 메모리로 자동 로드한다
  (공식 문서: 프로젝트 지침은 `./CLAUDE.md` 또는 `./.claude/CLAUDE.md`). 루트
  `CLAUDE.md`와 함께 컨텍스트로 concatenate된다.
- `settings.local.json`은 커스텀 워커엔 활성화할 페르소나 플러그인이 없으므로
  `enabledPlugins`에 `cc-agora@agentagora: true`만 둔다. (7개 페르소나 플러그인은
  `cc-agora`에 의존하므로 기존 spawn은 페르소나 플러그인만 켜도 `cc-agora`가 따라
  켜졌다 — 커스텀 워커는 `cc-agora`를 직접 켠다.)

### 2.4 스캐폴딩 — `spawn.py` 커스텀 모드

`spawn.py`의 `do_spawn`에 선택 인자 `persona_body: str | None = None`을 추가한다.

- `persona_body`가 `None`(현 동작) — 기존 그대로. `roles.json` 조회 → 페르소나
  플러그인 활성화. `.claude/CLAUDE.md` 미생성.
- `persona_body`가 주어짐(커스텀 모드) — `roles.json` 조회를 건너뛴다. `.claude/
  CLAUDE.md`에 `persona_body`를 쓰고, `settings.local.json`은 `cc-agora`를
  활성화하며, 루트 `CLAUDE.md`는 페르소나 플러그인 대신 `.claude/CLAUDE.md`를
  가리키는 thin 본문을 쓴다.

`agora-design-worker` 스킬은 대화로 페르소나 전문을 작성한 뒤 그 텍스트를 넘겨
`spawn.py`를 커스텀 모드로 호출한다. `.mcp.json` 렌더링·디렉토리 캐스케이드·JSON
self-check 등 기계적 로직은 그대로 재사용한다.

## 3. `agora-setup`

### 3.1 인터페이스

```
/cc-agora-ops:agora-setup [--dir=<path>]
```

- `--dir` (선택) — 배치 루트. 기본 `$CWD`. `.agentagora/`·`run-server.bat`·워커
  디렉토리가 모두 이 아래 생긴다.

### 3.2 절차 (스킬 본문이 순서대로 진행)

1. **서버 설정** — 운영자에게 묻는다: 포트(기본 8420), TLS 사용 여부,
   wait-timeout 값 또는 `--no-timeout`, `--restore` 여부, `AGORA_ADMIN_TOKEN`
   설정 여부. → `$CWD/run-server.bat`을 선택한 플래그로 기록한다(admin 토큰 선택
   시 bat에 `set AGORA_ADMIN_TOKEN=...` 포함).

2. **SessionStart 훅** — 운영자 선택:
   - **건다** — `$CWD/.claude/settings.json`에 `SessionStart` 훅을 추가해 Claude
     Code 세션 시작 시 서버를 detached로 자동 기동한다. 훅은 idempotent —
     해당 포트가 이미 떠 있으면 다시 띄우지 않는다.
   - **건너뛴다** — 운영자가 `run-server.bat`을 수동 실행한다.

3. **에이전트 로스터** — 생성 예정 에이전트 목록을 수집한다(각 항목: id + 한 줄
   책임). 이후 4·5·6단계의 입력이다.

4. **스키마** — 운영자가 깊이를 고른다:
   - **경량 대화** — 스키마 이름·용도·주요 필드만 묻고 최소 JSON Schema body 생성.
   - **전체 설계** — 메시지 타입별 필드 타입·필수 여부·제약까지 상세 설계.
   - **파일만 초기화** — 빌트인을 안내하고 빈 `schemas.jsonl`만 준비. 커스텀
     스키마는 워커·봇이 런타임에 등록.

   결과를 서버가 시작 시 로드하는 형식으로 `$CWD/.agentagora/schemas.jsonl`에 쓴다.

5. **권한** — 3단계 로스터를 기반으로:
   - **comm-matrix** — `agora-make-comm-matrix`와 같은 토폴로지 선택(hub-and-spoke
     / all-allow / custom)으로 `(N+1)×(N+1)` CSV(`*` fallback 행/열 포함)를
     `$CWD/.agentagora/comm-matrix.csv`에 쓴다.
   - **file-policy** — 에이전트별 r/w gitignore 패턴(`{"r":[...],"w":[...]}`)을
     `$CWD/.agentagora/file-policy.json`에 쓴다. 누락 차원 기본값은 비대칭 —
     `r` 누락은 전체 허용, `w` 누락은 전체 비허용.

6. **에이전트 생성** — 로스터 각 항목마다 `agora-design-worker` 흐름을 돌린다 —
   id와 한 줄 책임은 로스터에서 받고, 페르소나 대화(2.2의 2~5단계: 미션·역할
   라벨·작업 스타일·handoff)를 수행한 뒤 워커 디렉토리를 스캐폴딩한다.

### 3.3 산출 위치

| 산출물 | 위치 |
| --- | --- |
| `run-server.bat` | `$CWD/` |
| SessionStart 훅 | `$CWD/.claude/settings.json` (2단계에서 "건다" 선택 시) |
| `schemas.jsonl` · `comm-matrix.csv` · `file-policy.json` | `$CWD/.agentagora/` |
| 워커 디렉토리 | `$CWD/<id>/` |

`.agentagora/` 기본 위치는 서버가 `--dir` 아래에서 시작 시 로드하는 바로 그
디렉토리다 — `agora-setup`을 배치 루트에서 실행하면 산출물이 서버 로드 위치에
바로 떨어진다.

### 3.4 SessionStart 훅 동작

훅은 장수명 서버를 블로킹으로 띄우면 세션이 멈추므로, **detached로 기동하고 즉시
반환**한다(Windows: `start`로 별 창/백그라운드 기동). 또 **idempotent** — 기동 전
대상 포트가 이미 바인딩돼 있는지 확인하고, 떠 있으면 새로 띄우지 않는다. 구체적
훅 커맨드·포트 점검 방식은 구현 플랜에서 확정한다.

## 4. 비목표 (YAGNI)

- 기존 `agora-spawn`·`agora-spawn-team`·7개 페르소나 플러그인·`roles.json` 변경 —
  무관, 그대로 둔다.
- 커스텀 페르소나를 재사용 가능한 플러그인으로 승격 — 커스텀 페르소나는 워커
  디렉토리에 일회성으로 산출한다. 재사용 카탈로그는 7개 플러그인이 담당한다.
- 실행 중 서버 생명주기 관리(stop·restart 오케스트레이션) — `agora-setup`은
  선택적 SessionStart 기동까지만 다룬다.
- GUI·웹 UI — 두 스킬 모두 터미널 대화.

## 5. 구현 분할

독립 머지 가능한 플랜 2개. `agora-design-worker`가 `agora-setup`이 호출하는 재사용
단위이므로 먼저 구현한다.

- **Plan 1 — `agora-design-worker`**: `spawn.py` 커스텀 모드(`persona_body` 인자)
  + 커스텀 모드 산출물 테스트 + `agora-design-worker/SKILL.md` + `cc-agora-ops`
  README 갱신. 단독으로 동작·유용하다.
- **Plan 2 — `agora-setup`**: `agora-setup/SKILL.md`(6단계 절차) + SessionStart
  훅 커맨드·포트 점검 + `run-server.bat` 렌더링 + README 갱신. Plan 1의
  `agora-design-worker`를 6단계에서 호출한다.

## 6. 테스트

- `spawn.py` 커스텀 모드 — `persona_body` 지정 시 `.claude/CLAUDE.md`가 그
  내용으로 생성되고, `settings.local.json`이 `cc-agora`를 활성화하며 페르소나
  플러그인을 켜지 않음을 검증. 기존 모드(`persona_body=None`) 회귀 불변.
- `run-server.bat` 렌더링 — 선택 플래그(포트·`--no-tls`·`--no-timeout`·
  `--restore`)가 정확히 반영되는지.
- SessionStart 훅 — 포트 점검 분기(떠 있음 → 미기동 / 비어 있음 → detached 기동).
- SKILL.md 2종 — frontmatter 유효성, 플러그인 스킬 디스커버리.
