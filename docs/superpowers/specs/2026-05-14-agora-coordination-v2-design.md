# Agora Coordination v2 — Design Spec

- 날짜: 2026-05-14
- 대상 코드: `AgentAgora/src/agent_agora/`
- 베이스: v1 (현행) — `Dispatcher`, `InstanceRegistry`, `AgoraStore` 등
- 입력 문서: [자유대화_실험_리뷰_종합_2026-05-14.md](../../../자유대화_실험_리뷰_종합_2026-05-14.md)
- 결정 방식: Inst1 + 워커 7명 두 라운드 의견 수렴 → 사용자 확정

---

## 1. 배경

8 인스턴스 자유대화 실험에서 Agora가 멀티-에이전트 협업 채널로 **작동은 하지만**, 다자 동시 대화에서 4가지 운영 갭(+ 추가 발견 1) + 6가지 운영 가드 누락이 드러났다.

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
- backward compat: 기존 클라이언트(v1 시그니처)는 무수정 동작

### Non-goals
- 멀티 호스트 분산 (단일 서버 가정 유지)
- 인증·인가 (신뢰 도메인 가정 유지, squatting은 advisory 수준)
- 메시지 암호화
- conversation 머지 도구 (스레드 명시 합치기는 클라이언트가 conversation_id 명시 지정으로 해결)
- Web UI / 모니터링 대시보드

## 3. 아키텍처 개요

**Hot path (메시지 라우팅)**: 기존 in-memory `_queues` / `_waiters` (asyncio future) 유지. dispatch/wait 응답성 영향 없음.

**Cold path (영속성·조회)**: SQLite (Python stdlib). 비동기 write는 기존 `AsyncWriteQueue` 패턴 재활용.

**상태 분리**:
- `_queues`, `_waiters`: in-memory (큐와 깨움)
- `_conversation_of: dict[command_id, conversation_id]`: in-memory 캐시 (in_reply_to 상속용)
- `_conversations: dict[conversation_id, ConversationState]`: in-memory 캐시
- SQLite: 영속 source of truth (재시작 시 위 2개 dict 복구)

WAL 모드. DB 위치: `<agora_dir>/.agentagora/agora.db`.

## 4. Envelope 스키마 (v2)

```python
# dispatcher.py:dispatch() 시그니처
async def dispatch(
    self,
    source: str,
    target: list[str] | Literal["*"],          # str은 "*"만 허용
    payload: Any,                              # JSON serializable, ≤1MB
    expect_result: bool = False,
    reply_to: str | None = None,               # 단일 — 의무 답신자. None이면 source
    cc: list[str] | None = None,               # 옵저버. 동일 envelope 사본 수신, 답신 의무 없음
    in_reply_to: str | None = None,
    # --- v2 신규 ---
    conversation_id: str | None = None,
    closing: bool = False,
    priority: Literal["low", "normal", "high"] = "normal",
    deadline_ts: str | None = None,            # ISO8601, advisory
) -> dict[str, Any]
```

**Envelope (큐·SQLite 양쪽에 들어가는 dict)**:
```python
{
  "id": cmd_id,
  "source": str,
  "target": str,                       # broadcast는 N행으로 fan-out
  "payload": Any,
  "created_at": str,                   # ISO8601 UTC
  "expect_result": bool,
  "reply_to": str | None,              # 단일 의무 답신자
  "cc": list[str] | None,              # 옵저버 명단 (모든 수신자가 동일 list 본다)
  "delivered_as": "primary" | "cc",    # 이 수신자가 cc로 받았는지 primary로 받았는지
  "in_reply_to": str | None,
  # --- v2 ---
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
  "dispatched_to": [                          # primary + cc 합산
    {"instance_id": "Inst3", "as": "primary"},
    {"instance_id": "Inst5", "as": "cc"},
    ...
  ],
  "target_inbox_depth_after": dict[str, int], # 각 수신자의 dispatch 직후 큐 깊이
  "skipped_full": list[str],                  # max-inbox-depth로 빠진 수신자 (broadcast 부분 성공)
}
```

## 5. Target / reply_to / cc 시맨틱

### target
- `target: list[str]` — 명시 instance_id들. 빈 리스트 거부.
- `target: "*"` — 발신자 제외 모든 등록 인스턴스로 fan-out.
- `target: ["*", "Inst3"]` — **거부** (`ValueError("'*' cannot be mixed with explicit instance_ids")`)
- `target: ["*"]` — `"*"`와 동일 의미로 허용 (리스트 안에 단일 와일드카드).

### reply_to (단일)
- `reply_to: str` — primary 답신 수신자. 의무 답신자.
- `reply_to: None` — 수신자의 답신이 `source`에게 감 (기본).
- 와일드카드 미지원 (v1 범위 밖).

### cc (옵저버 명단)
- `cc: list[str]` — 명시 instance_id들. 빈 리스트는 None과 동치.
- `cc: None` — 옵저버 없음.
- `cc`에 나열된 인스턴스의 큐에도 동일 command가 enqueue되되, envelope에 `delivered_as: "cc"` 마킹. primary 수신자(target)는 `delivered_as: "primary"`.
- **cc 수신자는 답신 의무 없음**. CLAUDE.md 페이로드 규약에 "envelope의 `delivered_as == 'cc'`면 응답하지 않는 것이 기본" 명시.
- **cc는 자동 상속 안 함** (Inst8 R7): cc 수신자가 다음 dispatch에서 cc를 명시하지 않으면 옵저버 체인이 끊김. 폭주 방지.
- `cc`와 `reply_to`는 같은 instance_id 가질 수 없음 → `ValueError("instance cannot be both reply_to and cc")`.
- `target="*"` broadcast와 `cc` 동시 사용: cc는 broadcast 대상에서 자동 제외. 두 집합이 중복되면 broadcast가 우선(primary로 받음).
- cc 수신자가 그 메시지에 응답하고 싶으면 새 dispatch를 일으키되 `in_reply_to`로 correlation 가능. 그 답신은 정상 라우팅(별 conversation일 수 있음 — 클라이언트 결정).

### `_broadcast` 매직 스트링 폐기
v1에서 사용하던 `["_broadcast"]`는 deprecated하되 한 마이너 버전 동안은 `"*"`로 자동 치환 (warning 로그). 치환 위치: `Dispatcher.dispatch()` 진입부 normalize 단계 — `target == ["_broadcast"]`이면 `target = "*"`로 변환 후 logger.warning, 그 외 동작은 동일.

## 6. Conversation 모델

### 6.1 발급 규칙
- dispatch에 `conversation_id` 미지정:
  - `in_reply_to`가 있고 부모 메시지가 있는 conversation을 알면 → 부모의 `conversation_id` 상속
  - 그 외 → 서버가 새 UUID 발급
- `conversation_id` 명시 지정: 그 값 사용 (스레드 머지 케이스)
- `target="*"` broadcast: **단일 conversation_id 시작** (모든 수신자가 같은 conversation에 들어감)
- closed conversation에 dispatch: **자동으로 새 conversation_id 발급** (에러 없음, 이전 closed 대화는 그대로 보존)

### 6.2 상태 머신
- `open` → `half_closed` → `closed`
- `closed`에서 reopen 없음. 같은 토픽을 이어가려면 클라이언트가 새 conversation을 시작.
- `half_closed`: 한 participant가 `closing=True`를 보낸 상태. `closing` 플래그는 **단방향 advisory 신호 — ack 불필요**.
- `closed`: (a) 모든 participants가 각자 `closing=True`를 보냈거나, (b) `half_closed` 상태로 `close_timeout` 경과 후 background task가 자동 전이.

### 6.3 SQLite 스키마

```sql
CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('open','half_closed','closed')),
  started_at TEXT NOT NULL,
  last_message_at TEXT NOT NULL,
  closed_at TEXT,
  closed_by TEXT NOT NULL DEFAULT '[]',     -- JSON array of instance_ids
  message_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_conv_status ON conversations(status);
CREATE INDEX idx_conv_last_msg ON conversations(last_message_at);

CREATE TABLE messages (
  command_id TEXT NOT NULL,
  target TEXT NOT NULL,                      -- broadcast는 N행, cc도 N행
  conversation_id TEXT NOT NULL,
  source TEXT NOT NULL,
  in_reply_to TEXT,
  created_at TEXT NOT NULL,
  expect_result INTEGER NOT NULL DEFAULT 0,
  reply_to TEXT,                             -- 단일 instance_id | null
  cc TEXT,                                   -- JSON array of instance_ids | null (envelope에 동일 list)
  delivered_as TEXT NOT NULL DEFAULT 'primary' CHECK (delivered_as IN ('primary','cc')),
  closing INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
  deadline_ts TEXT,
  payload TEXT NOT NULL,                     -- JSON
  drained_at TEXT,                           -- null이면 in-flight
  PRIMARY KEY (command_id, target),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX idx_msg_conv ON messages(conversation_id);
CREATE INDEX idx_msg_source ON messages(source);
CREATE INDEX idx_msg_inflight ON messages(target, drained_at) WHERE drained_at IS NULL;
CREATE INDEX idx_msg_created ON messages(created_at);

CREATE TABLE conversation_participants (
  conversation_id TEXT NOT NULL,
  instance_id TEXT NOT NULL,
  joined_at TEXT NOT NULL,
  PRIMARY KEY (conversation_id, instance_id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX idx_cp_inst ON conversation_participants(instance_id);

-- 마이그레이션 메타
CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
INSERT INTO schema_version VALUES (1, datetime('now'));
```

## 7. 신규 MCP 도구

### 7.1 `agora.peek(targets: list[str] | "*") → dict`

부하 가시성. payload·내용 노출 없음 — 메타만.

**메타 추적 위치 (구현 노트)**:
- `queue_depth`: `len(self._queues[t])` 즉시 계산
- `in_flight`: dispatch 시 `expect_result=True`이고 그 cmd_id에 대해 reply가 아직 안 온 수. Dispatcher가 `self._in_flight: dict[str, set[str]]` (instance_id → 미응답 cmd_id 집합)으로 추적
- `last_wait_at`: `InstanceRegistry.last_seen_at` 그대로
- `last_dispatch_to_at`: Dispatcher가 `self._last_dispatch_to: dict[str, str]` (instance_id → ISO timestamp)로 추적, dispatch 시 갱신
- `wait_mode`, `accepting`: `InstanceInfo` 필드 그대로

```python
@mcp.tool(name="agora.peek")
async def agora_peek(targets: list[str] | Literal["*"]) -> str:
    """Snapshot of pending queue and consumer activity per instance.
    ADVISORY ONLY — atomicity not guaranteed (TOCTOU race vs subsequent dispatch).
    Unregistered targets return registered=False, not error."""
```

반환:
```python
{
  "Inst3": {
    "registered": True,
    "queue_depth": 3,
    "in_flight": 1,                    # expect_result=True 미응답 수
    "last_wait_at": "2026-05-14T...",  # null 가능
    "last_dispatch_to_at": "2026-05-14T...",
    "wait_mode": "auto" | "manual" | "unknown",
    "accepting": True,
  },
  "Inst99": {
    "registered": False,
    "queue_depth": None,
    "in_flight": None,
    "last_wait_at": None,
    "last_dispatch_to_at": None,
    "wait_mode": None,
    "accepting": None,
  }
}
```

### 7.2 `agora.conversation_status(conversation_id: str) → dict`

특정 대화 상태 조회. `closed` 후에도 (GC 전까지) 조회 가능.

```python
{
  "conversation_id": "...",
  "status": "open" | "half_closed" | "closed",
  "participants": ["Inst1", "Inst3", "Inst6"],
  "started_at": "...",
  "last_message_at": "...",
  "closed_at": "..." | None,
  "closed_by": ["Inst3"],
  "message_count": 12,
}
```

존재하지 않으면 `{"error": "unknown_conversation"}`.

### 7.3 `agora.conversations_list(participant: str | None = None, status: str | None = None, limit: int = 100) → list`

진행 중·종료 대화 인덱스. SQLite 쿼리.

- `participant`: 그 instance_id가 끼인 대화만
- `status`: `"open" | "half_closed" | "closed"` 필터
- `limit`: 기본 100, 최대 1000

반환: `last_message_at DESC` 순.

### 7.4 `agora.close_thread(conversation_id: str, reason: str = "") → dict`

명시적 종료 도구. 호출자가 그 conversation에 `closing=True` 메시지를 (자신을 source로) 모든 다른 participants에게 dispatch한 것과 동치. 페이로드는 `{"type": "closing", "from": "<caller>", "reason": "..."}`.

**워커 처리 부담 안내**: closing envelope이 수신자 큐에 들어가지만 `closing=True` 플래그가 명시되어 있으므로 수신자는 응답 의무 없음(섹션 9 단방향 advisory 규약). 워커는 wait 응답에서 envelope의 `closing` 필드를 보고 자연 종료.

```python
{"status": "closed" | "half_closed" | "already_closed", "conversation_id": "..."}
```

이미 `closed`면 idempotent (`already_closed`).

## 8. 갱신된 기존 도구

### 8.1 `agora.dispatch` — 시그니처 확장

- 신규 인자: `conversation_id`, `closing`, `priority`, `deadline_ts`
- 반환에 `conversation_id`, `dispatched_to`, `target_inbox_depth_after` 추가
- backward compat: 신규 인자 모두 default 보존, 기존 호출 동작 변경 없음

### 8.2 `agora.wait` — 응답 확장 + 정렬 보장

- 신규 인자: `by_conversation: str | None = None`, `sort: Literal["fifo","priority"] = "fifo"`
- 응답의 각 command에 `conversation_id`, `priority`, `wait_age_ms` 추가
- 정렬 키:
  - `sort="fifo"` (기본): `(created_at asc, command_id asc)`
  - `sort="priority"`: `(priority desc, created_at asc, command_id asc)` — 동률은 `command_id` 사전순 tie-breaker (Inst7 결정적 정렬)
- wait 호출 시 `last_seen_at` 자동 갱신

### 8.3 `agora.instances` — 부하 메타 노출

응답의 각 instance entry에 추가:
```python
{
  "instance_id", "role", "description", "registered_at",
  "inbox_depth": int,
  "in_flight": int,
  "last_seen_at": str | None,
  "wait_mode": "auto" | "manual" | "unknown",
  "accepting": bool,
}
```

### 8.4 `agora.register` — wait_mode 명시

신규 인자: `wait_mode: Literal["auto","manual"] | None = None`. None이면 `"unknown"`으로 저장. 워커는 자기 운영 모드를 정직 보고 (Inst5 결정적 지적: 추론하지 않음).

**헤더 자동 등록 일관성**: `X-Agora-Wait-Mode` 헤더 추가 (값 `"auto"` 또는 `"manual"`). `AutoRegisterMiddleware`가 첫 요청에서 헤더 보고 `wait_mode` 자동 설정. 미지정이면 `"unknown"`.

## 9. Closing 프로토콜 시맨틱

- `closing=True`는 **단방향 advisory**. 받은 쪽 ack 의무 없음.
- 모든 participants가 각자 `closing=True`를 보냈을 때만 즉시 `closed`.
- `half_closed` 상태에서 `--close-timeout-ms` (기본 **300000ms = 5분**) 경과 시 background task가 자동 `closed` 전이.
- TTL 카운트 시작점: `half_closed`로 진입한 시각 (= 가장 최근 `closing=True` 메시지의 `created_at`).
- TTL 카운트 갱신: half_closed 상태에서 새 메시지가 도착하면 TTL 리셋. closing이 아닌 일반 메시지여도 리셋(정상 활동 신호).
- `close_thread` 도구 호출은 closing 메시지 발신과 동등.

## 10. 운영 가드 (must-add 6건)

### 10.1 instance_id squatting
- 같은 instance_id로 register 시도 시: 기존 entry의 `last_seen_at`이 `--squat-window-ms` (기본 30000ms) 이내면 거부 (`ValueError("instance_id_in_use")`). 초과면 기존 entry 자동 unregister 후 신규 등록 허용 (현행 동작 유지).
- README에 "신뢰 도메인 가정 — 인증은 v1 범위 밖" 명시.

### 10.2 PII 로그 redact
- CLI 플래그 `--redact-payloads`. 활성 시 `_fmt_payload(payload)`가 `<len=N bytes>` 형태로 출력.
- 기본 비활성 (개발 친화).

### 10.3 max-inbox-depth
- CLI 플래그 `--max-inbox-depth` (기본 100).
- dispatch 시 타깃의 `len(self._queues[t]) >= max_depth`면 `ValueError("inbox_full: {target} has {n} pending")`.
- broadcast의 경우 일부 target만 가득 차면 가득 찬 target은 제외하고 나머지에는 정상 dispatch. 반환의 `dispatched_to`에서 제외된 target은 빠지고, 별도 `skipped_full: list[str]`에 명시.

### 10.4 registry.last_seen 자동 갱신
- wait 호출 진입 시 `InstanceRegistry.touch_last_seen(instance_id)` 호출.

### 10.5 dead-session GC
- CLI 플래그 `--dead-session-timeout-ms` (기본 1800000ms = 30분).
- Background task 60초마다 실행: `last_seen_at`이 timeout 초과면 `unregister_session()` 호출 + 그 인스턴스 대상의 in-flight 메시지는 그대로 큐에 남김 (재등록 시 받게 됨).
- 외부 모니터링 가시화를 위해 `accepting=False`로 먼저 마킹 후 grace period 적용은 v2 후보.

### 10.6 half-closed 명문화
- README와 워커 CLAUDE.md 페이로드 규약에 "closing=True는 단방향 advisory 신호 — ack 불필요. 양방향 도달 시 closed, 한쪽만이면 half_closed (5분 후 자동 closed)" 명시.

## 11. 데이터 흐름

### 11.1 dispatch
1. validate: caller registered? target/reply_to/cc 형식? payload ≤1MB? `cc ∩ {reply_to}` 빈 집합?
2. resolve targets: `"*"`이면 self 제외 등록 인스턴스 리스트. cc 각 instance_id도 registry resolve.
3. cc - target 중복 제거: 같은 instance_id가 target과 cc 양쪽에 있으면 target(primary)이 우선, cc 명단에서 그 id 빠짐.
4. inbox depth 체크 → 가득 찬 target은 `skipped_full`로 분리. cc 수신자도 동일 검사.
5. conversation_id 결정:
   - 명시 지정 시 그 값. 단, 그 conversation이 `closed`면 새 UUID 발급으로 대체하고 응답에 `conversation_id_substituted: true` 마킹 (호출자 가시화).
   - 미지정 + in_reply_to 있음 → `_conversation_of[in_reply_to]` 룩업 → 해당 conversation의 status가 `open`/`half_closed`면 상속, `closed`이거나 룩업 실패면 새 UUID.
   - 미지정 + in_reply_to 없음 → 새 UUID.
6. conversation 신규면 `conversations` 행 INSERT + participants INSERT (target + cc + source 모두 participants에 들어감).
7. envelope 만들고 `_queues[t].append(envelope)` — primary target은 `delivered_as="primary"`, cc 수신자는 `delivered_as="cc"`. 둘 다 동일 `command_id`·`conversation_id`·payload.
8. `_conversation_of[cmd_id] = conversation_id` 캐시 적재.
9. `AsyncWriteQueue.submit_message_insert(envelope)` 호출 (논블로킹) — primary + cc 합쳐 N+M 행.
10. `closing=True`면 `conversations.closed_by`에 source 추가 + 모든 participants가 closed_by에 포함되면 status='closed' UPDATE.
11. waiter 깨움 (primary + cc 모두).
12. 로그 1줄 (현행 통합 형식 유지): `[agora] {source} -> {target} (cc: {cc_list}) : {payload}`. cc 없으면 `(cc: ...)` 부분 생략. `--redact-payloads` 활성 시 `{payload}` 자리에 `<len=N bytes>` 출력.
13. 반환. `dispatched_to`는 primary + cc 합친 instance_id 리스트, 각 항목에 `as`(primary|cc) 마킹.

### 11.2 wait
1. validate: caller registered?
2. `_drain_matching` → 정렬 적용
3. `last_seen_at` 갱신
4. drained 각 envelope에 `wait_age_ms = now - created_at` 계산해 첨부
5. `AsyncWriteQueue.submit_drained_update(command_ids, target)` (논블로킹)
6. 반환

### 11.3 Background tasks
- **close TTL** (60초 주기): `UPDATE conversations SET status='closed', closed_at=now WHERE status='half_closed' AND last_message_at < now - close_timeout`. 영향받은 conversation_id들의 in-memory cache도 갱신.
- **dead-session GC** (60초 주기): registry 순회, `last_seen_at` 초과면 unregister.
- **message GC** (일 1회, `--gc-hour` 기본 03:00 UTC): `DELETE FROM messages WHERE conversation_id IN (SELECT conversation_id FROM conversations WHERE status='closed' AND closed_at < now - 90d)`. `conversations` 메타는 보존.

### 11.4 재시작 복구
1. `agora.db`가 없으면 신규 생성, schema 적용.
2. 있으면 schema_version 체크 후 필요 시 마이그레이션 적용.
3. `SELECT * FROM messages WHERE drained_at IS NULL` → 각 행을 envelope으로 복원해 `_queues[target].append()`.
4. 복원 시 conversation status가 `closed`면 드롭하고 `drained_at='__server_restart_drop__'`로 마킹 (재드롭 방지).
5. `_conversation_of`, `_conversations` 캐시는 lazy load (필요 시점에 SQLite 쿼리).

## 12. 에러 처리

| 케이스 | 응답 |
|---|---|
| target 미등록 | `NotRegisteredError` → `{"error": "..."}` |
| target=`"*"` 인데 본인 외 등록 인스턴스 0 | `dispatched_to=[]`, `command_id` 발급, conversation 시작 (감사) |
| target에 `*`와 명시 id 혼합 | `ValueError("'*' cannot be mixed with explicit instance_ids")` |
| reply_to == 어느 cc 원소 | `ValueError("instance cannot be both reply_to and cc")` |
| cc에 미등록 instance_id | `NotRegisteredError` |
| payload > 1MB | `ValueError("payload_too_large: {n} bytes > 1048576")` |
| 큐 가득 (max-inbox-depth) | broadcast: 부분 성공, 그 target은 `skipped_full`에. 단일 target: `ValueError("inbox_full")` |
| sqlite write 실패 | 로그 기록 + 메시지는 in-memory 큐에 남음 (eventual consistency). hot path 차단 없음 |
| 재시작 후 복원한 메시지의 conversation이 closed | 큐에서 제외, `drained_at='__server_restart_drop__'` 마킹 |
| close_thread를 미등록 conversation_id에 호출 | `{"error": "unknown_conversation"}` |
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

## 14. Backward Compatibility

- v1 클라이언트(신규 필드 미지정)는 모든 동작 변경 없음 — 동일 응답 shape.
- 단 envelope에 `conversation_id`, `priority`, `wait_age_ms`는 **항상 응답에 포함**. v1 클라이언트가 unknown 필드를 무시한다면 영향 없음.
- `["_broadcast"]`은 한 마이너 버전 동안 자동으로 `"*"`로 치환 + warning 로그. 다음 메이저에서 제거.
- 사용자 schemas.json은 영향 없음 (reserved schemas로 차단됨).
- 빈 `agora.db`에서 시작 시 schema 자동 생성.

## 15. 테스트 전략

### 15.1 회귀 (Inst7 9개 + 추가 2개)
- `test_dispatch_wait_unchanged_when_new_optional_fields_omitted` (golden test)
- `test_conversation_id_inherited_across_multi_hop_chain`
- `test_crossing_dispatch_without_conv_id_creates_distinct_ids`
- `test_explicit_same_conversation_id_merges_crossing_threads`
- `test_closing_one_side_half_closed_both_sides_closed`
- `test_priority_tie_break_deterministic_by_command_id_lex_order`
- `test_peek_unregistered_target_returns_registered_false_not_error`
- `test_expired_deadline_message_still_delivered_as_advisory` — Inst7의 원래 안(서버 enforce)을 spec advisory only로 바꾸면서 테스트 의도 재정렬. 단언: 만료된 메시지도 wait이 반환하되 `deadline_ts`와 `wait_age_ms`가 envelope에 보존되어 클라이언트가 만료 판단 가능.
- `test_priority_mode_orders_broadcast_and_direct_dispatch_deterministically`
- (추가 Inst2) `test_squatting_within_window_rejected`
- (추가 Inst2) `test_max_inbox_depth_dispatch_rejected_when_full`
- (추가 Inst7 Q5) `test_cc_recipients_receive_message_but_correlation_targets_reply_to_only` — cc 수신자는 동일 envelope 사본을 `delivered_as="cc"`로 받지만, in_reply_to correlation은 reply_to(primary)에만 동작. cc 수신자의 in_flight 카운트는 증가하지 않음
- (추가) `test_cc_overlap_with_reply_to_rejected` — `reply_to="Inst3"`이고 `cc=["Inst3"]`이면 `ValueError`
- (추가) `test_cc_overlap_with_broadcast_target_primary_wins` — `target="*"`이고 `cc=["Inst3"]`이면 Inst3는 primary로 받음 (cc 명단에서 제거)

### 15.2 영속화·복구
- `test_restart_recovery_restores_inflight_messages`
- `test_restart_recovery_drops_closed_conversation_messages`
- `test_message_gc_deletes_after_90_days_preserves_meta` (monkeypatch clock)

### 15.3 TTL
- `test_half_closed_auto_close_after_timeout`
- `test_half_closed_ttl_resets_on_new_message`

### 15.4 운영
- `test_dead_session_gc_unregisters_after_timeout`
- `test_redact_payloads_logs_only_length`
- `test_payload_size_cap_rejects_over_1mb`

## 16. 구현 마일스톤

Inst8 planner 시퀀싱 채택, owner는 spec 단계에선 indicative (writing-plans 단계에서 확정).

- **M1 — 코드 변경**:
  - schema.py: commands 빌트인 스키마 신규 필드 4개 properties 추가
  - dispatcher.py: 시그니처 + conversation state + write hook + closing/priority/deadline 처리
  - registry.py: InstanceInfo + last_seen 갱신 + dead-session GC
  - server.py: 도구 4개 신규 + 기존 3개 갱신
  - 신규 모듈: `persistence.py` — SQLite handle, schema 마이그레이션, AsyncWriteQueue 확장
  - `__main__.py`: CLI 플래그 추가

- **M2 — 테스트**: 위 15.1~15.4 전수.

- **M3 — 문서**: README, 워커 CLAUDE.md 7개, 페이로드 규약 v2 블록.

- **M4 — 코드 리뷰 + 라이브 검증**: Inst5 코드 리뷰, Inst3 + Inst2가 새 자유대화 라운드 돌려 갭 해소 실측.

## 17. Out of scope (v2 후보)

- 멀티 호스트 분산 / replication
- 인증·인가 (current: 신뢰 도메인 가정)
- 메시지 암호화
- conversation 머지·분기 도구
- broadcast rate-limit
- `agora.find`의 description 컨벤션 가이드
- in-flight 메시지의 deadletter 큐 (24시간 stale 마킹)
- priority 인플레이션 quota
- 페이지네이션 (conversations_list)

## 18. Open issues

- (해소됨) Q1~Q5 결정 완료
- 신규 필드의 schemas.json strict 모드 대응 — 빌트인 스키마에 명시 추가로 자기 문서화하되, additionalProperties는 strict로 잠그지 않음 (v1 호환).
- broadcast 시 inbox_full skipped target에 대한 발신자 가시성 — 반환의 `skipped_full`로 노출, 워커가 retry 결정.
- conversation 명시 머지(v2 후보)가 도입되기 전엔 동시 교차 dispatch가 별개 conversation으로 갈라지는 게 의도된 동작임을 README에 명시.

## 19. 참고 자료

- A2A 프로토콜 contextId 모델 (Inst3 비교)
- 자유대화 1라운드 결과: [자유대화_실험_결과_2026-05-14.md](../../../자유대화_실험_결과_2026-05-14.md)
- 자유대화 2라운드 (디자인 리뷰): 본 spec의 모든 결정의 출처
