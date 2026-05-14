# Agora Coordination v3 — Design Spec

- 날짜: 2026-05-14
- 대상 코드: `AgentAgora/src/agent_agora/`
- 베이스: v1 (현행) — `Dispatcher`, `InstanceRegistry`
- 입력 문서: [자유대화_실험_리뷰_종합_2026-05-14.md](../../../자유대화_실험_리뷰_종합_2026-05-14.md)
- 이전 안: v2 spec (`2026-05-14-agora-coordination-v2-design.md`) — 두 책임 공존 가정. v3에서 KV 제거로 변경.
- 결정 방식: Inst1 + 워커 7명 두 라운드 의견 수렴 + 정체성 결정 라운드(6명 압도적 옵션 C) → 사용자 확정

## v3에서 v2 대비 변경된 점

1. **AgentAgora를 메시지 채널 단일 책임 서버로 재정의** — KV (`agora.set/get/append/delete/list`, `schema.py`, `store.py`, `schemas.json`) 제거
2. **target 단일화 + broadcast 별 도구** — `target: str` (와일드카드 없음), `agora.broadcast` 신규 도구
3. **로그 형식**: `<name> Broadcast : payload` (broadcast 시), `<name> Announcement : payload` (broadcast + closing=True)
4. **priority enum 정렬 trap fix** — 문자열 DESC가 알파벳 순(`normal>low>high`)이라 의도와 정반대. enum→int 매핑으로 결정적 정렬
5. **cc + closing dead code fix** — cc 수신자가 closing 안 보내 양방향 closed 영원히 충돌. participants에 `role` 컬럼 추가, closed_by 검사는 `role='primary'`만
6. **last_message_at 갱신 누락 fix** — 모든 dispatch에서 UPDATE (close TTL 정상 동작)
7. **SQLite write 트랜잭션 경계 명시** — 단일 dispatch의 모든 SQL은 한 트랜잭션
8. **broadcast announcement 시맨틱** — broadcast + closing=True는 즉시 closed (1:N 발표 + N 답신 자유)
9. **envelope.closing이 single source of truth** — payload-level `type="closing"` deprecated
10. **결정 트레일 명시** (섹션 2.5) — 비대응 결정의 동기·비용·트리거 조건 추적
11. **self-dispatch 허용** (사용자 결정) — `target == source` 허용, v1 호환 + 워커 자율 루프 패턴 지원
12. **closed conversation 자동 대체 통일** (Inst5 V3) — 명시 지정·자동 상속 모두 새 UUID + `conversation_id_substituted=True` 마킹
13. **broadcast message_count 의미 명시** (Inst5 V2) — 논리적 메시지 1건, command_id 단위 카운트
14. **SQLite 트랜잭션 실패 시 일관성 정책** (Inst5 V4) — in-memory 상태 유지, 그 dispatch는 best-effort 손실
15. **_in_flight 재시작 복구** (Inst4 우려3) — 재시작 직후 peek/instances 정확
16. **_conversations cache GC** (Inst4 우려4) — message GC와 함께 in-memory pop, 메모리 누수 방지
17. **Dispatcher 생성자 시그니처 변경 명시** (Inst4 우려5) — `__init__(registry, persistence, default_timeout_ms)`, `create_agora_app(persistence=...)`
18. **envelope.py 신규 모듈** (Inst4 명확화) — dataclass + priority enum + payload size validate, dispatcher.py에 inline 거부 (200줄 → 300줄 비대 방지)
19. **announcement 로그 형식 확정** (Inst5 V8) — `[agora] {source} Announcement [conv:...] : ...`

---

## 1. 배경

8 인스턴스 자유대화 실험에서 AgentAgora가 멀티-에이전트 협업 채널로 **작동은 하지만**, 다자 동시 대화에서 5가지 운영 갭 + 6가지 운영 가드 누락이 드러났다.

또한 v1 README의 "공유 상태 저장소(KV) + 명령 채널" 두 책임 중 KV는 1·2라운드 자유대화 실험·모든 워커 deep dive·정체성 결정 라운드에서 **사용 0회**. Inst5의 grep 실측 확인. v3에서 KV는 제거하고 메시지 채널 단일 책임으로 재정의.

**갭 (실측)**:
1. 종료 신호 표준 부재 → wait 데드락 위험
2. 스레드 ID 부재 → 동시 교차 dispatch가 별개 task 2개로 인식
3. 부하 가시성 없음 → hub formation (Inst6에 4명 몰림)
4. 응답 우선순위 미정의 → 한 wait에 N개 도착 시 임의 처리
5. 수신자 활성 상태 가시성 부재 → consumer down 사후 인지

**운영 가드 누락 (Inst2 잡일러 발견)**:
1. instance_id squatting (register 인증 없음)
2. 페이로드 로그에 PII 노출 위험
3. 무한 큐 (백프레셔 없음, OOM 벡터)
4. dead-session 감지 부재
5. half-closed 의미 미정의
6. broadcast 권한 무제한

**비교 참고 (Inst3 researcher)**: A2A 프로토콜의 `contextId(대화) vs taskId(작업)` 분리 패턴이 갭 2에 정확히 대응.

## 2. 목표 / Non-goals

### 목표
- 5갭 모두 해소 (envelope + 서버 state + 신규 도구)
- 운영 가드 6건 v1에 포함
- 메시지·conversation 영속화로 재시작 견고성 확보
- AgentAgora를 메시지 채널 단일 책임 서버로 재정의
- KV 기능 제거 (350~400 LoC 감축)

### Non-goals
- 멀티 호스트 분산 (단일 서버 가정 유지)
- 인증·인가 (신뢰 도메인 가정 유지, squatting은 advisory 수준)
- 메시지 암호화
- conversation 머지 도구 (스레드 명시 합치기는 클라이언트가 conversation_id 명시 지정으로 해결)
- Web UI / 모니터링 대시보드
- KV (v3에서 제거). 미래에 필요해지면 요구사항에 맞게 재작성, 또는 별 패키지로 도입
- v1 KV 도구의 backward compat — v3 메이저 변경 (Inst5 R1 명시)

## 2.5 결정 트레일

비대응 결정(5갭에 직접 매핑되지 않으나 채택된 변경)의 근거·비용·대안·후속 검증 추적. Inst5 I6 권고.

| 결정 | 동기 | 비용 | 대안 | 후속 검증 트리거 |
|---|---|---|---|---|
| 메시지까지 SQLite 영속화 | 사용자 결정 (옵션 C), 재시작 견고성 | ~150~200 LoC, 마이그레이션 스크립트, GC 정책 | A(in-memory only), B(메타만 SQLite) | write queue 백로그 누적 실측 시 옵션 C→B 후퇴 검토 |
| 메시지 GC 90일 후 자동 삭제 | 사용자 결정 (기본값), 디스크 누적 방지 | 일 1회 background task, 감사 가치 일부 손실 | 영구 보존 / 30일 / disk size cap | 디스크 사용량 1GB 초과 시 30일로 단축 검토 |
| closing TTL 300s + 환경변수 | Inst2/Inst7 권장, half-closed zombie 방지 | background task 60s 주기, 정상 long-running task와 충돌 위험 | 미도입 (Inst5) / 120s (Inst6/Inst8) | half_closed → closed 자동 전이로 정상 task가 깨지는 사례 1회 실측 시 600s로 연장 검토 |
| payload 1MB hard cap | 사용자 결정, OOM·SQLite 부담 방지 | 큰 상태 동기는 별 매체 필요 | 256KB / cap 없음 | 1MB 초과 dispatch 거부 사례 5회 누적 시 256KB·512KB 재평가 |
| cc 필드 신설 | 사용자 결정 (Q5), 옵저버 시나리오 | participants 테이블에 role 컬럼, closed_by 검사 분기 | reply_to: list 확장 / 보류 | cc 사용 0회로 1개월 누적 시 제거 검토 |
| KV 제거 | 정체성 결정 라운드 6/7 합의, 사용 0회 | schema.py·store.py·5개 도구 제거 (~350~400 LoC), 마이그레이션 (외부 사용자 0이라 사실상 0) | A(유지) / B(prefix 분리) / D(별 패키지) | 향후 KV 같은 요구 발생 시 별 패키지 신설 |

## 3. 아키텍처 개요

**Hot path (메시지 라우팅)**: 기존 in-memory `_queues` / `_waiters` (asyncio future) 유지. dispatch/wait 응답성 영향 없음.

**Cold path (영속성·조회)**: SQLite (Python stdlib). 비동기 write는 `AsyncWriteQueue` 패턴 재활용 — v3에서는 `store.py` 제거되므로 패턴은 `persistence.py`로 이전 (Inst7 cross-coupling 경고 반영).

**상태 분리**:
- `_queues`, `_waiters`: in-memory (큐와 깨움)
- `_conversation_of: dict[command_id, conversation_id]`: in-memory 캐시 (in_reply_to 상속용)
- `_conversations: dict[conversation_id, ConversationState]`: in-memory 캐시
- `_in_flight: dict[instance_id, dict[cmd_id, set[pending_replyer_ids]]]`: peek/instances의 in_flight 메타 (Inst4 함정4 반영, primary 수신자만 카운트)
- `_last_dispatch_to: dict[instance_id, str]`: peek의 last_dispatch_to_at 추적
- SQLite: 영속 source of truth (재시작 시 위 dict들 복구)

WAL 모드. DB 위치: `<agora_dir>/.agentagora/agora.db`.

**KV 제거 후 디렉토리**: 기존 `<agora_dir>/.agentagora/schemas.json`은 무시(있어도 로드 안 함). startup에서 warning 한 줄 출력. agora_dir 자체는 유지 (db 파일 부모).

**Envelope 검증 인프라 보존** (Inst7 #1 우려): v1의 `schema.py:_BUILTIN_SCHEMAS.commands`가 메시지 envelope 검증에 묵시 사용되던 부분은 v3에서 `dispatcher.py` 또는 새 `envelope.py` 모듈로 inline 이동. JSON Schema 의존 대신 dataclass + 코드 수준 강제(타입·1MB·priority enum)로 전환. 회귀 테스트 카테고리에 envelope validation 추가.

## 4. Envelope 스키마

```python
# dispatcher.py:dispatch() 시그니처
async def dispatch(
    self,
    source: str,
    target: str,                               # 단일 instance_id. 와일드카드 없음
    payload: Any,                              # JSON serializable, ≤1MB
    expect_result: bool = False,
    reply_to: str | None = None,               # 단일 — 의무 답신자. None이면 source
    cc: list[str] | None = None,               # 옵저버. 답신 의무 없음, 자동 상속 안 함
    in_reply_to: str | None = None,
    conversation_id: str | None = None,
    closing: bool = False,
    priority: Literal["low", "normal", "high"] = "normal",
    deadline_ts: str | None = None,            # ISO8601, advisory
) -> dict[str, Any]

# dispatcher.py:broadcast() 시그니처 (별 도구)
async def broadcast(
    self,
    source: str,
    payload: Any,
    expect_result: bool = False,
    reply_to: str | None = None,
    in_reply_to: str | None = None,
    conversation_id: str | None = None,
    closing: bool = False,                     # True면 announcement → 즉시 closed
    priority: Literal["low", "normal", "high"] = "normal",
    deadline_ts: str | None = None,
) -> dict[str, Any]
```

**broadcast 시맨틱** (사용자 결정):
- 발신자 제외 모든 등록 인스턴스에 fan-out
- cc 인자 없음 (이미 전부에게 보냄)
- broadcast로 시작한 conversation은 단일 conversation_id (Inst6 announcement 시맨틱)
- `closing=True`인 broadcast = announcement → 모든 다른 participants 답신 의무 없이 conversation 즉시 closed

**Envelope (큐·SQLite 양쪽에 들어가는 dict)**:
```python
{
  "id": cmd_id,
  "source": str,
  "target": str,                       # broadcast/cc는 N행으로 fan-out, 각 행 target은 단일
  "payload": Any,
  "created_at": str,                   # ISO8601 UTC
  "expect_result": bool,
  "reply_to": str | None,
  "cc": list[str] | None,              # 모든 수신자가 동일 final list 본다 (중복 제거 후)
  "delivered_as": "primary" | "cc",
  "dispatch_kind": "direct" | "broadcast",  # 로그 형식·시맨틱 분기에 사용
  "in_reply_to": str | None,
  "conversation_id": str,              # 항상 채워짐 (서버 보장)
  "closing": bool,
  "priority": "low" | "normal" | "high",
  "deadline_ts": str | None,
  "wait_age_ms": int,                  # wait 응답에만 추가
}
```

**반환 값 (dispatch)**:
```python
{
  "command_id": str,
  "created_at": str,
  "conversation_id": str,
  "conversation_id_substituted": bool,        # 명시 conversation_id가 closed라 새로 발급된 경우 True
  "dispatched_to": [
    {"instance_id": "Inst3", "as": "primary"},
    {"instance_id": "Inst5", "as": "cc"},
    ...
  ],
  "target_inbox_depth_after": dict[str, int],
  "skipped_full": list[str],
}
```

**반환 값 (broadcast)**: dispatch와 동일 shape. `dispatched_to`의 모든 항목은 `"as": "primary"` (cc 없음).

## 5. Target / cc / Broadcast 시맨틱

### dispatch (1:1)
- `target: str` — 단일 instance_id. 와일드카드 미지원.
- `target`가 미등록 → `NotRegisteredError`.
- `target == source`는 **허용** (Inst2 발견 — v1 호환 + 워커 자율 루프 패턴 지원). 자기 큐에 nudge 메시지 enqueue로 stop-hook 재트리거 같은 패턴 가능.

### cc (옵저버)
- `cc: list[str]` — 명시 instance_id들. 빈 리스트는 None과 동치.
- `cc`에 나열된 인스턴스의 큐에도 동일 command가 enqueue, envelope에 `delivered_as: "cc"` 마킹. primary 수신자(target)는 `delivered_as: "primary"`.
- **cc 수신자는 답신 의무 없음**. CLAUDE.md 페이로드 규약에 "envelope의 `delivered_as == 'cc'`면 응답하지 않는 것이 기본" 명시.
- **cc는 자동 상속 안 함** (Inst8 R7): cc 수신자가 다음 dispatch에서 cc를 명시하지 않으면 옵저버 체인이 끊김. 폭주 방지.
- `cc`와 `reply_to`는 같은 instance_id 가질 수 없음 → `ValueError("instance cannot be both reply_to and cc")`.
- `cc`에 `source` 또는 `target` 포함 시 자동 제거 (중복 fan-out 방지).
- cc 수신자가 그 메시지에 응답하고 싶으면 새 dispatch를 일으키되 `in_reply_to`로 correlation 가능.

### broadcast (1:N 발표)
- 별 도구 `agora.broadcast`. `agora.dispatch`와 명시적 구분.
- 발신자 제외 모든 등록 인스턴스에 fan-out (현 v1 `_broadcast`와 동일 시맨틱).
- 단일 conversation_id 시작 (모든 수신자가 같은 conversation의 participants).
- **announcement 시맨틱** (Inst6): `closing=True`인 broadcast는 즉시 conversation closed. 1:N 발표 후 답신 의무 없는 자연 종료.

### `_broadcast` 매직 스트링 폐기
v1 `target=["_broadcast"]`은 v3에서 사용 시 ValueError + deprecation 안내. 한 마이너 동안 silent fallback(자동 `agora.broadcast` 호출 + warning 로그)도 고려 가능하나, 외부 사용자 0이므로 즉시 폐기 권장.

## 6. Conversation 모델

### 6.1 발급 규칙
- dispatch/broadcast에 `conversation_id` 미지정:
  - `in_reply_to`가 있고 부모 메시지가 있는 conversation을 알면 → 부모의 `conversation_id` 상속 (재시작 후 in-memory 캐시 미스 시 SQLite에서 `SELECT conversation_id FROM messages WHERE command_id=?` fallback — Inst4 함정2 + Inst2 fallback)
  - 그 외 → 서버가 새 UUID 발급
- `conversation_id`가 가리키는 conversation이 `closed` (명시 지정이든 자동 상속이든 어느 경우든): **새 UUID 발급으로 대체, 응답에 `conversation_id_substituted: true` 마킹 (Inst5 V3 fix — 통일 처리)**
- 워커는 응답의 `conversation_id_substituted=True` 보면 옛 conversation_id 폐기, 새 ID로 후속 dispatch 유지 (M4.2 워커 CLAUDE.md 안내 — Inst8 B2')
- broadcast는 단일 conversation_id로 모든 수신자가 같은 conversation의 participants

### 6.2 상태 머신
- `open` → `half_closed` → `closed`
- `closed`에서 reopen 없음. 같은 토픽을 이어가려면 클라이언트가 새 conversation을 시작.
- `half_closed`: 한 primary participant가 `closing=True`를 보낸 상태. `closing` 플래그는 **단방향 advisory 신호 — ack 불필요**. **단 single source of truth는 envelope.closing**, payload-level `type="closing"`은 deprecated (Inst6).
- `closed`: (a) 모든 **primary** participants가 각자 `closing=True`를 보냈거나 (cc는 카운트에서 제외 — Inst5 C1), (b) `half_closed` 상태로 `close_timeout` 경과 후 background task가 자동 전이, (c) broadcast announcement(`closing=True`)는 즉시 closed.

### 6.3 SQLite 스키마

```sql
CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('open','half_closed','closed')),
  started_at TEXT NOT NULL,
  last_message_at TEXT NOT NULL,
  closed_at TEXT,
  closed_by TEXT NOT NULL DEFAULT '[]',     -- JSON array of primary instance_ids
  message_count INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL DEFAULT 'direct' CHECK (kind IN ('direct','broadcast'))
);
CREATE INDEX idx_conv_status ON conversations(status);
CREATE INDEX idx_conv_last_msg ON conversations(last_message_at);

CREATE TABLE messages (
  command_id TEXT NOT NULL,
  target TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  source TEXT NOT NULL,
  in_reply_to TEXT,
  created_at TEXT NOT NULL,
  expect_result INTEGER NOT NULL DEFAULT 0,
  reply_to TEXT,                             -- 단일 instance_id | null
  cc TEXT,                                   -- JSON array | null
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc')),
  dispatch_kind TEXT NOT NULL DEFAULT 'direct' CHECK (dispatch_kind IN ('direct','broadcast')),
  closing INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
  priority_rank INTEGER NOT NULL DEFAULT 1   -- 정렬용 (Inst7 critical fix): high=0, normal=1, low=2
    CHECK (priority_rank IN (0,1,2)),
  deadline_ts TEXT,
  payload TEXT NOT NULL,
  drained_at TEXT,                           -- null이면 in-flight
  drop_reason TEXT CHECK (drop_reason IN ('server_restart','manual')),  -- Inst5 M1 fix
  PRIMARY KEY (command_id, target),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX idx_msg_conv ON messages(conversation_id);
CREATE INDEX idx_msg_source ON messages(source);
CREATE INDEX idx_msg_inflight ON messages(target, drained_at) WHERE drained_at IS NULL;
CREATE INDEX idx_msg_priority_sort ON messages(target, priority_rank, created_at, command_id);
CREATE INDEX idx_msg_created ON messages(created_at);

CREATE TABLE conversation_participants (
  conversation_id TEXT NOT NULL,
  instance_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'primary' CHECK (role IN ('primary','cc')),  -- Inst5 C1 critical fix
  joined_at TEXT NOT NULL,
  delivered INTEGER NOT NULL DEFAULT 1,      -- skipped_full 처리 시 0 (Inst5 I2)
  PRIMARY KEY (conversation_id, instance_id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX idx_cp_inst ON conversation_participants(instance_id);

CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
INSERT INTO schema_version VALUES (1, datetime('now'));
```

**priority enum → int 매핑** (Inst7 CRITICAL fix):
- Python: `_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}`. 정렬 키는 `(priority_rank asc, created_at asc, command_id asc)`.
- SQL: `priority_rank` 컬럼을 INSERT 시 함께 채움. ORDER BY는 그 컬럼 사용.
- 회귀 테스트로 단언 잠금: `test_priority_string_enum_orders_high_before_normal_before_low`.

## 7. 신규 MCP 도구

### 7.1 `agora.broadcast(payload, ...)` (신규)

`agora.dispatch`와 별 도구. 발신자 제외 모든 등록 인스턴스에 fan-out. 시그니처는 §4 broadcast 시그니처 그대로.

### 7.2 `agora.peek(targets: list[str] | "*") → dict`

부하 가시성. 단 `targets` 인자에서 `"*"`는 "모든 등록 인스턴스 조회" 의미 — dispatch target과 다른 도메인(query)이라 와일드카드 허용.

```python
@mcp.tool(name="agora.peek")
async def agora_peek(targets: list[str] | Literal["*"]) -> str:
    """Snapshot of pending queue and consumer activity per instance.
    ADVISORY ONLY — atomicity not guaranteed (TOCTOU race vs subsequent dispatch).
    Unregistered targets return registered=False, not error."""
```

**메타 추적 위치 (구현 노트)**:
- `queue_depth`: `len(self._queues[t])` 즉시 계산. CPython GIL로 단건 읽기 atomic. eventual consistency.
- `in_flight`: `_in_flight: dict[instance_id, dict[cmd_id, set[pending_replyer_ids]]]`. dispatch 시 `expect_result=True`이고 **primary 수신자만** pending set에 추가. reply 도착 시 source 제거.
- `last_wait_at`: `InstanceRegistry.last_seen_at`.
- `last_dispatch_to_at`: `_last_dispatch_to: dict[instance_id, str]`, dispatch 시 갱신.
- `wait_mode`, `accepting`: `InstanceInfo` 필드.

반환:
```python
{
  "Inst3": {
    "registered": True,
    "queue_depth": 3,
    "in_flight": 1,
    "last_wait_at": "2026-05-14T...",
    "last_dispatch_to_at": "2026-05-14T...",
    "wait_mode": "auto" | "manual" | "unknown",
    "accepting": True,
  },
  "Inst99": {
    "registered": False,
    "queue_depth": None, "in_flight": None,
    "last_wait_at": None, "last_dispatch_to_at": None,
    "wait_mode": None, "accepting": None,
  }
}
```

### 7.3 `agora.conversation_status(conversation_id: str) → dict`

특정 대화 상태 조회. `closed` 후에도 (GC 전까지) 조회 가능. **Advisory only** (TOCTOU — Inst7 #7).

```python
{
  "conversation_id": "...",
  "kind": "direct" | "broadcast",
  "status": "open" | "half_closed" | "closed",
  "participants": [
    {"instance_id": "Inst1", "role": "primary"},
    {"instance_id": "Inst5", "role": "cc"},
    ...
  ],
  "started_at": "...",
  "last_message_at": "...",
  "closed_at": "..." | None,
  "closed_by": ["Inst3"],            # primary 중 closing 보낸 자
  "message_count": 12,
}
```

존재하지 않으면 `{"error": "unknown_conversation"}`.

### 7.4 `agora.conversations_list(participant: str | None = None, status: str | None = None, limit: int = 100) → list`

진행 중·종료 대화 인덱스. SQLite 쿼리.
- `participant`: 그 instance_id가 끼인(primary 또는 cc) 대화만
- `status` 필터
- `limit`: 기본 100, 최대 1000
- 반환: `last_message_at DESC` 순.

### 7.5 `agora.close_thread(conversation_id: str, reason: str = "") → dict`

명시적 종료 도구. 호출자가 그 conversation에 `closing=True` 메시지를 모든 다른 **primary** participants에게 dispatch한 것과 동치. cc participants에는 발송 안 함 (closed_by 카운트에 포함 안 되므로 의미 없음). 페이로드: `{"type": "closing", "from": "<caller>", "reason": "..."}`.

```python
{"status": "closed" | "half_closed" | "already_closed", "conversation_id": "..."}
```

이미 `closed`면 idempotent. **caller가 participants에 없으면 ValueError("not_a_participant")** (Inst5 I5).

**close_thread + max-inbox-depth 상호작용** (Inst8 B5): 내부적으로 broadcast 부분 성공 정책 적용 — 일부 primary participant 큐가 가득 차면 그 participant에는 발송 실패, 응답 dict에 `skipped_full: list[str]` 명시.

**워커 처리 부담 안내**: closing envelope이 수신자 큐에 들어가지만 `envelope.closing=True`이므로 수신자는 응답 의무 없음. 워커 CLAUDE.md 규약에 "closing 수신 시: 더 보낼 메시지 없으면 다음 dispatch에 closing=True 동봉 권장 (즉시 종료). 아무 것도 안 하면 5분 후 자동 closed" 안내 (Inst2 발견).

## 8. 갱신된 기존 도구

### 8.1 `agora.dispatch` — 시그니처 확장

- 신규 인자: `cc`, `conversation_id`, `closing`, `priority`, `deadline_ts`
- `target`은 단일 str (와일드카드 없음)
- 반환에 `conversation_id`, `conversation_id_substituted`, `dispatched_to` (primary+cc 합산), `skipped_full` 추가
- v1 `target=["_broadcast"]` 호출 → ValueError (대신 `agora.broadcast` 사용)

### 8.2 `agora.wait` — 응답 확장 + 정렬 보장

- 신규 인자: `by_conversation: str | None = None`, `sort: Literal["fifo","priority"] = "fifo"`
- 응답의 각 command에 `conversation_id`, `priority`, `wait_age_ms` 추가
- 정렬 키 (**Inst7 critical fix**):
  - `sort="fifo"` (기본): `(created_at asc, command_id asc)`
  - `sort="priority"`: `(priority_rank asc, created_at asc, command_id asc)` — high(0) → normal(1) → low(2) 순. tie-breaker는 created_at, 그것도 동률이면 command_id 사전순으로 결정적.
- 두 필터(`from_sources`, `by_conversation`) 동시 지정 시 **AND** 결합 (Inst4 함정7)
- wait 호출 시 `last_seen_at` 자동 갱신

### 8.3 `agora.instances` — 부하 메타 노출

응답의 각 instance entry에 추가:
```python
{
  "instance_id", "role", "description", "registered_at",
  "inbox_depth": int,
  "in_flight": int,              # primary 수신자만 카운트
  "last_seen_at": str | None,
  "wait_mode": "auto" | "manual" | "unknown",
  "accepting": bool,
}
```

### 8.4 `agora.register` — wait_mode 명시

신규 인자: `wait_mode: Literal["auto","manual"] | None = None`. None이면 `"unknown"`.

**헤더 자동 등록 일관성**: `X-Agora-Wait-Mode` 헤더 추가. `AutoRegisterMiddleware`(server.py에 ASGI 미들웨어로 신규 또는 기존 확장 — Inst4 함정6 + Inst2 발견)가 첫 요청에서 헤더 보고 자동 설정. 명시 `agora.register` 인자가 헤더 값보다 우선.

## 9. Closing 프로토콜 시맨틱

- `envelope.closing` (bool)이 **single source of truth** (Inst6). payload-level `type="closing"`은 deprecated, 워커 CLAUDE.md에서 사용 금지.
- `closing=True`는 **단방향 advisory**. 받은 쪽 ack 의무 없음.
- 모든 **primary** participants가 각자 `closing=True`를 보냈을 때 즉시 `closed` (cc는 카운트 제외 — Inst5 C1).
- broadcast의 `closing=True` = **announcement** → 즉시 closed (Inst6).
- `half_closed` 상태에서 `--close-timeout-ms` (기본 **300000ms = 5분**) 경과 시 background task가 자동 `closed` 전이.
- TTL 카운트 시작점: `half_closed`로 진입한 시각 (= 가장 최근 `closing=True` 메시지의 `created_at`).
- TTL 카운트 갱신: half_closed 상태에서 새 메시지가 도착하면 TTL 리셋. 닫지 않은 일반 메시지도 정상 활동 신호로 간주.
- `close_thread` 도구 호출은 closing 메시지 발신과 동등.

## 10. 운영 가드 (must-add 6건 + 추가 운영 규약)

### 10.1 instance_id squatting
- 같은 instance_id로 register 시도 시: 기존 entry의 `last_seen_at`이 `--squat-window-ms` (기본 30000ms) 이내면 거부 (`ValueError("instance_id_in_use")`). 초과면 기존 entry 자동 unregister 후 신규 등록 허용.
- README에 "신뢰 도메인 가정 — 인증은 v3 범위 밖" 명시.

### 10.2 PII 로그 redact
- CLI 플래그 `--redact-payloads`. 활성 시 dispatch 로그 payload 자리에 `<len=N bytes>` 출력.
- 기본 비활성 (개발 친화).

### 10.3 max-inbox-depth
- CLI 플래그 `--max-inbox-depth` (기본 100).
- dispatch 시 타깃의 `len(self._queues[t]) >= max_depth`면 직접 dispatch는 `ValueError("inbox_full")`, broadcast/cc는 그 target만 `skipped_full`로 분리, 다른 target에는 정상 dispatch (부분 성공).
- cc inbox_full 처리: 항상 skipped_full로 분리 (Inst5 I2 + Inst2 발견). participants 테이블의 그 행은 `delivered=0`으로 마킹 → closed_by 카운트에서도 제외.

### 10.4 registry.last_seen 자동 갱신
- wait 호출 진입 시 `InstanceRegistry.touch_last_seen(instance_id)` 호출.

### 10.5 dead-session GC
- CLI 플래그 `--dead-session-timeout-ms` (기본 1800000ms = 30분).
- Background task 60초마다: `last_seen_at`이 timeout 초과면 `unregister_session()` 호출. 인스턴스 대상의 in-flight 메시지는 그대로 큐·SQLite에 남김 (재등록 시 받게 됨).

### 10.6 half-closed 명문화
- README와 워커 CLAUDE.md 페이로드 규약에 "closing=True는 단방향 advisory 신호 — ack 불필요. 양방향 primary 도달 시 closed, 한쪽만이면 half_closed (5분 후 자동 closed)" 명시.

### 10.7 priority 인플레이션 advisory (Inst5 M2 + Inst8 B1)
- `agora.dispatch` docstring + 워커 CLAUDE.md: "priority='high'는 실제 차단 사유(데드라인 임박, 사용자 대기)에만. 기본은 normal." 명문화.
- 인플레이션 quota는 v2 후보 (섹션 17). v3는 자율 준수 + 사후 audit.

### 10.8 wait_mode advisory 사후 검증 (Inst8 B4)
- `agora.instances` 응답에 `last_seen_at` 노출. 발신자가 `wait_mode="auto"`라고 보고된 인스턴스의 `last_seen_at`이 60초 이상 차이나면 advisory inconsistent 신호로 판단 가능 (운영 규약, 코드 enforce 안 함).

## 11. 데이터 흐름

### 11.1 dispatch (direct, 1:1)
1. validate: caller registered? target 형식·미등록? cc 형식·미등록? `cc ∩ {reply_to}` 빈 집합? `target == source`? payload ≤1MB? (1MB 측정: `len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))`)
2. cc - target 중복 제거: 같은 instance_id가 target과 cc 양쪽에 있으면 target(primary) 우선, cc 명단에서 제거. cc에 source 포함되면 제거.
3. inbox depth 체크 → primary target은 가득 차면 ValueError, cc는 가득 찬 항목만 skipped_full로 분리.
4. conversation_id 결정 (§6.1).
5. conversation 신규면 in-memory `_conversations[conv_id] = ConversationState(...)` 동기 추가, SQLite INSERT는 AsyncWriteQueue (race 방지 위해 in-memory 즉시 + SQLite eventually — Inst4 함정3).
6. 모든 dispatch에서 `conversation_participants` INSERT OR IGNORE: source(primary), target(primary), cc 각 instance_id(cc role, delivered=0 if skipped_full). joined_at=now (Inst5 I1).
7. envelope 만들고 `_queues[t].append(envelope)` — primary는 `delivered_as="primary"`, cc는 `delivered_as="cc"`. 둘 다 동일 command_id·conversation_id·payload·priority·priority_rank.
8. `_conversation_of[cmd_id] = conversation_id` 캐시 적재.
9. `AsyncWriteQueue.submit_transaction([INSERT messages, UPDATE conversations.last_message_at, ...])` (Inst5 I4: 단일 트랜잭션) — 단계 5/6/9의 모든 SQL은 한 트랜잭션으로 commit, FK 일관성 보장.
10. `conversations.last_message_at = now, message_count += 1` UPDATE (모든 dispatch마다 — Inst5 I3 critical fix).
11. `closing=True`고 source가 primary면 `conversations.closed_by` JSON에 source 추가. 모든 primary participants(role='primary' AND delivered=1)가 closed_by에 포함되면 status='closed' UPDATE.
12. waiter 깨움 (primary + cc 모두).
13. 로그 1줄: `[agora] {source} -> {target} (cc: {cc_list}) [conv:{cid[:8]} pri:{priority} closing:{closing}] : {payload}`. cc 없으면 `(cc: ...)` 생략. closing=False, priority=normal이면 그 메타도 생략 (가독성). `--redact-payloads` 활성 시 `{payload}` → `<len=N bytes>` (Inst2 발견).
14. 반환.

### 11.2 broadcast
- 위 dispatch flow의 1~13단계와 동일, 차이점:
  - target 결정: self 제외 모든 등록 인스턴스. 각각 primary로 enqueue.
  - cc 무시 (broadcast는 이미 전부).
  - conversations.kind='broadcast'.
  - **message_count는 +1** (Inst5 V2 fix): broadcast가 messages 테이블에 N행을 만들지만 논리적 메시지는 1건. 카운트 키는 `command_id` 단위, target 단위 아님.
  - 로그 형식 (Inst5 V8 확정):
    - closing=False: `[agora] {source} Broadcast [conv:{cid[:8]} pri:{priority}] : {payload}`
    - closing=True: `[agora] {source} Announcement [conv:{cid[:8]} pri:{priority}] : {payload}` (announcement 시맨틱 가시화)
  - closing=True 시 announcement → 단계 11에서 모든 primary가 close 안 보내도 즉시 status='closed' UPDATE (Inst6).

### 11.3 wait
1. validate: caller registered?
2. `_drain_matching` → 정렬 적용 (priority_rank/created_at/command_id 사전순).
3. `last_seen_at` 갱신 (Registry).
4. drained 각 envelope에 `wait_age_ms = now - created_at` 계산해 첨부.
5. `AsyncWriteQueue.submit_drained_update(command_ids, target)`. (in-flight 인덱스에서 자동 제외됨)
6. primary 수신자라면 `_in_flight[primary][cmd_id]`에서 자기 pending 항목 제거. set 빈 후 dict key 제거.
7. 반환.

### 11.4 Background tasks
- **close TTL** (60초 주기): `UPDATE conversations SET status='closed', closed_at=now WHERE status='half_closed' AND last_message_at < now - close_timeout`. 영향받은 conversation의 in-memory cache도 갱신.
- **dead-session GC** (60초 주기): registry 순회, `last_seen_at` 초과면 unregister.
- **message GC** (일 1회, `--gc-hour` 기본 03:00 UTC): `DELETE FROM messages WHERE conversation_id IN (SELECT conversation_id FROM conversations WHERE status='closed' AND closed_at < now - 90d)`. `conversations` 메타는 보존. **in-memory `_conversations`/`_conversation_of` cache eviction** (Inst4 우려4 fix): GC 대상 conversation_id 리스트를 메모리 dict에서도 pop. cmd_id 키 기반인 `_conversation_of`는 `WHERE conversation_id IN deleted_ids` 추가 SELECT 후 cmd_id 집합 일괄 제거. 운영 1년 후 누수 방지.

### 11.5 재시작 복구
1. `agora.db` 없으면 신규 생성, schema 적용.
2. 있으면 schema_version 체크 후 마이그레이션. `INSERT OR IGNORE INTO schema_version` 사용 (Inst5 V7 fix — 매 startup PK violation 방지).
3. JOIN으로 한 번에 — `SELECT m.* FROM messages m JOIN conversations c ON m.conversation_id=c.conversation_id WHERE m.drained_at IS NULL AND c.status != 'closed'` (Inst4 함정5) → 각 행을 envelope으로 복원해 `_queues[target].append()`. closed conversation의 in-flight 메시지는 자동 제외.
4. closed conversation의 in-flight 메시지가 있다면 `UPDATE messages SET drained_at=now, drop_reason='server_restart' WHERE ...` (Inst5 M1 — sentinel을 별도 drop_reason 컬럼으로 분리).
5. `_conversation_of`, `_conversations` 캐시는 lazy load (필요 시점에 SQLite 쿼리).
6. `_in_flight` 재구축 (Inst4 우려3 fix): `SELECT m.target, m.command_id, m.source FROM messages m JOIN conversations c ON m.conversation_id=c.conversation_id WHERE m.drained_at IS NULL AND m.expect_result=1 AND m.delivered_as='primary' AND c.status != 'closed'`. 각 행에 대해 `_in_flight[target].setdefault(cmd_id, set()).add(target)` 형태로 pending replyer 집합 재구축. 재시작 직후 peek/instances의 in_flight가 정확.

## 12. 에러 처리

| 케이스 | 응답 |
|---|---|
| target 미등록 | `NotRegisteredError` |
| target == source | 허용 (self-dispatch — 자율 루프 패턴 지원, v1 호환) |
| broadcast 호출자만 등록 인스턴스 | `dispatched_to=[]`, `command_id` 발급, conversation 시작 (감사). `closing=True`면 conversation 즉시 `closed`로 INSERT (message_count=0) — Inst5 V6 fix |
| target에 `_broadcast` 또는 `"*"` 같은 v1 syntax | `ValueError("use agora.broadcast for fan-out")` |
| reply_to == 어느 cc 원소 | `ValueError("instance cannot be both reply_to and cc")` |
| cc에 미등록 instance_id | `NotRegisteredError` |
| payload > 1MB | `ValueError("payload_too_large: {n} bytes > 1048576")` |
| primary 큐 가득 | `ValueError("inbox_full")` |
| cc 큐 가득 | 부분 성공, `skipped_full`에 포함 |
| sqlite write 실패 | 로그 기록 + 메시지는 in-memory 큐에 남음 (**best-effort write — retry 없음, sqlite 실패한 메시지는 재시작 시 복원 불가**. hot path는 차단하지 않음). **in-memory `_conversations`/`_conversation_of`/`_in_flight`는 그대로 유지 (메모리 내 일관성)** — 재시작 시 SQLite에서만 복구되므로 그 dispatch는 영영 손실 (의도된 best-effort 정책 — Inst5 V4 fix). 일관성 강화는 v3.1 후보 (섹션 18 open issues) |
| 재시작 후 복원한 메시지의 conversation이 closed | JOIN으로 자동 제외, `drained_at=now, drop_reason='server_restart'` (Inst5 M1) |
| close_thread를 미등록 conversation_id에 호출 | `{"error": "unknown_conversation"}` |
| close_thread caller가 participants에 없음 | `ValueError("not_a_participant")` (Inst5 I5) |
| deadline_ts 만료 메시지 | 서버 enforce 안 함 (advisory). wait이 그대로 반환하며, 클라이언트는 `wait_age_ms`와 `deadline_ts`로 판단 |

## 13. CLI 플래그 (신규)

```
agent-agora ...
  --max-inbox-depth N             # 기본 100, 0이면 무한
  --close-timeout-ms N            # 기본 300000 (5분)
  --dead-session-timeout-ms N     # 기본 1800000 (30분)
  --squat-window-ms N             # 기본 30000
  --gc-retention-days N           # 기본 90
  --gc-hour H                     # 기본 3 (UTC)
  --redact-payloads               # 기본 off
  --db-path PATH                  # 기본 <agora_dir>/.agentagora/agora.db
```

## 14. v1 → v3 Migration

v3는 **메이저 변경** — backward compat 약속은 메시지 채널 시그니처에만 한정.

**제거된 것**:
- 도구: `agora.set`, `agora.get`, `agora.append`, `agora.delete`, `agora.list` — 호출 시 unknown_tool 에러
- 모듈: `schema.py`, `store.py`
- 설정: `<agora_dir>/.agentagora/schemas.json` — 있어도 startup에서 warning 후 무시
- 빌트인 스키마: `instances`, `commands`, `results` — SQLite 테이블로 대체

**메시지 채널 backward compat**:
- v1 클라이언트가 신규 envelope 필드를 미지정하면 default로 동작. 응답에 신규 필드 항상 포함 (unknown 필드 무시 가정한 클라이언트만 호환).
- v1 `target=["_broadcast"]` 호출은 ValueError + 안내 ("use agora.broadcast"). 외부 사용자 0이라 silent fallback 비제공.

## 15. 테스트 전략

### 15.1 회귀 (Inst7 9개 → 변경 사항 반영)
- `test_dispatch_wait_unchanged_when_new_optional_fields_omitted` (golden test)
- `test_conversation_id_inherited_across_multi_hop_chain`
- `test_crossing_dispatch_without_conv_id_creates_distinct_ids`
- `test_explicit_same_conversation_id_merges_crossing_threads`
- `test_closing_one_side_half_closed_both_sides_closed` — **primary만 카운트** 단언 (Inst5 C1)
- `test_priority_string_enum_orders_high_before_normal_before_low` — Inst7 critical fix
- `test_peek_unregistered_target_returns_registered_false_not_error`
- `test_expired_deadline_message_still_delivered_as_advisory`
- `test_priority_mode_orders_broadcast_and_direct_dispatch_deterministically`
- (Inst2) `test_squatting_within_window_rejected`
- (Inst2) `test_max_inbox_depth_dispatch_rejected_when_full`

### 15.2 사용자 결정 invariant 잠금 (Inst7 신규)
- `test_cc_recipients_receive_message_but_correlation_targets_reply_to_only`
- `test_cc_overlap_with_reply_to_rejected`
- `test_broadcast_with_cc_arg_rejected` (broadcast는 cc 인자 자체 없음)
- `test_dispatch_to_closed_conversation_id_substituted_with_new_uuid` — `conversation_id_substituted=True` 단언
- `test_auto_inherit_to_closed_conversation_returns_substituted_true` (Inst5 V3 추가)
- `test_legacy_underscore_broadcast_target_normalized_or_rejected` — v3는 ValueError
- `test_broadcast_announcement_closing_true_immediately_closes_conversation` — envelope.closing=True 보존 단언 포함 (Inst7 우려3)
- `test_broadcast_fans_out_to_all_others_with_single_conversation_id_and_kind_marker` (Inst7 happy path) — dispatched_to 길이/conversation_id/dispatch_kind/delivered_as 4단언
- `test_broadcast_message_count_increments_by_one_not_n` (Inst5 V2 fix 회귀)
- `test_cc_participants_excluded_from_closed_by_count` (Inst5 C1)
- `test_last_message_at_updated_on_every_dispatch` (Inst5 I3)
- `test_single_dispatch_sqlite_writes_atomic_or_all_rollback` (Inst5 I4)
- `test_self_dispatch_target_equals_source_allowed` (사용자 결정 invariant)

### 15.3 신규 도구 양성 케이스 (Inst7)
- `test_peek_returns_accurate_queue_depth_and_in_flight_count_for_registered_target`
- `test_conversation_status_returns_correct_participants_and_message_count_for_open_conv`
- `test_conversation_status_returns_unknown_conversation_error_for_missing_id`
- `test_conversations_list_filters_by_participant_and_status_ordered_by_last_message_desc`
- `test_close_thread_is_idempotent_returns_already_closed_on_repeat_call`
- `test_close_thread_dispatches_closing_envelope_to_other_primary_participants_only`
- `test_close_thread_caller_not_in_participants_raises_not_a_participant`

### 15.4 경계 케이스 (Inst7)
- `test_broadcast_dispatch_with_partial_inbox_full_dispatches_to_remaining_with_skipped_full_list`
- `test_target_inbox_depth_after_reflects_actual_queue_state_post_dispatch`
- `test_wait_age_ms_calculation_matches_now_minus_created_at_within_tolerance` (monkeypatch clock)
- `test_broadcast_with_zero_other_registered_instances_returns_empty_dispatched_to_no_error`

### 15.5 영속화·복구 + 동시성 (Inst7)
- `test_restart_recovery_restores_inflight_messages`
- `test_restart_recovery_drops_closed_conversation_messages` — drop_reason='server_restart' 단언
- `test_message_gc_deletes_after_90_days_preserves_meta` (monkeypatch clock)
- `test_async_write_queue_does_not_block_hot_path_under_burst_dispatch`
- `test_async_write_queue_bounded_or_documented_unbounded` (Inst7 invariant)

### 15.6 TTL
- `test_half_closed_auto_close_after_timeout`
- `test_half_closed_ttl_resets_on_new_message`

### 15.7 운영
- `test_dead_session_gc_unregisters_after_timeout`
- `test_redact_payloads_logs_only_length`
- `test_payload_size_cap_rejects_over_1mb`

### 15.8 KV 제거 (v3 신규)
- `test_v1_kv_tools_removed` — `agora.set/get/append/delete/list` 호출이 unknown_tool 에러
- `test_legacy_schemas_json_present_warned_but_ignored`

### 15.9 envelope validation (Inst7 우려 반영)
- `test_envelope_validation_rejects_unknown_priority`
- `test_envelope_validation_rejects_invalid_iso_deadline_ts`
- `test_dispatch_inserts_priority_rank_consistent_with_priority_string_field` (Inst7 우려2 — dispatch(priority='high') → SQLite priority_rank=0)

## 16. 구현 마일스톤

Inst8 시퀀싱 채택 + M0 단계 추가 (KV 제거).

### Critical path
`M0 → M1 → M2 → M3 → M4`. 부분 병렬 가능.

### M0 — KV 제거 (T+30~60분, owner: Inst4)
- M0.1 `schema.py` 제거. `_BUILTIN_SCHEMAS.commands`의 envelope 검증 부분은 `dispatcher.py` 또는 신규 `envelope.py`로 inline 이동
- M0.2 `store.py` 제거. `AsyncWriteQueue` 패턴은 신규 `persistence.py`로 이전
- M0.3 `server.py`에서 `agora.set/get/append/delete/list` 도구 5개 + `_RESERVED_SCHEMA_NAMES` 제거
- M0.4 `__main__.py`에서 `SchemaRegistry.load(agora_dir)` 호출 제거 + schemas.json 발견 시 warning 출력만
- M0.5 KV 관련 테스트 fixture·케이스 제거
- M0.6 README의 KV 섹션 제거, 정체성 한 줄 재작성

**Inst2 권장 PR 분리**: M0를 별 PR로 분리 → 머지 → 안정화 → M1 진입. 회귀 원인 분간 용이.

### M1 — v3 메시지 채널 코드 (T+240~300분, owner: Inst4)
- M1.1 `registry.py`: `InstanceInfo` 확장 (wait_mode/last_seen_at/accepting) + `touch_last_seen()` 메서드
- M1.2 `persistence.py` 신규 (Inst4 구체화): `Persistence` 클래스 (sqlite3.connect + WAL pragma) + `migrate()` + `AsyncWriteQueue.submit_transaction(stmts: list[tuple[sql,params]])` (BEGIN/EXEC*/COMMIT 단일 트랜잭션) + `restore_inflight()` + `restore_in_flight_pending()` + `lookup_conversation_for(cmd_id)` (함정2 폴백) + `close()`. ~150~200 LoC
- M1.3 `envelope.py` 신규 (Inst4 명확화): `@dataclass(frozen=True) Envelope`(16필드) + `_PRIORITY_RANK={"high":0,"normal":1,"low":2}` + `validate_payload_size(payload)→bytes` (직렬화 1회) + `validate_priority(p)→rank` + `make_envelope(...)` (primary/cc 분기, delivered_as 마킹). ~80~100 LoC. v1에는 명시적 envelope 검증 없음 — v3 신규 추가에 가까움
- M1.4 `dispatcher.py`: 시그니처 확장 + state(`_conversation_of`, `_conversations`, `_in_flight`, `_last_dispatch_to`) + write hook + 정렬 (priority_rank) + half-closed 전이 + `broadcast()` 별 메서드. **생성자 시그니처 변경** (Inst4 우려5): `Dispatcher.__init__(registry, persistence, default_timeout_ms=60000)`. self._lock 보유 중에 in-memory state 추가 (Inst2 우려5)
- M1.5 `server.py`: `agora.dispatch/wait/instances/register` 갱신 + `agora.broadcast/peek/conversation_status/conversations_list/close_thread` 신규. **`create_agora_app` 시그니처에 `persistence` 인자 추가** (Inst4 우려5)
- M1.6 `auto_register.py` (Inst2/Inst4 함정6): `X-Agora-Wait-Mode` 헤더 파싱 추가
- M1.7 `__main__.py`: `Persistence` 인스턴스 생성 + `persistence.migrate()` 호출 + `dispatcher`에 주입. 신규 CLI 플래그 (max-inbox-depth, close-timeout-ms, dead-session-timeout-ms, squat-window-ms, gc-retention-days, gc-hour, redact-payloads, db-path)

**M0/M1 PR 전략** (Inst8 B3'): M0(KV 제거)와 M1 별 PR. M0.2(`store.py` 제거 + `AsyncWriteQueue` 이전)는 M1.2와 같은 PR로 묶거나 M0에서 `persistence.py` 스켈레톤만 만들고 M1에서 채우는 stub-first 정책. 시작 전 Inst4 결정.

### M2 — Background tasks + TTL (T+90분, owner: Inst4)
- M2.1 close TTL 자동 cleanup (60s 주기)
- M2.2 dead-session GC (60s 주기)
- M2.3 message GC (일 1회)
- M2.4 priority 인플레이션 advisory docstring 강화

### M3 — 테스트 (T+150분, owner: Inst7, M1 시작 후 병렬 가능 from M1.5)
- §15 전수 (15.1~15.9)
- backward compat golden test 강화
- KV 제거 후 envelope validation 회귀 (Inst7 #1 우려 반영)

### M4 — 문서 (T+90~120분, owner: Inst6, M0 후 시작 가능)
- M4.1 README 전면 재작성 — "공유 상태 + 명령 채널" → "multi-agent message-routing MCP server with conversation + persistence". **한국어 유지** (Inst6 발견), 영문 코드 식별자는 그대로. **v1 → v3 history 단락** 추가 (Inst6 W3)
- M4.2 워커 CLAUDE.md 7개 갱신:
  - 페이로드 규약 v3 블록 (envelope 4신규 필드 + cc + delivered_as)
  - closing 수신 시 권장 행동 (Inst2 발견)
  - priority='high' 사용 규약 (실제 차단 사유만)
  - wait_mode='manual' 인스턴스 처리 권장 (5초 grace)
  - cc 비상속 명시
  - 페르소나 vs v3 공통 규약 우선순위: v3 공통 우선, 페르소나는 추가 규약 (Inst6 A의 [부분] 항목)
  - payload-level type="closing" deprecated 안내
  - **broadcast vs dispatch 결정 가이드** (Inst8 B1' + Inst6 W1): "broadcast는 announcement(1:N 발표·공지)에만, 답신 기대하는 fan-out은 dispatch + cc"
  - **`conversation_id_substituted=True` 응답 처리 규약** (Inst8 B2'): 옛 ID 폐기, 새 ID로 컨텍스트 갱신
  - **dispatch + 대규모 cc vs broadcast 임계 advisory** (Inst5 V1): cc가 등록 인스턴스의 50% 초과면 broadcast로 옮기는 게 시맨틱 정합
  - **broadcast(closing=False) 답신 의무** (Inst5 V5): `expect_result=True`면 답신 권장, False면 답신 선택
  - **redact-payloads 디버깅 영향 안내** (Inst6 W4): 호스트 측에 확인 요청
  - **payload-envelope 동명 회피 권고** (Inst6 W5): conversation_id/closing/priority/in_reply_to를 payload 키로 쓰지 않기
  - **명시 N명에게 같은 conversation 분기 dispatch 패턴** (Inst4 우려1): 첫 dispatch 응답 conversation_id를 두 번째에 명시 지정
  - **2명 동시 task 의뢰 가이드** (Inst2 발견): conversation_id 명시 지정으로 묶기
- M4.3 v1 종합 문서 사실관계 8건 패치 (D 표) — 일괄
- M4.4 v2 spec을 archived/historical로 마킹

### M5 — 코드 리뷰 + 라이브 검증 (T+180분)
- M5.1 코드 리뷰 — owner: Inst5
- M5.2 라이브: 자유대화 v3 라운드 재실행, 5갭 실측 해소 확인 — owner: Inst3 (모니터링) + Inst2 (참여)

### Effort 총합 (병렬 가정)
- Sequential floor: M0 + M1 + M2 + M5 = ~7시간
- Parallel total: M3·M4가 M1.5 이후 병렬 → ~5~6시간

## 17. Out of scope (v3.1+ 후보)

- 멀티 호스트 분산 / replication
- 인증·인가
- 메시지 암호화
- conversation 머지·분기 도구
- broadcast rate-limit per source
- in-flight 메시지의 deadletter 큐
- priority 인플레이션 quota (자동 차단)
- 페이지네이션 (conversations_list)
- conversation_status TTL (현재는 GC 전까지 무한 조회 가능)
- conversation 명시 머지 도구
- 외부 KV 저장소 (별 패키지로 — 필요해지면)

## 18. Open issues

- **(Inst8 R1)** 메시지 영속화 conversations/messages 테이블이 mini-KV 우회로로 활용될 위험 → 본 spec에 "메시지/대화 영속화는 외부 KV 노출 금지. 신규 도구로 외부 데이터 저장 채널 만들지 말 것" 명시. v3.1 reviewer가 후속 노출 도구를 거부할 근거.
- **(Inst8 R2)** schemas.json 디렉토리 컨벤션 — v3에서 무시·warning. agora_dir 컨셉은 유지 (db 부모).
- **(Inst7 #6 + Inst5)** 사용자가 본인 도메인 의미로 conversation_id 같은 이름의 메타 필드를 페이로드에 넣는 경우 — payload는 free-form JSON이므로 envelope 필드와 분리됨. 별도 정의 충돌 없음.
- **(Inst7 #7)** peek + conversation_status 모두 advisory only — TOCTOU race 가능. 동기화 용도 아님 README 명시.
- **(Inst5 M3, Inst8 B3)** schema.py builtin commands 갱신 작업이 M0의 schema.py 제거로 자연 해결. 단 envelope.py 신규 도입 시 schema 정의가 코드 dataclass에 명시되어야 자기 문서화.
- **(Inst7 우려5)** `conversation_id_substituted=True`는 dispatch 응답에만 노출, envelope에는 없음 — cc/primary 수신자는 substitute 사실을 envelope으로 알 수 없음. 의도된 비대칭, 수신자는 새 conversation으로 인지하면 충분.
- **(Inst2 발견)** `conversation_status`·`conversations_list`는 권한 가드 없음 — 같은 호스트 동일 신뢰 도메인 가정. 미래 인증 도입 시 participant-only 가시성으로 변경 가능 (v3.1+ 후보).
- **(Inst2 발견)** broadcast 발신 측 rate-limit은 v3에서 의도적 미도입 — 외부 사용자 0, 자율 준수 가능. 라이브 검증에서 폭주 실측 1회 시 v3.1 도입 트리거. 결정 트레일 §2.5에 추가됨.

## 19. 참고 자료

- v1 자유대화 1라운드: [자유대화_실험_결과_2026-05-14.md](../../../자유대화_실험_결과_2026-05-14.md)
- v1 자유대화 2라운드 (디자인 리뷰): [자유대화_실험_리뷰_종합_2026-05-14.md](../../../자유대화_실험_리뷰_종합_2026-05-14.md)
- 이전 spec (v2): [2026-05-14-agora-coordination-v2-design.md](2026-05-14-agora-coordination-v2-design.md) — 두 책임 공존 가정, v3에서 폐기
- A2A 프로토콜 contextId 모델 (Inst3 비교)
- 정체성 결정 라운드 워커 회신: command_id `d8c868ed-8703-4722-be1f-a96449273963`의 응답들
