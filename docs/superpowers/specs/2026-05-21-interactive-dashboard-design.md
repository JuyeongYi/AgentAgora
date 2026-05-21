# Interactive Dashboard — 운영자 dispatch + 드릴다운 (설계)

- 작성일: 2026-05-21
- 상태: 설계 작성 → 유저 검토 대기
- 관련: `src/agent_agora/dashboard_routes.py`, `src/agent_agora/dashboard.html`, `src/agent_agora/envelope.py`, `src/agent_agora/registry.py`, `src/agent_agora/comm_matrix.py`, `src/agent_agora/sweeper.py`, `src/agent_agora/dispatcher.py`

## 1. 배경 / 문제

현재 대시보드는 읽기 전용 — 운영자(사람)는 워커들의 상태를 볼 수만 있고 직접 메시지를 보내거나 워커가 들고 있는 in-flight 메시지·대화 thread를 들여다볼 수 없다. 운영자는 각 워커의 CLI 탭을 왔다갔다 하면서 작업하는데, 특정 워커에 한 줄 지시하거나 전체에 공지하려면 우회 경로(워커 탭에서 직접 타이핑·다른 워커가 broker로 dispatch)밖에 없다.

추가 누락:
- 대화/메시지의 본문이 보이지 않음 — `dispatcher`가 보관 중인 envelope 페이로드 가시화 불가.
- 워커별 인박스 내용 모름 — 큐 길이는 알지만 무엇이 들어있는지 모름.
- 운영자가 여러 명일 수 있음 (팀 운영) — 현재는 단일 유저 가정.
- 원격 접근(다른 PC·모바일)이 필요해질 수 있음 — 데스크탑 GUI는 부적합, 웹 유지가 정답.
- 폴링 갱신(3초)은 느리고 낭비 — 푸시가 자연스러움.
- 무인증 운영은 원격 접근에서 위험 — 토큰 인증 필요.

## 2. 목표 / 비목표

**목표**
- 운영자가 대시보드 UI에서 **(a) 특정 워커에 직접 dispatch, (b) 여러 워커에 broadcast, (c) 답변 수신**.
- **드릴다운**: 대화 행 클릭 → 메시지 thread, 워커 행 클릭 → 그 워커의 현재 인박스 (모두 envelope 본문 포함).
- **다중 운영자** — username 기반의 per-user pseudo-instance, 운영자별 inbox 분리.
- **인증 미들웨어 swap-ready + MVP에서 `trust`·`token` 두 모드 구현** — 토큰 모드로 원격 운영 즉시 가능. 추가 모드(basic·OIDC)는 backlog.
- **SSE 푸시 갱신** — 폴링 제거, EventSource 기반 즉시 반영. SSE 실패 시 폴링 fallback.
- **서버 헬스 메트릭** — uptime·SQLite 크기·dispatcher write queue·sweeper 실행 통계를 대시보드에 노출.
- 원격 접근 친화 (서버 바인딩·인증·TLS 분리 가능).

**비목표**
- 워크플로 파이프라인 시각화 (backlog).
- 정렬·필터 외의 검색 엔진 (backlog).
- 파일 스토어 뷰 (backlog).
- basic/OIDC 인증 (MVP는 trust·token 두 모드. 나머지는 backlog).
- 운영자 액션(대화 close·워커 unregister·comm-matrix UI 편집) (backlog).
- 기존 단일 파일 `dashboard.html`의 self-contained 속성 (vendored 라이브러리 도입으로 단일 파일은 불가하나 외부 의존은 0 유지).

## 3. 아키텍처 개요

```
[ 웹 브라우저 ]                       [ AgentAgora 서버 ]

  dashboard.html (shell)              dashboard_routes.py
   ├─ login modal ─────────────────┐  ├─ /dashboard (HTML shell)
   │                               │  ├─ /dashboard/static/* (StaticFiles)
   ├─ 헤더(health 카드)            │  ├─ /dashboard/data (snapshot+health)
   ├─ 인스턴스/대화/봇 표           │  ├─ /dashboard/stream (SSE)
   ├─ comm-matrix SVG               │  ├─ /dashboard/dispatch ────┐
   ├─ 운영자 인박스 패널            │  ├─ /dashboard/broadcast    │  → dispatcher
   ├─ dispatch 모달                 │  ├─ /dashboard/operator/    │
   ├─ 드릴다운 모달                 ├──┤   inbox + ack            │
   │                               │  ├─ /dashboard/conversation/{id}
   ├─ api.js (HTTP wrapper)         │  ├─ /dashboard/instance/{id}/inbox
   └─ stream.js (EventSource) ──────┘  ├─ /dashboard/schemas
       (Authorization Bearer            └─ /dashboard/auth-mode
        + X-Agora-Operator-User                ↑
        자동 첨부)                    auth middleware (trust|token)
                                              ↓
                                      dashboard_events.py (SSE pub/sub)
                                      dashboard_health.py (metrics 수집)
                                      instance_registry
                                       ├─ 워커 인스턴스
                                       └─ operator:<username> ← lazy 등록
                                      comm_matrix (operator bypass)
                                      sweeper (operator 면제)
                                      envelope (reply_only 필드)
                                      dispatcher (event hooks)
```

## 4. 서버 측 변경

### 4.1 Pseudo-instance `operator:<username>`

- 네임스페이스: `operator:` 접두사로 워커 instance_id와 분리. e.g. `operator:alice`.
- **Lazy 등록**: 운영자의 첫 dispatch/inbox 호출 시 `instance_registry.register()` 자동 호출. `session_id`는 `dashboard:<username>`처럼 고유 마커.
- **Sweeper 면제**: `sweeper.py`의 dead-session GC가 `operator:` 접두사를 만나면 skip — TTL 무관.
- **comm-matrix 면제**: `comm_matrix.py`의 dispatch 허용 체크에서 `from.startswith("operator:") or to.startswith("operator:")`면 무조건 allow (matrix 활성 여부와 무관).
- `agora.instances` 결과에 operator도 포함 (워커 입장에서 보임 — broadcast 대상이 될 수 있고, 누가 메시지 보냈는지 추적 가능).

### 4.2 Envelope `reply_only: bool = False`

- `envelope.py`의 envelope 스키마(dataclass + 검증)에 optional `reply_only: bool` 필드 추가, default `False`.
- 직렬화·영속화·전달에 포함. 서버는 파싱·전달만 — **강제는 안 함**.
- 위반 시 dashboard 대화 thread에서 답신 sender가 다른 인스턴스로 나타나 가시화됨.
- `agora-protocol` 스킬에 한 줄 추가: "envelope.reply_only가 true면 forward 금지, sender에게만 답신". 강제는 워커 자율.

### 4.3 인증 미들웨어 (`dashboard_auth.py` 신규)

Starlette middleware. 모든 신규 dashboard 엔드포인트(+ 기존 `/dashboard/data`)가 이 middleware를 거침.

**`request.state.operator_user`를 항상 채움.** 비채워지면 401.

**모드 환경변수 `AGORA_DASHBOARD_AUTH_MODE`** — MVP는 두 모드 모두 구현:

- `trust` (기본): `X-Agora-Operator-User` 헤더 값을 그대로 신뢰. 빈 값 → 401. 로컬·신뢰 LAN 운영용.
- `token`: `Authorization: Bearer <token>` 검증. 환경변수 `AGORA_DASHBOARD_TOKENS`에 `user1:token1,user2:token2` 매핑. 매칭되면 username을 결정. 매칭 안 되면 401. **token에서 도출한 username이 X-Agora-Operator-User 헤더 값보다 우선** (impersonation 방지).

**향후 모드** (이 spec 범위 외, dashboard_auth.py에 분기만 추가하면 됨): `basic` (htpasswd), `oidc`. 엔드포인트 코드 변경 0.

신규 엔드포인트 `GET /dashboard/auth-mode` — 현재 모드 반환 (`{"mode": "trust"}` 또는 `{"mode": "token"}`). 인증 미들웨어 비적용. 클라이언트가 로그인 UI(token 입력 여부)를 결정하는 데 사용.

### 4.4 HTTP 엔드포인트 (`dashboard_routes.py` 확장)

데이터 / 작업:
- `GET /dashboard/data` — 변경: snapshot에 `server` 헬스 필드 추가 (§4.8 참조). `instances`에 operator pseudo-instance 포함. **인증 적용**.
- `POST /dashboard/dispatch` — body: `{to: str, schema: str, payload: object, reply_only: bool, conversation_id?: str}`. `sender` = `operator:<request.state.operator_user>`. 내부적으로 dispatcher 호출. 성공 시 201 + `{message_id, conversation_id}`.
- `POST /dashboard/broadcast` — body: `{targets: list[str], schema: str, payload: object, reply_only: bool}`. 각 target에 dispatch 반복. 결과: `{results: [{to, message_id?, error?}]}`.
- `GET /dashboard/operator/inbox` — 호출자(`operator:<self>`)의 인박스 — envelope 본문 포함. 비ack 메시지만 기본, `?include_acked=true` 옵션.
- `POST /dashboard/operator/inbox/ack` — body: `{message_ids: list[str]}`. **ack = 인박스 표시에서 제거**(messages 테이블의 envelope 본문은 영속화 유지 — drill-down에선 여전히 보임). 구현은 `acked_at` 컬럼 추가 후 `?include_acked=true`가 아닌 한 미반환.
- `GET /dashboard/conversation/{conversation_id}` — thread 전체 (envelope 배열, 시간 순).
- `GET /dashboard/instance/{instance_id}/inbox` — 워커 인박스 (peek + 메시지 본문). 운영자 본인 inbox는 `/operator/inbox`로 우회.
- `GET /dashboard/schemas` — 등록된 schema 카탈로그 (id + JSON Schema). dispatch 모달의 schema dropdown·payload editor용.

실시간 / 인증:
- `GET /dashboard/stream` — SSE 엔드포인트 (text/event-stream). §4.7 참조.
- `GET /dashboard/auth-mode` — 인증 모드 반환. §4.3 참조. 인증 미적용.

**운영자 인박스 가시성**: 본 spec은 read-all 정책 — `GET /dashboard/instance/operator:<other>/inbox`로 다른 운영자 인박스도 조회 가능. 팀 운영 투명성 우선. 운영자별 격리는 backlog.

### 4.5 정적 자산 mount

- 새 디렉터리 `src/agent_agora/dashboard_static/` — CSS·JS·vendor 파일.
- `dashboard_routes.register()`에 `app.router.routes.append(Mount("/dashboard/static", app=StaticFiles(directory=<path>)))` 추가.

### 4.6 서버 바인딩 / 원격 설정

- 기본은 `127.0.0.1` 유지(안전 default). 변경 없음.
- README/docs에 원격 설정 가이드 추가: `--host 0.0.0.0` + `AGORA_DASHBOARD_AUTH_MODE=token` + `AGORA_DASHBOARD_TOKENS` 설정 + TLS (`certs.py` self-signed) 조합 권장.

### 4.7 SSE event publisher (`dashboard_events.py` 신규)

- 신규 모듈 — in-process pub/sub.
- 구조: 각 SSE 구독자마다 `asyncio.Queue`. publisher가 event를 모든 큐에 broadcast.
- **이벤트 종류**:
  - `data_snapshot` — 주기적 또는 변경 trigger 시 `/dashboard/data` 페이로드와 동일한 구조 push (초기 hydration용).
  - `instance_registered` / `instance_unregistered` — 워커·운영자 등록 변동.
  - `message_dispatched` — dispatch 발생 시 minimal 메타 (from·to·schema·conversation_id·timestamp).
  - `operator_inbox_message` — 특정 운영자에게 메시지 도착 (해당 운영자 구독자에게만 푸시, sender·schema·timestamp·envelope_preview).
  - `conversation_updated` — 대화에 새 메시지 추가 (conversation_id·message_count).
- **dispatcher hooks**: `dispatcher.py`에 콜백 hook 추가 — `on_dispatch(envelope)`, `on_register(info)`, `on_unregister(instance_id)`. `dashboard_events.py`가 이 hook에 subscribe.
- **`GET /dashboard/stream` 엔드포인트**:
  - 클라이언트 연결 시 큐 생성 → 큐에서 이벤트 받아 SSE format(`data: <json>\n\n`)으로 stream.
  - 연결 종료 시 큐 cleanup.
  - 초기 연결 직후 `data_snapshot` 1회 전송 → 클라이언트 즉시 hydration.
  - keepalive `: ping` 30초마다 전송.
- 구독자 식별: 인증 미들웨어를 통과한 `operator_user`를 stream 핸들러에 전달. `operator_inbox_message` 이벤트는 매칭되는 구독자에게만 send.

### 4.8 서버 헬스 (`dashboard_health.py` 신규)

- 신규 모듈 — metrics 수집.
- **수집 항목**:
  - `uptime_seconds` — 서버 시작 시각부터 경과 (server.py 시작 시 timestamp 기록).
  - `db_size_bytes` — SQLite DB 파일 크기 (`pathlib.Path.stat().st_size`).
  - `write_queue_depth` — `persistence.AsyncWriteQueue`의 현재 큐 길이.
  - `sweeper_last_run_at` — 마지막 sweep 시각.
  - `sweeper_runs_total` — 누적 실행 횟수.
- `/dashboard/data` snapshot에 `server` 키로 포함: `{"uptime_seconds": 1234, "db_size_bytes": ..., ...}`.
- 변경 trigger: 의미 있는 변동(예: sweeper run, queue depth 변화) 시 SSE `data_snapshot` 발화. 단순 시간 경과는 client 측에서 보간(server.uptime + 경과 시간).
- `sweeper.py`·`persistence.py`에 collector 호출 hook 추가 (단순 카운터·timestamp 기록).

## 5. 클라이언트 측 변경

### 5.1 파일 구조

```
src/agent_agora/
  dashboard.html               # 교체 — 작은 shell + <link>·<script>
  dashboard_static/            # 신규
    css/dashboard.css
    js/api.js                  # fetch wrapper + 인증 헤더 자동 첨부
    js/stream.js               # EventSource wrapper + 이벤트 dispatch
    js/login.js                # 로그인 모달 (mode-aware: token 모드면 token 입력)
    js/dashboard.js            # 메인 hydration + 레이아웃 조립
    js/dispatch.js             # dispatch 모달
    js/inbox.js                # 운영자 인박스 패널
    js/drilldown.js            # 대화·인스턴스 인박스 모달
    js/health.js               # 서버 헬스 카드
    vendor/tabulator.min.js    # 정렬·필터 테이블
    vendor/tabulator.min.css
    vendor/jsoneditor.min.js   # schema 기반 payload 에디터
    vendor/jsoneditor.min.css
```

### 5.2 로그인 흐름

- 페이지 로드 → `GET /dashboard/auth-mode` 호출 → 응답에 따라 로그인 모달 form 구성:
  - `trust` 모드: username 입력만.
  - `token` 모드: username 입력 + token 입력 (둘 다 필수).
- `localStorage`에 `operator_username` (+ `operator_token` if token mode) 저장.
- `api.js` 및 `stream.js`가 모든 요청에 적절한 인증 헤더 첨부:
  - trust: `X-Agora-Operator-User: <username>`.
  - token: `Authorization: Bearer <token>` + `X-Agora-Operator-User: <username>` (서버는 token에서 추출한 username 우선).
- 헤더 우상단: `operator:<username>` + 로그아웃 (localStorage clear → 로그인 모달 재표시).

### 5.3 메인 레이아웃

```
┌──────────────────────────────────────────────────────────────────────┐
│ AgentAgora — operator:alice  [● SSE]  uptime 1h23m | db 4MB  [로그아웃]│
├─────────────────────┬────────────────────────────────────────────────┤
│                     │ [요약 4 카드]                                   │
│ 운영자 인박스 (3)    ├────────────────────────────────────────────────┤
│ ┌─────────────────┐ │ 인스턴스 (Tabulator: 정렬·필터)                  │
│ │ from worker3    │ │                                                │
│ │ schema: response│ ├────────────────────────────────────────────────┤
│ │ 09:34:12        │ │ 대화 (Tabulator)                                │
│ │ [본문 preview]  │ │                                                │
│ │ [ack]           │ ├────────────────────────────────────────────────┤
│ └─────────────────┘ │ 봇                                              │
│ ... 더보기          ├────────────────────────────────────────────────┤
│                     │ comm-matrix SVG                                │
│ 헬스 expand ▼       │                                                │
│  write queue: 0     │                                                │
│  sweeper: 12회      │                                                │
└─────────────────────┴────────────────────────────────────────────────┘
                                                          [+ 보내기]   ← floating
```

- 헤더 우측: SSE 연결 상태 indicator(● = 연결, ○ = 폴링 fallback), uptime·db 크기 inline.
- 좌측 하단: 헬스 카드 expand — write queue·sweeper 통계.
- 좌측 인박스 패널: 새 메시지 도착 시 unread badge (SSE 푸시로 즉시 갱신).
- 메시지 클릭 → 드릴다운 모달에 전체 envelope.
- 우하단 "보내기" 플로팅 버튼 → dispatch 모달.

### 5.4 Dispatch 모달

- 모드 토글: **단일 워커** / **브로드캐스트**.
- **단일 워커**: 인스턴스 dropdown (현재 등록된 워커 목록; 다른 operator도 가능). 단일 워커 = 사용자께서 확인하신 "유저가 인스턴스로 직접 전달".
- **브로드캐스트**: 체크박스 리스트 (인스턴스 전체) + "모두 선택" + role 필터 chip.
- **Schema**: dropdown — `/dashboard/schemas`에서 가져옴.
- **Payload**: JSONEditor — 선택한 schema가 있으면 form 모드, raw JSON fallback.
- **reply_only** 체크박스.
- 전송 → POST → 성공 시 모달 닫고 토스트.

### 5.5 드릴다운 모달

- **대화 thread**: 대화 행 클릭 → `GET /dashboard/conversation/{id}` → 모달에 메시지 N개 카드 (sender·receiver·timestamp·schema·payload formatted·`reply_only` 마커).
- **인스턴스 인박스**: 워커 행 클릭 → `GET /dashboard/instance/{id}/inbox` → 모달에 현재 인박스 메시지 목록.
- 모달 열려 있는 동안 SSE 이벤트는 큐잉(즉시 적용 안 함). 모달 닫으면 큐 비우며 일괄 반영(데이터 흔들림 방지).

### 5.6 갱신 — SSE-first, 폴링 fallback

- 페이지 부팅 시:
  1. `GET /dashboard/data` 1회 호출 — 초기 hydration (헤더의 헬스 메트릭 포함).
  2. `EventSource("/dashboard/stream")` 연결.
  3. 이후 모든 변동은 SSE 이벤트로 수신 — `data_snapshot`은 전체 교체, 개별 이벤트(`instance_registered` 등)는 부분 갱신.
- SSE 연결 실패·끊김:
  - `stream.js`가 5초 backoff로 재연결 시도 (최대 60초까지 exponential).
  - 재연결 동안 폴링 fallback (3초 간격, `/dashboard/data`). 헤더 indicator에 ○ 표시.
  - 재연결 성공 시 폴링 중단, ● 복귀.
- `health.js`: uptime은 server uptime + (now - last sync) 형태로 client 측 보간 (매 초 갱신).

## 6. 파일 영향

| 파일 | 변경 |
|---|---|
| `src/agent_agora/envelope.py` | `reply_only: bool = False` 필드 |
| `src/agent_agora/registry.py` | `operator:` 접두사 인스턴스 지원 (등록 경로는 기존 사용) |
| `src/agent_agora/comm_matrix.py` | operator bypass 규칙 |
| `src/agent_agora/sweeper.py` | operator 인스턴스 GC 면제 + sweeper 통계 hook |
| `src/agent_agora/dispatcher.py` | event hook 추가 (on_dispatch·on_register·on_unregister) |
| `src/agent_agora/persistence.py` | AsyncWriteQueue depth 노출 |
| `src/agent_agora/dashboard_routes.py` | 9개 신규 엔드포인트(/stream·/auth-mode 포함) + StaticFiles mount + /data 확장 |
| `src/agent_agora/dashboard_auth.py` | **신규** — trust·token 두 모드 |
| `src/agent_agora/dashboard_events.py` | **신규** — SSE pub/sub + dispatcher hook 구독 |
| `src/agent_agora/dashboard_health.py` | **신규** — metrics 수집 |
| `src/agent_agora/dashboard.html` | 교체 — shell |
| `src/agent_agora/dashboard_static/` | **신규** — CSS·JS·vendor (총 13파일) |
| `plugin/cc-agora/skills/agora-protocol/SKILL.md` | reply_only 존중 규칙 한 줄 |
| `docs/dashboard.md` | 신규 기능·원격 설정·SSE·인증 모드 가이드 |
| 테스트 | 9개 신규/확장 (아래 §8) |

## 7. 에러 / 엣지케이스

- **빈 username**: 401, login 모달에서 "username 필수" 표시.
- **token 모드에서 token 미입력/잘못된 token**: 401, login 모달에서 "token 검증 실패" 표시.
- **token 모드에서 token이 다른 username 매핑**: token 우선 — header username 무시. 클라이언트엔 정정된 username 반환되도록 응답에 포함.
- **dispatch to 존재하지 않는 워커**: 404, dispatch 모달에서 토스트로 통보.
- **dispatch schema 등록 안 됨**: 422, 모달에서 schema dropdown으로 안내.
- **broadcast targets 빈 리스트**: 422, "최소 1개 target 필요".
- **운영자 inbox 빈 상태**: 200, 빈 배열 + UI "(메시지 없음)".
- **SSE 연결 끊김**: 자동 backoff 재연결 + 그 사이 폴링 fallback. indicator로 가시화.
- **SSE 구독자 폭증**: 각 구독자가 own Queue + dispatcher hook이 broadcast. 100+ 구독자가 동시에 붙어도 in-process 메모리만 소비 (각 큐 최대 길이 제한, 초과시 오래된 이벤트 drop + warning event).
- **dispatcher event hook 예외**: hook 내 예외가 dispatcher 본 로직을 막지 않도록 wrap (try/except + log).
- **모달 열려 있는 동안 워커 등록/해제**: 모달 안의 dropdown은 stale일 수 있음. 모달 열기 시 fresh fetch.
- **localStorage 비활성 브라우저**: login 모달이 매 새로고침 표시 (UX 저하). 안내 메시지로 fallback.
- **운영자 인스턴스가 conversation에 속해있을 때 ack 처리**: 메시지 본문은 보관 (drill-down에서 여전히 보임). inbox에서만 제거.
- **헬스 메트릭 수집 실패** (e.g. DB 파일 일시적 lock): 해당 필드만 null 또는 마지막 알려진 값. 다른 필드는 그대로.

## 8. 테스트

| 파일 | 검증 |
|---|---|
| `tests/test_envelope.py` | reply_only 필드 직렬화·역직렬화·default False |
| `tests/test_registry.py` | operator:<x> 인스턴스 등록·조회; sweeper 면제 |
| `tests/test_comm_matrix.py` | operator bypass (active matrix에서 allow) |
| `tests/test_dashboard_routes.py` | 9개 엔드포인트 happy path + 에러 + 인증 적용 |
| `tests/test_dashboard_auth.py` | trust 모드 헤더 신뢰; token 모드 매핑·impersonation 방지; 401 케이스; auth-mode endpoint |
| `tests/test_dashboard_events.py` | SSE pub/sub 동작; dispatcher hook 호출; 구독자별 큐 분리; operator_inbox_message 라우팅; 큐 overflow drop |
| `tests/test_dashboard_health.py` | uptime·db_size·queue·sweeper 메트릭 수집; collector 예외 안전 |
| `tests/test_dashboard_static.py` | StaticFiles mount 동작 (vendor 파일 존재·서빙) |
| `tests/test_dispatcher_hooks.py` | dispatcher event hook이 dispatch/register/unregister에 호출되고 예외가 본 로직을 막지 않음 |

## 9. 미해결 / 백로그

본 spec 범위 외, `docs/backlog.md`로 기록:
- 워크플로 파이프라인 시각화 (Cytoscape 도입).
- 운영자 액션 (대화 close·워커 unregister·comm-matrix UI 편집 — admin_routes 게이트 활용).
- 에러/이벤트 로그 패널.
- 스키마 카탈로그 explorer (등록된 스키마·사용 통계·JSON Schema viewer).
- 파일 스토어 뷰.
- 시계열 차트 (인박스 depth·dispatch rate sparkline).
- 추가 인증 모드 (basic·OIDC) — dashboard_auth.py에 분기 추가.
- 운영자별 inbox 격리 (다른 운영자의 inbox 비공개 정책 옵션).
- 검색 엔진 (FTS5 기반 메시지·대화 full-text 검색).
