# 팀 현황 대시보드

AgentAgora 서버가 제공하는 읽기 전용 운영 대시보드다. 브라우저 한 탭으로 현재 등록된 워커 인스턴스, 봇, 대화, 그리고 comm-matrix 그래프를 실시간으로 확인할 수 있다.

---

## 엔드포인트

### `GET /dashboard`

단일 자체 포함(self-contained) HTML 페이지를 반환한다. 외부 CDN, 빌드 단계, 정적 파일 서버가 전혀 필요 없다. 서버가 실행 중이면 브라우저에서 바로 열 수 있다.

기본 URL:

```
http://127.0.0.1:8420/dashboard
```

### `GET /dashboard/data`

페이지가 주기적으로 폴링하는 JSON 엔드포인트다. 응답 필드는 다음과 같다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `generated_at` | ISO 8601 문자열 | 스냅샷 생성 시각 (UTC) |
| `summary.instances` | 정수 | 등록된 워커 인스턴스 수 |
| `summary.bots` | 정수 | 등록된 봇 수 |
| `summary.open_conversations` | 정수 | 현재 열린(`open`) 대화 수 |
| `summary.total_inbox_depth` | 정수 | 전체 인스턴스의 인박스 합계 |
| `instances[]` | 배열 | 워커 인스턴스 목록 (아래 참고) |
| `bots[]` | 배열 | 봇 목록 (아래 참고) |
| `conversations[]` | 배열 | 최근 대화 50개 |
| `comm_matrix` | 객체 | 디스패치 허용 매트릭스 (아래 참고) |

**`instances[]` 항목 필드**

| 필드 | 설명 |
|------|------|
| `instance_id` | 인스턴스 식별자 |
| `role` | 역할 (`orchestrator` / `worker` 등) |
| `description` | 등록 시 지정한 설명 |
| `inbox_depth` | 현재 인박스 큐 깊이 (0보다 크면 강조 표시) |
| `in_flight` | 현재 처리 중인 메시지 수 |
| `last_seen_at` | 마지막 활동 타임스탬프 |
| `accepting` | 새 메시지를 받는 상태인지 여부 |

**`bots[]` 항목 필드**

| 필드 | 설명 |
|------|------|
| `instance_id` | 봇 식별자 |
| `bot_mode` | 봇 동작 모드 |
| `subscribe_schemas` | 이 봇이 구독하는 메시지 스키마 목록 |

**`conversations[]` 항목 필드**

| 필드 | 설명 |
|------|------|
| `conversation_id` | 대화 식별자 |
| `kind` | 대화 종류 |
| `status` | 상태 (`open` / `closed` 등) |
| `message_count` | 누적 메시지 수 |
| `last_message_at` | 마지막 메시지 타임스탬프 |

**`comm_matrix` 필드**

| 필드 | 설명 |
|------|------|
| `active` | 매트릭스 활성 여부. `false`면 all-allow (모든 워커가 서로 dispatch 가능) |
| `matrix` | `matrix[to][from] = weight` 형태의 중첩 객체. weight > 0이면 `from → to` 방향 dispatch 허용 |

---

## 대시보드가 보여주는 것

### 요약 카드

페이지 상단에 4개의 요약 카드가 표시된다: 총 인스턴스 수, 봇 수, 열린 대화 수, 총 인박스 깊이.

### 인스턴스 테이블

현재 등록된 모든 워커 인스턴스를 테이블로 나열한다. 인박스에 메시지가 있는 인스턴스는 큐 깊이 셀이 강조 표시(노란색)된다.

### 봇 테이블

`register_bot`으로 등록된 봇 목록을 보여준다. 봇 모드와 구독 중인 메시지 스키마를 함께 표시한다.

### 대화 테이블

서버에 기록된 최근 대화 50개를 표시한다. 대화 ID, 종류, 상태, 메시지 수, 마지막 메시지 시각이 포함된다.

### comm-matrix 방향 그래프

comm-matrix가 활성(`active: true`)인 경우, 워커 인스턴스를 노드로, 허용된 dispatch 방향을 화살표로 나타낸 SVG 방향 그래프를 렌더링한다. 화살표 위의 숫자는 weight다. comm-matrix가 비활성이면 "all-allow" 안내 메시지만 표시한다.

---

## 자동 갱신

페이지는 **3초마다** `/dashboard/data`를 폴링해 자동으로 화면을 갱신한다. 수동 새로고침이 필요 없다. 서버와의 연결 상태는 우상단의 상태 표시기("연결됨" / "연결 끊김")로 확인할 수 있다.

---

## 읽기 전용

대시보드는 데이터를 조회하기만 한다. comm-matrix 변경, 인스턴스 등록/해제 등 상태를 변경하는 기능은 없다. comm-matrix를 변경하려면 `/cc-agora-ops:agora-comm-matrix` 스킬을 사용한다.

---

## 오픈 방법: `/cc-agora-ops:agora-dashboard`

cc-agora-ops 플러그인의 `/cc-agora-ops:agora-dashboard` 슬래시 스킬이 대시보드를 운영자의 기본 브라우저로 연다.

```
/cc-agora-ops:agora-dashboard
# 또는 서버 URL 지정
/cc-agora-ops:agora-dashboard --server-url http://127.0.0.1:8420
```

스킬은 플랫폼에 맞는 명령(`start` / `open` / `xdg-open`)으로 브라우저를 열고, URL을 터미널에도 출력해 브라우저 실행이 실패해도 수동 접속이 가능하도록 한다.

서버가 먼저 실행 중이어야 한다:

```bash
python -m agent_agora --port 8420 --no-tls --no-timeout
```

---

## 보안 고려 사항

대시보드 엔드포인트는 토큰 인증이 없다. 서버가 `127.0.0.1`에만 바인딩되므로 로컬호스트 접근만 허용된다. 향후 인증이 필요한 경우 `dashboard_routes.py`의 `register` 함수에 토큰 게이트를 추가한다.

---

## 참고

- [`src/agent_agora/dashboard_routes.py`](../src/agent_agora/dashboard_routes.py) — 라우트 구현 및 JSON 조립
- [`src/agent_agora/dashboard.html`](../src/agent_agora/dashboard.html) — 대시보드 UI
- [`plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md`](../plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md) — 오픈 스킬 정의
