# dispatcher.py 책임 분리 리팩터링 설계

> 2026-05-17. `Dispatcher` 단일 클래스(~1110행)에서 콘솔 로그·conversation 상태·
> 백그라운드 sweep·dispatcher 영속 로직을 별도 모듈로 분리한다. 순수 리팩터링 —
> 외부 동작 불변.

## 1. 배경 / 동기

`src/agent_agora/dispatcher.py`는 `Dispatcher` 한 클래스에 메시지 라우팅 핫패스,
conversation 라이프사이클, 4종 백그라운드 sweep, SQLite 영속 트랜잭션, 재시작 복원,
콘솔 로그 헬퍼를 모두 담아 ~1110행이다. 핫패스(`dispatch`·`broadcast`·`bot_emit`·
`flush`·`wait_notify`·`system_notify`)는 공유 가변 상태와 단일 `_lock`을 함께 만지므로
한 클래스에 묶이는 게 맞지만, 나머지는 책임이 분리된다.

이 리팩터링은 핫패스를 `dispatcher.py`에 남기고 나머지를 4개 모듈로 추출한다.
**순수 리팩터링이다 — 외부 동작·로깅 출력·락 의미는 모두 보존하며, 기존 329개
테스트가 변경 없이 통과해야 한다.**

## 2. 목표 모듈 구조

| 모듈 | 책임 |
|---|---|
| `dispatcher.py` | `Dispatcher` 핫패스: `dispatch`·`broadcast`·`bot_emit`·`flush`·`wait_notify`·`system_notify`·`peek`·`in_flight_count`·`_wake`·`_validate_payload`·`_touch_last_seen`·`close`. 공유 상태(`_queues`·`_waiters`·`_in_flight`·`_last_dispatch_to`)와 `_lock` 보유. |
| `dispatch_console.py` (신규) | `_fmt_payload`·`_color_for`·`_colored`·`_COLOR_PALETTE`·`_RESET` — 순수 로그/색상 헬퍼. |
| `conversation_store.py` (신규) | `ConversationStore` — conversation 상태 dict와 라이프사이클 로직. |
| `sweeper.py` (신규) | `Sweeper` — 4종 백그라운드 sweep. |
| `dispatch_persistence.py` (신규) | `DispatchPersistence` — dispatch 영속 트랜잭션 빌드·제출, 복원·drop의 SQL 부분. |

`_now_iso`·`_envelope_to_dict`는 작은 범용 헬퍼라 `dispatcher.py`에 남긴다(로그 헬퍼가
아니므로 `dispatch_console.py` 대상 아님).

## 3. `dispatch_console.py`

순수 함수·상수만 이동한다 — `_fmt_payload`, `_color_for`, `_colored`,
`_COLOR_PALETTE`, `_RESET`. 공유 상태가 없어 단순 이동이다. `dispatcher.py`는
`from agent_agora.dispatch_console import _fmt_payload, _colored`로 import한다.
콘솔 출력 문자열은 한 글자도 바뀌지 않는다.

## 4. `ConversationStore`

`conversation_store.py`에 `ConversationStore` 클래스를 둔다. `Dispatcher`가 인스턴스
하나를 보유한다(`self._conv = ConversationStore()`).

**보유 상태** (현 `Dispatcher`에서 이동):
- `_conversations: dict[str, dict]` — conv_id → 상태(status·kind·participants·closed_by 등).
- `_conversation_of: dict[str, str]` — cmd_id → conv_id.
- `_message_source: dict[str, str]` — cmd_id → source. `_conversation_of`와 함께 GC되므로
  같은 store가 보유한다.

**메서드** (현 `Dispatcher`의 동명 헬퍼에서 이동):
- `new_state(kind) -> dict` (현 `_new_conversation_state`).
- `add_participant(state, instance_id, role, delivered) -> bool` (현 `_add_participant`).
- `maybe_close(conv_id, state) -> bool` (현 `_maybe_close`).
- `resolve_conversation_id(conversation_id, in_reply_to) -> tuple` (현 `_resolve_conversation_id`).
  현재 이 메서드는 `_persistence.lookup_conversation_for`를 호출하므로 `ConversationStore`가
  `persistence` 참조를 생성자 인자로 받는다.
- `status(conv_id) -> dict` (현 `conversation_status`).
- `list(participant, status, limit) -> list` (현 `conversations_list`).
- conversation·cmd 캐시 접근자 — `conv_id_of(cmd_id)`, `source_of(cmd_id)`,
  `record(cmd_id, conv_id, source)`, `get(conv_id)`, `put(conv_id, state)`, `evict(conv_ids)`.

**락 규약 — 자체 락 없음.** `ConversationStore`는 자체 `Lock`을 갖지 않는다. `Dispatcher`의
핫패스가 `_lock`을 잡은 상태에서 변형 메서드(`new_state`·`add_participant`·`maybe_close`·
`record`·`put`)를 호출한다. 읽기 메서드(`status`·`list`·`conv_id_of`·`source_of`·`get`)는
현행 `conversation_status`/`conversations_list`처럼 락 없이 호출된다 — 기존 동작 그대로다.
락은 여전히 `Dispatcher._lock` 하나뿐이라 락 순서 위험이 없다.

`close_thread`는 `Dispatcher`에 남는다(내부에서 `self.dispatch`를 호출하므로) — 단
conversation 상태 변형(`closed_by` 추가·status 전이·`maybe_close`)은 `ConversationStore`에
위임한다.

## 5. `Sweeper`

`sweeper.py`에 `Sweeper` 클래스를 둔다. 생성자:

```
Sweeper(conversation_store, instance_registry, bot_registry, schema_registry,
        persistence, *, close_timeout_ms, dead_session_timeout_ms, gc_retention_days)
```

**메서드** (현 `Dispatcher`에서 본문 통째로 이동):
- `close_ttl_sweep(now=None) -> list[str]` — half_closed → closed 자동 전이.
- `dead_session_sweep(now=None) -> list[str]` — idle 워커 unregister + `schema_registry.release_holder`.
- `dead_bot_sweep(now=None) -> list[str]` — idle 봇 unregister + `schema_registry.release_holder`.
- `message_gc_sweep(now=None) -> int` — 닫힌 conversation의 오래된 메시지 삭제 + `ConversationStore` 캐시 eviction.

`message_gc_sweep`은 in-memory 캐시(`_conversations`·`_conversation_of`·`_message_source`)를
`ConversationStore.evict(...)`로 비운다. `close_ttl_sweep`은 `ConversationStore`의
conversation 상태를 순회·전이한다.

`__main__.py`의 sweep 루프(현 229~231행, 246행)가 `dispatcher.<sweep>()` →
`sweeper.<sweep>()`로 바뀐다. `Sweeper` 인스턴스는 `__main__.py`가 `Dispatcher`와 함께
생성하거나, `Dispatcher`가 `dispatcher.sweeper` 속성으로 노출한다 — 플랜에서 확정한다.

## 6. `DispatchPersistence`

`dispatch_persistence.py`에 `DispatchPersistence` 클래스를 둔다. 생성자는
`(persistence, write_queue)`.

**이동 대상:**
- `persist_dispatch_txn(...)` — 현 `_persist_dispatch_txn`. envelope·conversation 상태로
  SQL stmt 리스트를 빌드해 `write_queue.submit_transaction`으로 제출. `dispatch`·
  `broadcast`·`bot_emit`이 `_lock` 안에서 `await self._dispatch_persistence.persist_dispatch_txn(...)`로 호출.
- `restore_from_persistence`·`drop_inflight_on_restart`의 **SQL 부분** — 영속 레이어
  읽기/UPDATE. in-memory 상태 적재(`_queues`에 envelope 싣기, `ConversationStore`·
  `_in_flight` 채우기)는 `Dispatcher`가 수행한다.

`Dispatcher.restore_from_persistence`·`drop_inflight_on_restart`는 thin 메서드로 남아
SQL 부분을 `DispatchPersistence`에 위임하고 in-memory 적재만 직접 한다 — `__main__.py`
호출부(현 183·185행) 무변경.

## 7. Blast radius

호출부 변경을 최소화한다:
- `server.py`의 `conversation_status`·`conversations_list` 호출(419·428행) — `Dispatcher`에
  1줄 delegator(`return self._conv.status(...)`)를 남겨 `server.py` 무변경.
- `__main__.py`의 `restore_from_persistence`·`drop_inflight_on_restart` 호출 — `Dispatcher`
  thin 메서드 유지로 무변경.
- `__main__.py`의 sweep 호출(229~231·246행) — `sweeper.*`로 변경(불가피, sweep 본문이
  통째 이동).

## 8. 테스트

순수 리팩터링이므로 **새 동작 테스트를 추가하지 않는다.** 성공 기준은 기존 329개
테스트가 변경 없이 통과하는 것이다. 단:
- `__main__.py`의 sweep 호출이 `sweeper.*`로 바뀌므로, 그 sweep 루프를 검증하는 테스트가
  있으면 호출 경로를 갱신한다.
- sweep을 `dispatcher.close_ttl_sweep()` 식으로 직접 호출하던 단위 테스트(`test_v3_recovery.py`
  등)는 `Sweeper` 인스턴스를 통해 호출하도록 갱신한다 — 단언하는 *동작*은 그대로.
- 각 추출 모듈(`ConversationStore`·`Sweeper`·`DispatchPersistence`)은 추출 후 그 자체로
  단위 테스트가 가능해진다. 기존 테스트가 커버하던 동작을 새 단위 위치에서 재확인하는
  최소 테스트는 허용하되, 목적은 회귀 방지지 신규 기능 검증이 아니다.

## 9. 비목표 (YAGNI)

- 락 구조 변경 — `Dispatcher._lock` 단일 락 유지. `ConversationStore`·`Sweeper`는 자체
  락을 두지 않는다.
- 핫패스 로직 변경 — `dispatch`·`broadcast`·`bot_emit`·`flush`의 알고리즘은 그대로.
- 콘솔 출력 포맷 변경 — 로그 문자열 한 글자도 안 바꾼다.
- `_now_iso`·`_envelope_to_dict`를 별도 util 모듈로 빼기 — 작아서 `dispatcher.py`에 잔류.
- 기존의 느슨한 락 관행(읽기 메서드·sweep의 무락 접근) 교정 — 동작 보존이 우선.

## 10. 플랜 분할 (독립 머지 가능)

- **Plan 1 — `dispatch_console.py`.** 순수 로그 헬퍼 이동. 공유 상태 없음 — 독립, 가장 단순.
- **Plan 2 — `ConversationStore`.** conversation 상태·라이프사이클 추출, `Dispatcher`가
  위임. `conversation_status`/`conversations_list` delegator 유지.
- **Plan 3 — `Sweeper`.** 4종 sweep 추출, `__main__.py` sweep 루프 재배선. Plan 2 이후
  — `message_gc_sweep`·`close_ttl_sweep`이 `ConversationStore`에 의존.
- **Plan 4 — `DispatchPersistence`.** `persist_dispatch_txn`·복원 SQL 추출. Plan 2와 독립.

순서: Plan 1 임의, Plan 2 → Plan 3, Plan 4는 Plan 2 이후 임의. 각 플랜은 머지 시 329
테스트 통과 상태를 유지한다.
