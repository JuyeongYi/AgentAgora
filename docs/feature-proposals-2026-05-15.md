# AgentAgora 신규 기능 제안 — 2026-05-15

## 배경

세션에서 6개 워커 인스턴스(Inst2/4/5/6/7/8)에게 broadcast로 "현재 도구에 추가하면 도구 가치가 실제로 늘어날 기능 1~2개 + 한 줄 근거"를 요청. 응답 본문 + 같은 세션 중 굴러간 자율 메쉬 대화 6건(db 기준)에서 워커들이 실제로 부딪힌 페인포인트를 교차 검증.

세션 통계 (db 기준): conversations=18, messages=89, 자유 메쉬 thread=6.

## 핵심 시그널

**6명 중 5명이 같은 빈 칸을 가리킴 → "observability"**. `outstanding` / `expect_replies` / `ack_status` / `conversations_view` / `transcript` / `fetch_message` 모두 같은 결핍의 변종. 발사·대기 라이프사이클은 잘 정의돼 있지만 "지금 굴리고 있는 게 뭐고 누구 차례인가"를 한 호출로 못 얻음.

**자기참조 증거**: 이 문서를 쓰기 위해 자유 메쉬 대화 raw transcript가 필요했는데, agora 도구 표면(`conversation_status` / `peek` / `conversations_list`)으로는 본문 시계열을 얻을 수 없어 SQLite db에 직접 접근해 우회. 사용자가 "db 참고"라고 명시적으로 지시한 사실 자체가 도구 갭의 즉시 증명.

## 원본 제안

| 워커 | 제안 1 | 제안 2 |
|------|--------|--------|
| Inst2 (general) | `cancel(cmd_id)` — in-flight 회수 | `transcript(conv_id)` — 시계열 본문 |
| Inst4 (coder) | `reply(...)` — 답신 헬퍼 | `expect_replies(cmd_id)` — `{responded, pending}` |
| Inst5 (reviewer) | `outstanding` — 미회신 발신 (마감 정렬) | — |
| Inst6 (writer) | `search` — payload 풀텍스트 | `fetch_message(cmd_id)` — 단건 본문 |
| Inst7 (tester) | `ack_status(cmd_id)` — 도달/처리/회신 3단계 | `transcript_export + replay` — 회귀 fixture |
| Inst8 (planner) | `conversations_view` — 누구 차례 그룹 뷰 | `plan_dispatch` — DAG submit |

## 우선순위 권고

### P1 — Observability 묶음 (즉시 권고)

6명 중 5명이 독립적으로 같은 결핍 보고. 두 도구로 압축:

#### `agora.transcript(conversation_id, since_ts?)`
- conversation의 메시지 시퀀스를 시간순 envelope 배열로 반환.
- `fetch_message` (단건 조회), `search`의 일부는 derivable. 본 문서 작성을 위해 SQLite 직접 조회로 우회한 작업이 이 도구의 정확한 시연.
- 응답 형태: `[{command_id, source, target, payload, created_at, in_reply_to}, ...]`.

#### `agora.coverage(command_id)`
- `expect_result=true`로 발사된 command의 응답 커버리지 통합 조회.
- 응답 형태: `{command_id, responded: [{instance_id, reply_command_id, ts}], pending: [...], deadline_ts}`.
- `outstanding` (Inst5), `ack_status` (Inst7), `expect_replies` (Inst4)의 단일 통합. 자기 발신 명령 전체를 훑는 `outstanding`은 `coverage` 호출자 측 누적으로 합리적으로 대체.

**근거 요약**: db 직접 접근으로 우회 가능하다는 사실 자체가 이 두 도구가 빠진 자리임을 증명. 워커 5명이 같은 vacancy를 독립적으로 보고. 호출자(Inst1)가 broadcast 응답 수집 시 `payload.from`을 직접 누적하는 보일러플레이트가 매번 등장.

### P2 — Reply 헬퍼 (작은 추가, 큰 즉효)

#### `agora.reply(message, ...)`
- 가장 최근 수신한 (또는 명시한) 명령을 컨텍스트로 잡아 `in_reply_to` / `conversation_id` / `target` / `payload.from`을 자동 채움.
- 호출자는 본문(`message`)과 필요한 경우 `closing` / `expect_result` 만 지정.

**근거 (Inst4)**: 답신은 통신의 절대 다수인데 호출당 UUID 2개 + conversation_id를 payload·in_reply_to·conversation_id 세 곳에 직접 옮기는 가장 비싼 동작. db 검증: 자유 메쉬 6건 중 5건이 4~6 라운드를 굴렸고 매 라운드마다 동일 보일러플레이트가 워커마다 반복.

### P3 — Cancel (작고 좁음)

#### `agora.cancel(command_id)`
- 발신자가 아직 consume 안 된 in-flight 명령 회수. 이미 consume된 경우 no-op + 사유 반환.

**근거 (Inst2)**: 발사 후 오타·잘못된 target 발견 시 유일한 복구 경로. 시나리오 좁지만 구현 비용 작고 즉효.

### 보류 — Plan DAG

#### `agora.plan_dispatch(nodes, edges)`
- N개의 dispatch와 의존성 edge(B는 A 응답 후, C는 A·B fan-in 후)를 한 번에 제출. 메시지층이 응답 도달 시 다음 노드 자동 디스패치.

**근거 (Inst8)**: 가치 크지만 시맨틱 복잡 — 부분 실패 전파(자식 노드 cancel? skip?), 동적 분기, 사이클 검사, deadline 전파, 캐리/베리언트 처리. 단순 fan-out → fan-in 하나만 먼저 모델링하는 변종(`agora.gather(dispatches)`)으로 좁혀 도입하는 것도 옵션. 멀티페이즈 plan 케이스가 실측 누적되면 재검토.

### 보류 — Transcript Replay

#### `agora.transcript_export + replay(transcript, target_map, timestamps='replay'|'now')`
- 한 conversation의 메시지 시퀀스를 직렬화 저장, 인스턴스 매핑을 바꿔 재실행.

**근거 (Inst7)**: 분산 메시징 회귀 fixture로 흔한 형태. 단 시간 의존·외부 부작용 메시지는 결정성 옵션이 필수 — Inst7도 이를 명시했음. 회귀 테스트 수요가 누적되면 도입.

## 비추천 — 신규 multi-dispatch 도구

별도 세션에서 논의된 항목 (Inst4·Inst5·Inst8 의견 수렴). "broadcast가 아닌 지정 N명 응답 요청"의 단일 호출 형태를 추가할지 검토했으나:

- **(c) 보류 우세**(Inst4·Inst5). `gather`/`Promise.all` 한 줄로 호출부 해결되고, conversation_id / in_reply_to / cc / expect_result가 N명에 어떻게 분배되는지 *작은 결정의 폭발* 위험.
- (b) `dispatch.target: str | list[str]` 유니온 확장(Inst8)도 단일·다중 케이스의 시그니처·반환 모양(`dispatched_to`가 1 vs N)이 분기.

**도입 트리거**: ① atomic fan-out 보장 요구, ② 그룹 대화 시맨틱(3자+ 한 conversation), ③ 동일 호출부 패턴 3곳 이상 누적. 그 전까지 빈 슬롯 유지.

## 자기참조 자기증명

이 brainstorming 자체에서 본 관측 가능성 결핍:

1. Inst1이 워커끼리 메쉬 대화 6건을 직접 못 봄 — 워커 보고 요약에만 의존.
2. raw transcript는 외부 채널(SQLite 직접 조회)로만 접근 가능. agora 도구 표면에서는 불가.
3. broadcast 응답 수집 동안 "누가 답했고 누가 안 답했나" 추적은 호출자가 `payload.from`을 직접 누적했어야 함 (`agora.coverage`가 정확히 채울 갭).
4. 동일 conversation에서 4~6 라운드를 굴린 워커들이 매 라운드 in_reply_to / conversation_id를 손으로 옮김 (`agora.reply`가 정확히 채울 갭).

P1·P2가 채울 갭이 본 세션에서 *모두 실측*됨.

## 부록 A — 자유 메쉬 대화 메타 (db 발췌)

| conversation_id | 참가자 | 라운드 | 주제 | 종료 주체 |
|-----------------|--------|--------|------|----------|
| `5485227c…` | Inst5 ↔ Inst8 | 5 | 계획서 리뷰 체크포인트 위치 (early-review 트리거) | Inst8 |
| `0bb365e7…` | Inst5 ↔ Inst6 | 6 | 무시당하지 않는 리뷰 코멘트 (nit 무게추) | Inst5 |
| `a29753df…` | Inst2 ↔ Inst8 | 6 | 직접 실행 vs 위임 결정 (scope shape) | Inst8 |
| `25916a2c…` | Inst5 ↔ Inst7 | 5 | 테스트 안티패턴 (tautology test diff 동시성) | Inst7 |
| `c5db7b8e…` | Inst5 ↔ Inst8 | 4 | 머지 직전에 발견되면 늦은 항목 (failure mode N/A) | Inst8 |
| `d5aa3dd6…` | Inst4 ↔ Inst7 | 5 | 코더/테스터 책임 경계 (`Covered:` PR 표기) | Inst4 |

세션 누적: conversations=18, messages=89.

## 부록 B — 메쉬 대화 발췌 인사이트 (raw transcript 기반)

P1·P2 도입의 정당성과 별개로, 메쉬 대화에서 도출된 도구 외 인사이트도 db에 보존돼 있어 별도 문서화 후보:

- **PR `Covered:` 표기 표준** (Inst4↔Inst7): 시나리오 어휘가 아니라 **입력 도메인의 차원** 어휘로 통일 (`Covered: empty_input, single_match, multi-match`).
- **tautology test 자동 검출** (Inst5↔Inst7): PR bot이 src/test 동일 라인 위치 변경 비율을 1차 필터로 사용 가능 — 리뷰어가 보기 전 자동 플래그.
- **plan template 개선** (Inst5↔Inst8): early-review 트리거 = 데이터모델/실패모드/스코프경계/non-goals 4칸 충족 시. failure mode는 "N/A + 한 줄 이유" 허용.
- **위임 결정 휴리스틱** (Inst2↔Inst8): scope shape(30초 사전 필터) + grok 후 'not my domain' 즉시 turnaround. 매몰된 grok은 'warm handoff' 페이로드로 회수.

이들은 agora 기능과 무관하나 워커 운영 노하우로 별도 문서로 옮길 가치 있음. raw transcript는 `db.messages WHERE conversation_id IN (...)` 로 복원 가능.
