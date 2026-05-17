# Claude Code 플러그인 (cc-agora)

AgentAgora는 Claude Code 플러그인 생태계를 통해 슬래시 명령으로 워커 간 통신과 팀 운용을 지원한다. 플러그인은 세 종류로 나뉜다: 통신 코어(`cc-agora`), 운영자 도구(`cc-agora-ops`), 역할 페르소나(7종). 이 문서는 각 플러그인의 역할과 슬래시 명령, 설치 방법, 워커 생성 경로를 설명한다.

---

## 1. 플러그인 생태계 개요

| 종류 | 플러그인 | 용도 |
|------|----------|------|
| 통신 코어 | `cc-agora` | 모든 워커에 활성화. 메시지 dispatch·broadcast·종결 슬래시와 운용 규칙 참조 스킬. |
| 운영자 도구 | `cc-agora-ops` | 운영자 세션에 활성화. 워커 spawn·팀 설정·대시보드. `cc-agora`에 의존. |
| 역할 페르소나 | `cc-agora-coder` 외 6종 | 워커별 역할 성격을 정의. 각각 `cc-agora`에 의존. |

---

## 2. `cc-agora` — 통신 코어

모든 AgentAgora 워커에 활성화하는 기반 플러그인이다. 워커 간 메시지 발송·수신·종결에 필요한 슬래시 명령과 운용 규칙 참조 스킬을 제공한다.

### 슬래시 명령

| 슬래시 | 시그니처 | 동작 |
|--------|----------|------|
| `/cc-agora:invoke` | `<id> "<message>" [옵션...]` | 지정한 워커에 task를 dispatch한다. payload 자동 채움 및 envelope 분리를 처리한다. |
| `/cc-agora:broadcast` | `"<message>" [옵션...]` | 등록된 모든 워커에 fan-out 발송한다. announcement나 세션 종료 신호에 사용한다. |
| `/cc-agora:agora-target` | `"<task>"` | `agora.find`로 최적 워커를 추천한다. chaining 문자열만 제안하며 직접 발사하지는 않는다. |
| `/cc-agora:agora-close` | `<conversation-id> [--reason="<text>"]` | conversation을 명시적으로 종결하고, 참여 워커에 `type=closing` payload를 자동 dispatch한다. |
| `/cc-agora:agora-run-script` | `[<dir>]` | 지정한 디렉토리(기본 CWD)에 OS에 맞는 채널 모드 실행 스크립트(`run.ps1`/`run.sh`)를 생성한다. |

### `agora-protocol` 참조 스킬

`/cc-agora:agora-protocol`은 채널 모드 워커의 운용 규칙을 담은 참조 스킬이다. 워커가 채널 알림으로 깨어나 `agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신하는 루프를 기술한다. 등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/`agora.unregister`를 명시적으로 호출하지 않는다.

워커의 채널 모드 동작 방식은 [`docs/channel-mode.md`](channel-mode.md)에 상세히 설명돼 있다.

---

## 3. `cc-agora-ops` — 운영자 도구

운영자(orchestrator) 세션에 활성화하는 플러그인이다. 워커 spawn, 팀 일괄 설정, 통신 매트릭스 관리, 배치 전체 부트스트랩을 담당한다. `cc-agora`에 의존한다.

### 슬래시 명령

| 슬래시 | 시그니처 | 동작 |
|--------|----------|------|
| `/cc-agora-ops:agora-spawn` | `<id> <role> "<description>" [옵션...]` | 7개 사전 정의 페르소나 중 하나로 워커 1명을 채널 모드로 스캐폴딩한다(`CLAUDE.md`, `.mcp.json`, `run.bat`, `settings.local.json` 생성). |
| `/cc-agora-ops:agora-spawn-team` | `<manifest.json> [옵션...]` | manifest JSON으로 팀 전체를 일괄 spawn한다. 부분 실패 시 순차 abort한다. |
| `/cc-agora-ops:agora-comm-matrix` | `[<csv-path>] [--server-url]` | 서버의 통신 매트릭스를 조회(GET) 또는 교체(POST)한다. admin 토큰 보호 엔드포인트를 사용한다. |
| `/cc-agora-ops:agora-make-comm-matrix` | `[<out-path>]` | 라이브 등록 인스턴스 목록을 기반으로 통신 매트릭스 CSV를 생성한다. 토폴로지(hub-and-spoke / all-allow / custom)를 선택해 N×N CSV를 만든다. |
| `/cc-agora-ops:agora-dashboard` | `[--server-url]` | 팀 현황 대시보드를 브라우저로 연다. |
| `/cc-agora-ops:agora-design-worker` | `[<id>] [옵션...]` | 운영자와 대화해 커스텀 페르소나를 공동 작성하고 워커를 스캐폴딩한다. 7개 사전 정의 페르소나에 없는 팀 고유 역할을 만들 때 사용한다. 페르소나 전문은 `.claude/CLAUDE.md`에 저장된다. |
| `/cc-agora-ops:agora-setup` | `[--dir]` | AgentAgora 배치 전체를 한 번에 부트스트랩한다. 서버 기동 스크립트·스키마·권한·워커 로스터를 순차적으로 설정한다. 각 에이전트는 `agora-design-worker`로 생성된다. |

---

## 4. 역할 페르소나 플러그인 (7종)

각 페르소나 플러그인은 `cc-agora`에 의존하며, 특정 워커 역할에 맞는 성격과 운용 지침을 제공한다. `agora-spawn`이 워커를 scaffold할 때 `settings.local.json`에 해당 페르소나 플러그인을 활성화한다.

| 플러그인 | 역할 |
|----------|------|
| `cc-agora-coder` | task를 최소·검토 가능한 코드 변경으로 구현하는 코더. |
| `cc-agora-reviewer` | diff를 검토해 정확성·가독성·테스트 커버리지 이슈를 지적하는 리뷰어. |
| `cc-agora-tester` | 황금 경로·엣지 케이스·회귀 시나리오를 커버하는 테스트를 작성·실행하는 테스터. |
| `cc-agora-writer` | 구체적 예시가 있는 문서와 산문을 작성하는 문서 작성자. |
| `cc-agora-planner` | 목표를 의존성·수용 기준·워커 배정이 있는 순서화된 task로 분해하는 플래너. |
| `cc-agora-orchestrator` | 사용자 요청을 적절한 워커에 위임하는 팀 PM. |
| `cc-agora-general` | task를 직접 처리하거나 전문가에게 forward하는 제너럴리스트 폴백 워커. |

---

## 5. 설치

플러그인들은 Claude Code 플러그인 마켓플레이스로 배포된다. 마켓플레이스 저장소는 `https://github.com/JuyeongYi/AgentAgora-ClaudePlugins`다.

설치 절차:

1. **마켓플레이스 등록** — Claude Code 설정에서 위 저장소를 추가 마켓플레이스로 등록한다.
2. **플러그인 설치** — 마켓플레이스에서 `cc-agora`(통신 코어)를 설치한다. 운영자 세션에는 `cc-agora-ops`도 함께 설치한다. 워커에 페르소나를 부여할 때는 해당 `cc-agora-<role>` 플러그인을 설치한다.

`agora-spawn`으로 생성된 워커는 `.claude/settings.local.json`에 `extraKnownMarketplaces`와 `enabledPlugins`가 자동으로 설정돼 있어 플러그인을 별도로 수동 활성화하지 않아도 된다.

사전 조건:

- Python 3.13+, `agent_agora`가 `pip install -e .` 또는 `uv tool install .`로 설치돼 있어야 한다.
- AgentAgora MCP 서버가 실행 중이어야 한다 (기본 `http://127.0.0.1:8420/mcp`).
- Claude Code v2.1.80+ (채널 모드 사용 시).

---

## 6. 워커 생성 경로

워커를 만드는 방법은 세 가지다. 상황에 따라 적합한 경로를 선택한다.

### 6-1. `agora-spawn` — 사전 정의 페르소나로 워커 생성

7개 페르소나 중 하나를 골라 워커를 빠르게 scaffold하는 방법이다.

```
/cc-agora-ops:agora-spawn Coder1 coder "React 컴포넌트 담당."
```

생성 파일:

| 파일 | 내용 |
|------|------|
| `CLAUDE.md` | 역할·책임을 기술하는 thin 인스턴스 설명 |
| `.mcp.json` | AgentAgora HTTP 서버 + agora-channel stdio 어댑터 2-서버 구성 |
| `run.bat` | 채널 모드 기동 스크립트 |
| `.claude/settings.local.json` | 페르소나 플러그인 활성화 설정 |

워커를 기동할 때는 생성된 `run.bat`(또는 `run.ps1`/`run.sh`)을 워커 디렉토리 안에서 실행한다. 채널 모드 동작 원리는 [`docs/channel-mode.md`](channel-mode.md)를 참고한다.

### 6-2. `agora-design-worker` — 커스텀 페르소나 공동 설계

팀 고유 역할이 필요할 때 운영자와 대화해 커스텀 페르소나를 공동 작성하고 워커를 scaffold한다. 7개 사전 정의에 없는 역할(예: `db-migrator`, `api-gateway-admin`)을 새로 만들 수 있다.

```
/cc-agora-ops:agora-design-worker DbMigrator
```

스킬이 순서대로 질문한다: ① 미션(핵심 책임), ② 역할 라벨, ③ 작업 스타일·도메인 지식, ④ handoff 규약. 공통 응답 규약은 자동으로 삽입된다. 작성된 페르소나 전문을 운영자가 확인하면 스캐폴딩이 진행된다.

커스텀 워커의 페르소나 전문은 `.claude/CLAUDE.md`에 저장되고, `.claude/settings.local.json`은 `cc-agora` 통신 코어만 활성화한다(별도 페르소나 플러그인 없음).

### 6-3. `agora-setup` — 배치 전체 부트스트랩

처음 AgentAgora 팀을 구성할 때 서버 설정부터 모든 워커 생성까지 한 번에 안내하는 end-to-end 스킬이다.

```
/cc-agora-ops:agora-setup
```

진행 순서:

1. **서버 설정** — 포트·TLS·timeout·admin 토큰 등을 묻고 서버 기동 스크립트(`run-cc-agora.ps1`/`run-cc-agora.sh`)를 생성한다.
2. **에이전트 로스터** — 생성할 에이전트 목록(id + 한 줄 책임)을 수집한다.
3. **스키마** — 메시지 스키마를 설계하거나 빈 `schemas.jsonl`을 초기화한다.
4. **권한** — 통신 매트릭스(comm-matrix.csv)와 파일 접근 정책(file-policy.json)을 설정한다.
5. **에이전트 생성** — 로스터 각 항목마다 `agora-design-worker` 흐름을 실행해 워커 디렉토리를 생성한다.

완료 후 기동 순서를 안내한다: `run-cc-agora`로 서버를 먼저 띄우고, 서버가 뜬 것을 확인한 뒤 각 워커 디렉토리의 실행 스크립트를 실행한다.

---

## 참고

- [`docs/channel-mode.md`](channel-mode.md) — 채널 모드 워커 배선·동작 흐름 상세
- [`plugin/cc-agora/`](../plugin/cc-agora/) — 통신 코어 플러그인 소스
- [`plugin/cc-agora-ops/`](../plugin/cc-agora-ops/) — 운영자 도구 플러그인 소스
- [`plugin/personas/`](../plugin/personas/) — 7개 역할 페르소나 플러그인 소스
