# 팀 현황 대시보드

AgentAgora 서버가 제공하는 운영 대시보드다. 브라우저 한 탭으로 현재 등록된 워커 인스턴스, 봇, 대화, comm-matrix 그래프를 실시간으로 확인하고, 운영자가 직접 메시지를 dispatch하거나 인박스를 조회할 수 있다.

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
| `server` | 객체 | 서버 헬스 지표 (아래 참고, 선택적) |

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

**`server` 필드 (서버 헬스)**

`HealthCollector`가 활성화된 경우에만 포함된다.

| 필드 | 설명 |
|------|------|
| `uptime_seconds` | 서버 시작 후 경과 시간(초) |
| `db_size_bytes` | SQLite 데이터베이스 파일 크기(바이트) |
| `write_queue_depth` | 현재 비동기 쓰기 큐 깊이 |
| `sweeper_runs_total` | Sweeper 누적 실행 횟수 |
| `sweeper_last_run_at` | Sweeper 마지막 실행 시각 (ISO 8601) |

---

## 운영자 액션 엔드포인트

서버에 `persistence`와 `write_queue`가 제공된 경우에만 활성화된다. 모든 엔드포인트는 인증 미들웨어를 통해 운영자 사용자명을 `request.state.operator_user`로 주입한다.

### `POST /dashboard/dispatch`

운영자가 특정 워커 한 명에게 메시지를 발송한다.

**요청 본문 (JSON)**

| 필드 | 필수 | 설명 |
|------|------|------|
| `to` | 필수 | 수신 인스턴스 ID |
| `schema` | 필수 | 메시지 스키마 이름 (예: `"task_request"`) |
| `payload` | 선택 | 메시지 본문 객체 (기본 `{}`) |
| `reply_only` | 선택 | `true`이면 워커에게 답장만 요청 (기본 `false`) |
| `conversation_id` | 선택 | 기존 대화에 이어 붙일 때 지정 |

**응답** — 201 Created

```json
{
  "message_id": "msg_abc123",
  "conversation_id": "conv_xyz456"
}
```

`to`나 `schema`가 없으면 422, 수신자가 등록되지 않았으면 404를 반환한다.

---

### `POST /dashboard/broadcast`

운영자가 여러 워커에게 동일한 메시지를 일괄 발송한다.

**요청 본문 (JSON)**

| 필드 | 필수 | 설명 |
|------|------|------|
| `targets` | 필수 | 수신 인스턴스 ID 배열 |
| `schema` | 필수 | 메시지 스키마 이름 |
| `payload` | 선택 | 메시지 본문 객체 (기본 `{}`) |
| `reply_only` | 선택 | `true`이면 각 워커에게 답장만 요청 (기본 `false`) |

**응답** — 200 OK

```json
{
  "results": [
    {"to": "worker-a", "message_id": "msg_1", "conversation_id": "conv_1"},
    {"to": "worker-b", "error": "recipient not registered"}
  ]
}
```

개별 워커에 대한 실패는 해당 항목의 `error` 필드에 담긴다. 전체 요청은 실패하지 않는다.

---

### `GET /dashboard/operator/inbox`

현재 운영자(`operator:<username>`)의 수신 메시지 목록을 반환한다.

**쿼리 파라미터**

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `include_acked` | `false` | `true`이면 이미 읽음 처리된 메시지도 포함 |

**응답**

```json
{"messages": [...]}
```

---

### `POST /dashboard/operator/inbox/ack`

메시지를 읽음 처리(ack)한다.

**요청 본문 (JSON)**

```json
{"message_ids": ["msg_1", "msg_2"]}
```

**응답**

```json
{"acked": 2}
```

---

### `GET /dashboard/conversation/{conversation_id}`

특정 대화의 전체 메시지 스레드를 반환한다. 읽음 처리 여부와 관계없이 모든 메시지를 포함한다.

**응답**

```json
{"messages": [...]}
```

---

### `GET /dashboard/instance/{instance_id}/inbox`

특정 워커 인스턴스의 인박스를 드릴다운한다. 읽음 처리된 메시지도 포함한다.

**응답**

```json
{"messages": [...]}
```

---

### `GET /dashboard/schemas`

서버에 등록된 메시지 스키마 카탈로그를 반환한다. `schema_registry`가 없으면 빈 배열을 반환한다.

**응답**

```json
{
  "schemas": [
    {"id": "task_request", "schema": { /* JSON Schema */ }},
    ...
  ]
}
```

---

### `GET /dashboard/stream`

서버-전송 이벤트(SSE) 실시간 스트림. `event_broker`가 활성화된 경우에만 동작한다. 자세한 내용은 [SSE 푸시](#sse-푸시) 절 참고.

---

### `GET /dashboard/auth-mode`

인증 미들웨어 없이 누구나 읽을 수 있다. 현재 서버의 인증 모드를 반환한다.

**응답**

```json
{"mode": "trust"}
```

---

## 대시보드가 보여주는 것

### 요약 카드

페이지 상단에 4개의 요약 카드가 표시된다: 총 인스턴스 수, 봇 수, 열린 대화 수, 총 인박스 깊이.

### 인스턴스 테이블

현재 등록된 모든 워커 인스턴스를 테이블로 나열한다. 인박스에 메시지가 있는 인스턴스는 큐 깊이 셀이 강조 표시(노란색)된다. 행을 클릭하면 해당 인스턴스의 인박스 드릴다운(`GET /dashboard/instance/{instance_id}/inbox`)으로 이동한다.

### 봇 테이블

`register_bot`으로 등록된 봇 목록을 보여준다. 봇 모드와 구독 중인 메시지 스키마를 함께 표시한다.

### 대화 테이블

서버에 기록된 최근 대화 50개를 표시한다. 대화 ID, 종류, 상태, 메시지 수, 마지막 메시지 시각이 포함된다. 행을 클릭하면 대화 스레드 드릴다운(`GET /dashboard/conversation/{conversation_id}`)으로 이동한다.

### comm-matrix 방향 그래프

comm-matrix가 활성(`active: true`)인 경우, 워커 인스턴스를 노드로, 허용된 dispatch 방향을 화살표로 나타낸 SVG 방향 그래프를 렌더링한다. 화살표 위의 숫자는 weight다. comm-matrix가 비활성이면 "all-allow" 안내 메시지만 표시한다.

### 운영자 dispatch 패널

스키마를 선택하고 페이로드를 편집한 뒤 특정 워커에게 메시지를 전송할 수 있다. `POST /dashboard/dispatch`를 호출한다. JSONEditor(스키마 기반 폼)가 내장되어 있어 페이로드 구조를 안내받으며 입력할 수 있다.

### 프론트엔드 의존성

테이블 정렬·필터링에는 **Tabulator**, 스키마 기반 페이로드 편집에는 **JSONEditor**를 사용한다. 두 라이브러리는 `dashboard_static/vendor/`에 vendored되어 있으며, 외부 CDN에 의존하지 않는다.

---

## 자동 갱신

페이지는 **3초마다** `/dashboard/data`를 폴링해 자동으로 화면을 갱신한다. SSE(`/dashboard/stream`)가 사용 가능한 경우 이벤트 기반으로 즉시 반영된다. 서버와의 연결 상태는 우상단의 상태 표시기("연결됨" / "연결 끊김")로 확인할 수 있다.

---

## SSE 푸시

`EventSource('/dashboard/stream')`를 열면 서버로부터 실시간 이벤트를 수신한다.

### 이벤트 타입

| 이벤트 | 설명 |
|--------|------|
| `data_snapshot` | 전체 대시보드 스냅샷 (연결 직후 초기 hydration + 주기 업데이트 시 전송) |
| `instance_registered` | 새 인스턴스가 등록됨 |
| `instance_unregistered` | 인스턴스가 해제됨 |
| `message_dispatched` | 메시지가 dispatch됨 |
| `operator_inbox_message` | 운영자 인박스에 새 메시지가 도착함 |

모든 이벤트는 `{"type": "<이벤트명>", "payload": {...}}` 형태의 단일 `data:` 라인으로 전송된다.

### 인증 (SSE)

`EventSource`는 커스텀 HTTP 헤더를 지원하지 않는다. 인증 정보는 쿼리 파라미터로 전달한다.

- `trust` 모드: `?u=<username>`
- `token` 모드: `?u=<username>&t=<token>`

### 재연결

연결이 끊기면 지수 백오프(5초 → 최대 60초)로 재연결을 시도한다. SSE 연결 자체가 실패하면 3초 폴링(`/dashboard/data`) 폴백으로 자동 전환된다.

---

## 인증 모드

`AGORA_DASHBOARD_AUTH_MODE` 환경 변수로 제어한다.

### `trust` (기본값)

로컬 / 신뢰 LAN 환경용. 추가 시크릿 없이 사용자명만 자기 신고한다.

- 운영자 사용자명은 요청의 `X-Agora-Operator-User` 헤더에서 읽는다.
- 헤더가 없으면 `"anonymous"`로 처리한다.

```bash
# trust 모드 명시 (기본값이므로 생략 가능)
AGORA_DASHBOARD_AUTH_MODE=trust python -m agent_agora --port 8420 --no-timeout
```

### `token`

원격 배포 또는 멀티-사용자 환경용. Bearer 토큰으로 사용자를 식별한다.

- 요청 헤더에 `Authorization: Bearer <token>`을 포함해야 한다.
- `AGORA_DASHBOARD_TOKENS=user1:tok1,user2:tok2` 형태로 토큰-사용자명 매핑을 설정한다.
- 토큰으로 추출한 사용자명이 `X-Agora-Operator-User` 헤더보다 우선한다 (impersonation 방지).
- 유효하지 않은 토큰은 401을 반환한다.

```bash
AGORA_DASHBOARD_AUTH_MODE=token \
AGORA_DASHBOARD_TOKENS=alice:secret_a,bob:secret_b \
python -m agent_agora --port 8420 --no-timeout
```

---

## 원격 배포 설정

기본적으로 서버는 `127.0.0.1`에만 바인딩되어 로컬 접근만 허용한다. 원격에서 접근하려면 다음 단계를 따른다.

### 체크리스트

1. **서버 바인딩 변경**

   ```bash
   python -m agent_agora --host 0.0.0.0 --port 8420 --no-timeout
   ```

2. **토큰 인증 활성화** (원격 노출 시 필수)

   ```bash
   export AGORA_DASHBOARD_AUTH_MODE=token
   export AGORA_DASHBOARD_TOKENS=alice:your_token_here
   ```

3. **TLS 설정**

   - 내부 테스트용: `certs.py`가 자체 서명 인증서를 생성한다. `--no-tls` 없이 서버를 시작하면 자동 적용된다.
   - 프로덕션: 리버스 프록시(nginx, Caddy 등)를 앞에 두고 공인 인증서를 사용한다.

4. **방화벽 포트 오픈**

   서버 포트(기본 `8420`)를 방화벽에서 허용한다. 불필요한 포트는 닫는다.

5. **브라우저 접속**

   ```
   https://<서버-IP>:8420/dashboard
   ```

---

## 다중 운영자 모델

대시보드는 운영자마다 `operator:<username>` 형태의 pseudo-instance를 사용한다.

- 운영자가 처음 dispatch하는 순간 레지스트리에 자동 등록된다 (lazy registration).
- `sweeper`의 TTL/dead-session 정리 대상에서 제외된다.
- comm-matrix ACL을 우회한다 — 운영자는 등록된 모든 워커에게 메시지를 보낼 수 있다.
- 운영자의 인박스는 사용자별로 분리된다 (`GET /dashboard/operator/inbox`는 본인 메시지만 반환).
- 모든 운영자의 인박스는 전체 읽기 투명 정책에 따라 대시보드에서 읽을 수 있다.

---

## `reply_only` 플래그

dispatch 요청의 선택적 불리언 필드다.

- `true`이면 수신 워커에게 "이 메시지에 대한 답장만 보내달라"는 의도를 전달한다.
- **서버는 이 플래그를 강제하지 않는다.** 워커가 `agora-protocol` 스킬 규약에 따라 자율적으로 처리한다.
- `agora-protocol` 동작 규약은 [`plugin/cc-agora/skills/agora-protocol/SKILL.md`](../plugin/cc-agora/skills/agora-protocol/SKILL.md)를 참고한다.

---

## 읽기 전용 모드와 액션 모드

기본(`persistence` 미제공) 상태에서는 대시보드가 읽기 전용이다. `persistence`와 `write_queue`가 모두 제공된 경우에만 dispatch·broadcast·inbox 엔드포인트가 활성화된다. comm-matrix 변경, 인스턴스 등록/해제는 대시보드에서 수행하지 않는다 — `/cc-agora-ops:agora-comm-matrix` 스킬을 사용한다.

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

## 참고

- [`src/agent_agora/dashboard/routes.py`](../src/agent_agora/dashboard/routes.py) — 라우트 구현 및 JSON 조립
- [`src/agent_agora/dashboard/dashboard.html`](../src/agent_agora/dashboard/dashboard.html) — 대시보드 UI
- [`plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md`](../plugin/cc-agora-ops/skills/agora-dashboard/SKILL.md) — 오픈 스킬 정의
- [`plugin/cc-agora/skills/agora-protocol/SKILL.md`](../plugin/cc-agora/skills/agora-protocol/SKILL.md) — `reply_only` 워커 처리 규약
