# HTML+JS 팀 현황 대시보드 설계

> 2026-05-17. AgentAgora 서버가 팀 현황 대시보드를 서빙한다 — 등록 인스턴스·봇·
> 인박스 깊이·in-flight·대화·comm-matrix를 브라우저에서 라이브로 본다.

## 1. 배경 / 동기

운영자가 팀 상태를 보려면 현재 `agora.instances`·`agora.peek`·`agora.conversations_list`
MCP 도구를 일일이 호출해야 한다. 한눈에 보는 라이브 대시보드가 없다.

이 설계는 AgentAgora 서버에 대시보드 HTTP 라우트를 추가한다. 브라우저가 JSON 현황
엔드포인트를 주기적으로 폴링해 라이브로 렌더한다. `cc-agora-ops` 플러그인에 대시보드를
여는 슬래시를 둔다.

## 2. 아키텍처

- **`dashboard_routes.py`** (신규) — `admin_routes.py`를 미러한 Starlette 라우트 모듈.
  - `GET /dashboard` — 자기완결형 HTML 페이지를 서빙.
  - `GET /dashboard/data` — 팀 현황 JSON 스냅샷.
- **`dashboard.html`** (신규, 패키지 데이터) — 인라인 CSS+JS 단일 파일. JS가
  `/dashboard/data`를 ~3초 간격으로 폴링해 DOM을 갱신한다.
- **`cc-agora-ops`의 신규 슬래시 `agora-dashboard`** — 대시보드 URL을 브라우저로 연다.

**인증.** localhost 전용·토큰 없음 — 서버의 `127.0.0.1` 바인딩(로컬 개발 모드)에
의존한다. 읽기 전용 운영 데이터다. 네트워크 개방·인증 게이트는 향후 확장으로 두되,
라우트를 `register(...)` 함수로 구조화해 게이트를 나중에 끼우기 쉽게 한다
(`admin_routes.maybe_register` 패턴).

## 3. `dashboard_routes.py`

`admin_routes.py`와 같은 구조 — 의존성을 클로저로 캡처하는 라우트 팩토리.

```
register(app, *, dispatcher, instance_registry, bot_registry, comm_matrix) -> None
```

`app`(Starlette)에 두 라우트를 등록한다. `admin_routes.maybe_register`가 호출되는
앱 구성 지점 옆에서 호출한다.

- **`GET /dashboard`** — 패키지에 동봉된 `dashboard.html`을 읽어 `text/html`로 반환.
- **`GET /dashboard/data`** — 아래 JSON을 조립해 반환(§4).

토큰 검사는 하지 않는다. 향후 인증이 필요해지면 `register`에 token 인자를 더하고
핸들러 앞에 게이트를 끼운다 — 라우트 구조는 그대로.

## 4. `/dashboard/data` JSON

기존 소스에서 조립한다 — `dispatcher.peek(...)`, `instance_registry.list_instances()`,
`bot_registry.list_bots()`, `dispatcher.conversations_list(...)`, `comm_matrix.snapshot()`·
`comm_matrix.active`.

```json
{
  "generated_at": "<ISO 8601>",
  "summary": {
    "instances": 0, "bots": 0, "open_conversations": 0, "total_inbox_depth": 0
  },
  "instances": [
    {"instance_id": "...", "role": "...", "description": "...",
     "inbox_depth": 0, "in_flight": 0, "last_seen_at": "...", "accepting": true}
  ],
  "bots": [
    {"instance_id": "...", "bot_mode": "handler|observer", "subscribe_schemas": ["..."]}
  ],
  "conversations": [
    {"conversation_id": "...", "status": "...", "kind": "...",
     "message_count": 0, "last_message_at": "..."}
  ],
  "comm_matrix": {"active": false, "matrix": {"<to>": {"<from>": 0}}}
}
```

- `instances` — `dispatcher.peek`(인박스 깊이·in-flight)와 `instance_registry`(role·
  description·last_seen·accepting)를 합쳐 항목당 한 행.
- `conversations` — `conversations_list`(기본 limit, 최근순). 전부가 아니라 최근 N개.
- `comm_matrix` — `{active, matrix}`. `matrix`는 `comm_matrix.snapshot()`의
  `{to: {from: weight}}` 그대로(comm-matrix v2).

## 5. 대시보드 표시 (`dashboard.html`)

JS가 `/dashboard/data`를 ~3초 폴링해 렌더한다:

- **요약 바** — 인스턴스 수·봇 수·열린 대화 수·총 인박스 깊이.
- **인스턴스 테이블** — `instance_id`·role·인박스 깊이·in-flight·last_seen·accepting.
  인박스 깊이가 크면 시각적으로 강조한다.
- **봇 목록** — `instance_id`·mode·구독 스키마.
- **대화 목록** — 최근 대화의 id·status·kind·메시지 수·last_message_at.
- **comm-matrix 방향 그래프** — `{to: {from: weight}}`를 **방향 그래프**로 렌더한다.
  노드 = 인스턴스, 방향 엣지 `A→B` = 「A가 B에 dispatch 가능」 — 화살표가 송신→수신
  방향을 가리킨다. 엣지 라벨 = weight. `weight>0`인 쌍만 엣지를 그린다(`0`=금지=엣지
  없음). 비활성 매트릭스(`active=false`)면 "비활성 — all-allow" 텍스트로 표시(엣지
  생략). 구현: **SVG + 원형 레이아웃** — 노드를 원주에 균등 배치하고, 엣지는 `marker-end`
  화살표가 달린 `line`/`path`로, 양방향 쌍(`A→B`·`B→A` 둘 다 존재)은 살짝 휘어
  겹치지 않게 그린다. **바닐라 JS·자기완결형 — 외부 그래프 라이브러리·CDN 없음.**
  AgentAgora 팀은 워커 한 줌 규모라 원형 레이아웃으로 충분하다(force 시뮬레이션
  불필요). **읽기 전용 — 편집 UI 없음.** 매트릭스 교체는 `/cc-agora-ops:agora-comm-matrix`
  슬래시 소관.

자기완결형 — 외부 CDN·빌드 단계·그래프 라이브러리 없이 인라인 CSS+JS+SVG 한 파일.
폴링 실패 시 마지막 스냅샷을 유지하고 "연결 끊김"을 표시한다.

## 6. `agora-dashboard` 슬래시

`cc-agora-ops` 플러그인의 신규 스킬. `disable-model-invocation: true`(운영자가 명시
트리거). 동작: 대시보드 URL(`http://127.0.0.1:8420/dashboard`, `--server-url`로
오버라이드)을 안내하고 가능하면 기본 브라우저로 연다. SKILL.md 본문·frontmatter 영어.

## 7. 테스트

- `tests/test_dashboard_routes.py` (신규) — Starlette `TestClient`로:
  - `GET /dashboard/data`가 200 + 위 JSON 형태(키 존재·`summary` 카운트 정확성).
  - `GET /dashboard`가 200 + `text/html`.
  - 인스턴스·봇·대화가 데이터에 반영되는지(등록 후 조회).
- `dashboard.html`은 정적 에셋이라 단위 테스트하지 않는다.

## 8. 비목표 (YAGNI)

- 대시보드에서의 comm-matrix 편집 — 조회 전용. 교체는 `agora-comm-matrix` 슬래시.
- 인증·네트워크 개방 — 향후. v1은 localhost 전용.
- SSE/WebSocket 푸시 — 폴링으로 충분.
- 히스토리·차트·시계열 — 현재 스냅샷만.

## 9. 플랜 분할 (독립 머지 가능)

- **Plan 1 — 서버 측 대시보드.** `dashboard_routes.py`, `/dashboard/data` 조립,
  `dashboard.html`, 앱 와이어링(`register` 호출), `test_dashboard_routes.py`.
- **Plan 2 — `agora-dashboard` 슬래시.** `cc-agora-ops`에 스킬 추가. Plan 1과 독립
  (URL만 열므로 — 다만 실제로 열어 보려면 Plan 1이 머지돼 있어야 의미 있음).
