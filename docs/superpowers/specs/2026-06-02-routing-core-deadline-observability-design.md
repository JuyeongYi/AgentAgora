# Plan A — 라우팅 코어: deadline 안전망 + observability 설계

작성일: 2026-06-02
브랜치(예정): `routing-core-deadline-observability`
선행 분석: `docs/backlog.md`(observability 후보·기술부채), Explore 코어 조사(2026-06-02)

## 1. 배경과 문제

AgentAgora는 워커(Claude Code 인스턴스)들이 `expect_result=true`로 서로
task를 dispatch하고 응답을 주고받는 stateful broker다. 이때 두 부류의 운영
리스크가 있다.

1. **무한 대기** — A가 B의 응답을 `expect_result`로 기다리는데 B가 영영
   응답하지 않는 상황(B가 죽었거나, 느리거나, B도 A의 응답을 기다리는
   상호의존). 채널 모드 워커는 상시 `wait_notify` 폴링 중이라, 겉으로는
   "조용한"(idle) 정상 상태와 "막힌" 상태가 구분되지 않는다.
2. **관측 불가** — conversation 메시지 시퀀스, expect_result 응답 커버리지,
   불완전 전송(인박스 만석으로 일부 cc/봇에 미전달) 같은 운영 정보가 SQLite
   직접 조회나 서버 콘솔로만 보인다.

## 2. 설계 결정 트레일 — 왜 "교착 탐지"가 아니라 "deadline 안전망"인가

초안은 `_in_flight` 그래프(`{source → {cmd_id → {targets}}}`)에 사이클 탐지를
얹어 교착(deadlock)을 런타임에 탐지/자동해소하는 것이었다. 검토 끝에 **폐기**한다.

- **expect_result 사이클 ≠ 교착.** 큐 기반 비동기라 dispatch는 블로킹하지
  않고, 워커는 자기 큐의 다른 메시지를 처리→응답할 수 있다. 사이클 존재만으로
  경보하면 false positive 범벅이 된다.
- **사이클은 정상 워크플로의 본질이다.** `improver→reviewer→improver` 같은
  반복 루프, `A→B→C→A` 다단 루프는 의도된 구조다. 따라서 comm-matrix에 SCC가
  있다고 거부/경고하는 것은 틀렸다.
- **런타임 탐지기는 ROI가 거꾸로다.** comm-matrix를 acyclic하게 짜면 교착은
  구조적으로 불가능 → 탐지기는 dead code. 사이클 허용/비활성 매트릭스에서만
  작동 → "제대로 설정하면 안 돌고, 느슨하게 설정해야 도는" 기능. grace 튜닝·
  false positive·자동해소(임의 victim에 error 주입)의 위험을 상시 안고 가는
  대가로 얻는 게 그뿐이다.
- **분산 시스템의 정석은 detect-and-recover보다 prevent + timeout이다.**
  영원히 안 풀리는 대기 자체를 deadline으로 끊으면, 교착·죽은 워커·느린 응답을
  **구분 없이 한 메커니즘으로** 처리할 수 있다. 교착을 특수 케이스로 다룰
  필요가 사라진다.

결론: 교착 탐지·자동해소·suspected/confirmed 상태머신·grace 튜닝은 전부 빼고,
이미 존재하지만 **강제되지 않는** `deadline_ts`를 실제 안전망으로 만든다.

## 3. 비목표 (Non-goals)

- 런타임 교착 사이클 탐지 — 폐기(§2).
- 교착 자동해소(victim 선택·error 주입) — 폐기. 영원한 대기는 deadline timeout이
  일괄 처리하고, 운영자 수동 개입은 Plan C 대시보드의 "운영자 액션"에서 다룬다.
- comm-matrix SCC 거부/경고 — 사이클은 정상이므로 하지 않는다. 진단 조회만 제공.
- acyclic team 프리셋 CSV 산출물 — Plan D(워크플로)로 분리. 본 spec은 코드만.

## 4. 범위 — 7개 작업 항목

### A-1. comm-matrix `cycles()` 진단 메서드

`CommMatrix`에 순수 진단 메서드를 추가한다. **거부·경고·strict 모드 없음** —
정보 조회 전용.

- `cycles() -> list[list[str]]`: 패턴 그래프에서 `weight_of>0` 엣지
  (`from_pat → to_pat`)로 방향 그래프를 만들고 SCC(크기≥2) 또는 자기루프를
  반환. 노드는 CSV 헤더 패턴 문자열.
- 의미: "이 매트릭스가 무한 대기를 *허용하는* 구조인가" — 의도된 사이클일 수
  있으므로 **판단하지 않고 사실만 보고**.
- 노출: dashboard / 진단 도구가 매트릭스 acyclic 여부를 표시하는 데 사용
  (대시보드 통합 자체는 Plan C). 본 항목은 메서드 + 단위 테스트까지.

### A-2. deadline 강제 (핵심 안전망)

`deadline_ts`는 현재 envelope 필드(`envelope.py:30`)·검증(`:48`)·영속
(`persistence.py:42`)까지 있으나 **만료 시 아무 일도 일어나지 않는다**. 이를
강제한다.

**A-2a. 기본 deadline 부여.** `dispatch`/`broadcast`에서 `expect_result=true`
인데 `deadline_ts`가 `None`이면, `created_at + default_timeout_ms`로 기본
deadline을 채운다. `default_timeout_ms`(기본 60000)를 재사용. 명시된
`deadline_ts`는 존중. `expect_result=false`면 deadline 미부여(응답 의무 없음).

**A-2b. `deadline_sweep()` (sweeper 신설).** 주기적으로:
- 조건: `_in_flight`에 잔존(미응답)하는 (source, cmd_id, target) 중, 해당
  메시지의 `deadline_ts < now`인 것.
- 조치(타겟별):
  1. 발신자(source) 큐에 `timeout` 에러 envelope를 reply로 주입
     (`in_reply_to=cmd_id`, `conversation_id` 상속, payload는
     `{"error": "timeout", "command_id": cmd_id, "target": target}` 형태의
     예약 msgtype `agora.error`). source를 `_wake`.
  2. `_in_flight[source][cmd_id]`에서 target 제거(set 비면 cmd_id 제거).
  3. dispatch_console 이벤트 + 로그.
- `dispatcher._lock` 안에서 수행 — reply 도착과의 경쟁 차단. reply가 먼저 와서
  in_flight에서 빠졌으면 sweep은 no-op(자연히 대상 아님).
- sweep 주기는 기존 sweeper 루프에 합류.

**A-2d. deadline 인덱스.** `_in_flight`는 cmd_id만 갖고 deadline을 모르므로,
deadline을 sweep이 O(1)로 알 수 있게 한다. `_in_flight` 등록 시점(dispatch)에
`_deadlines[cmd_id] = deadline_ts`(파싱된 epoch 또는 ISO)를 함께 기록하고,
cmd_id가 in_flight에서 완전히 빠질 때 `_deadlines`에서도 제거. 재시작 복구
(`restore_in_flight_pending`)는 영속 메시지의 `deadline_ts`를 함께 읽어
`_deadlines`를 복원한다(영속 엣지의 만료도 sweep 대상이 되도록).

**A-2c. timeout envelope 의미.** 발신자 관점에서 "기다리던 응답이 deadline 내
도착하지 않음"을 1급 메시지로 받는다. 교착이든·죽은 워커든·느린 응답이든
동일하게 이 한 경로로 통지된다. 워커는 이를 받고 재시도/포기/에스컬레이션을
스스로 결정한다(broker는 정책을 강요하지 않음).

### A-3. TD2 — 불완전 전송 가시화

현재 dispatch/broadcast 반환은 `dispatched_to`(전달 성공)와 `skipped_full`
(인박스 만석으로 누락)을 *분리된* 리스트로 준다. 이를 per-target 1급
상태로 구조화한다.

- 반환에 `deliveries: [{target, role, status}]` 추가.
  `status ∈ {delivered, skipped_full}`. `role ∈ {primary, cc, subscribed}`.
- 기존 `dispatched_to`·`skipped_full`은 **하위호환 유지**(당분간 병행 반환).
  `deliveries`가 정본(canonical). 봇 fan-out 대상(subscribed/observer)도 포함.
- `throttled`는 현재 throttle 메커니즘이 없으므로 status enum에 자리만 두지
  않는다(YAGNI) — 필요 시 후속에서 추가.

### A-4. `agora.transcript(conversation_id, since_ts=None)`

conversation의 메시지를 시간순 envelope 배열로 반환.

- 출처: SQLite `messages`(영속) — conversation_id로 조회, `created_at` 오름차순.
  in-memory 큐에 아직 있는(미영속 가능성 낮으나) 메시지와 병합은 영속이 정본
  이므로 SQLite 단일 출처로 한다(AsyncWriteQueue가 best-effort 지연 영속이라,
  방금 dispatch한 메시지가 누락될 수 있음 → 반환에 `as_of_ts` 포함해 경계 명시).
- `since_ts`: 주어지면 `created_at > since_ts` 필터(증분 폴링용).
- 반환: `{conversation_id, as_of_ts, messages: [envelope_dict...]}`.
- 도구 권한: 호출자가 해당 conversation 참가자일 것을 요구하지 않는다(운영
  관측용, peek와 같은 advisory 등급). 단 등록된 인스턴스/봇만 호출 가능.

### A-5. `agora.coverage(command_id)`

`expect_result=true`로 발사된 command의 응답 커버리지를 한 호출로 조회.

- 출처: `_in_flight`(아직 미응답인 target 집합) + conversation participants +
  메시지 `deadline_ts`.
- 반환: `{command_id, conversation_id, expect_result, deadline_ts,
  responded: [iid...], pending: [iid...], expired: bool}`.
  `expired = deadline_ts < now`.
- command_id가 expect_result가 아니거나 미존재면 명확한 사유 반환.

### A-6. `agora.reply(payload, ...)`

호출자가 직전에 받은 명령을 컨텍스트로 잡아 회신 필드를 자동 충전하는 헬퍼.

- "직전에 받은 명령": dispatcher가 instance별 **마지막으로 flush(drain)된 inbound
  command 중, 회신 대상이 되는 최신 envelope**를 기록(`_last_inbound[instance]
  = {cmd_id, source, conversation_id}`). flush 시점(`flush()`)에 갱신.
  여러 개를 drain하면 `created_at` 최신 1건을 회신 컨텍스트로.
- `agora.reply(payload, in_reply_to=None, target=None, conversation_id=None)`:
  미지정 인자를 `_last_inbound`에서 자동 충전 — `in_reply_to=cmd_id`,
  `target=source`(원 발신자), `conversation_id` 상속. payload의 `from`은
  호출자 instance_id로 설정.
- 명시 인자는 항상 우선(자동 충전을 덮어씀).
- `_last_inbound`가 비어 있으면(받은 적 없음) 명확한 에러.
- 내부적으로 `dispatch(in_reply_to=..., target=..., conversation_id=...)`로
  위임 — reply correlation(in_flight 해제)이 기존 경로로 자연히 동작.

### A-7. `agora.cancel(command_id)`

발신자가, 아직 consume되지 않은 in-flight 명령을 회수.

- 호출자가 해당 command의 source여야 함(아니면 거부).
- target 큐에서 `cmd_id` envelope를 제거(아직 큐에 있으면). 이미 flush됨
  (`drained_at` set, 큐에 없음)이면 no-op + `reason: already_consumed`.
- `_in_flight[source][cmd_id]`에서 회수된 target 제거.
- 반환: `{command_id, cancelled: [iid...], already_consumed: [iid...]}`.
- 영속: 회수된 메시지에 `cancelled_at` 마킹(또는 삭제) — best-effort.

## 5. 데이터/상태 변경 요약

| 위치 | 변경 |
|------|------|
| `comm_matrix.py` | `cycles()` 추가 (순수, 거부 없음) |
| `dispatcher.py` | `_last_inbound` dict 신설(flush에서 갱신); `dispatch`/`broadcast`에 기본 deadline 부여; `cancel()`·`reply` 위임 메서드; dispatch 반환에 `deliveries[]` |
| `sweeper.py` | `deadline_sweep()` 신설, 주기 루프 합류 |
| `server.py` | `agora.transcript`·`agora.coverage`·`agora.reply`·`agora.cancel` 도구 등록 |
| `envelope.py` | 예약 msgtype `agora.error`(timeout 통지) — 기존 schema 카탈로그에 등록 |
| `persistence.py` | (선택) `cancelled_at` 컬럼; transcript 조회 쿼리 |

## 6. 에러/엣지 케이스

- **deadline 경쟁**: reply와 deadline_sweep이 동시 대상 → `_lock`으로 직렬화,
  먼저 처리된 쪽이 in_flight에서 제거하므로 다른 쪽은 no-op.
- **deadline timeout 후 늦은 reply 도착**: 이미 in_flight에서 빠졌으므로 reply는
  correlation 대상 없음 → 정상 메시지로 전달되되 in_flight 변화 없음. 발신자는
  이미 timeout을 받았으므로 늦은 응답을 자체 판단(허용 — broker는 막지 않음).
- **broadcast의 다중 target deadline**: target별로 독립 만료·독립 timeout 통지.
- **cancel 후 도착한 응답**: 회수된 target이 그 사이 flush했다면 already_consumed.
- **transcript의 영속 지연**: `as_of_ts` 경계로 명시. 방금 dispatch한 메시지가
  안 보일 수 있음을 문서화.

## 7. 테스트 계획 (TDD)

- `tests/test_v4_deadline.py` — 기본 deadline 부여, deadline_sweep이 만료
  엣지에 timeout envelope 주입 + in_flight 해제, reply 선도착 시 sweep no-op,
  늦은 reply 처리, broadcast 다중 target 독립 만료.
- `tests/test_v4_observability.py` — transcript(시간순·since_ts 필터),
  coverage(responded/pending/expired), reply(자동 충전·명시 우선·빈 inbound
  에러), cancel(회수·already_consumed·비-source 거부).
- `tests/test_v4_deliveries.py` — TD2 `deliveries[]` 구조(primary/cc/
  subscribed, delivered/skipped_full), 하위호환 필드 병존.
- `tests/test_comm_matrix.py`(확장) — `cycles()` (acyclic·자기루프·다단
  SCC·정규식 패턴 노드).

## 8. 후속 (이 spec 범위 밖)

- Plan B: 영속/sweeper 기술부채(재시작 복구 명시화·schema 영속 복원·VACUUM
  통합) + register_bot 재등록 ref 버그 + bot_emit ACL 재검사.
- Plan C: 대시보드에서 `cycles()`·`coverage`·`transcript`·deadline 만료
  이벤트 노출, 운영자 수동 해소 액션.
- Plan D: comm-matrix acyclic team 프리셋 CSV + 리뷰어 트리거 구조적 강제.
