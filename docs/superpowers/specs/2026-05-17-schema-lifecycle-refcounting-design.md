# 스키마 라이프사이클 ref-counting 설계

> 2026-05-17. 스키마 등록 해제를 신설한다 — 스키마를 등록·구독한 인스턴스·봇이
> 전부 사라졌을 때 reference count로 자동 해제한다.

## 1. 배경 / 동기

`SchemaRegistry`는 현재 append-only다. `register`만 있고 `unregister`가 없다.
봇은 `register_bot`의 인라인 `schemas=`로, 워커는 `agora.register_schema`로 스키마를
등록한다. 그러나 봇·워커가 사라져도(`agora.unregister`, `dead_session_sweep`,
`dead_bot_sweep`) 스키마 엔트리는 영구히 남는다 — 봇 detach(`BotRegistry._detach_locked`)는
구독 역인덱스(`_subscribers`)만 정리하고 `SchemaRegistry`는 손대지 않는다.

장기 운영 시 죽은 인스턴스가 등록한 스키마가 무한정 누적된다. 이 설계는 reference
count를 도입해, 한 스키마를 등록·구독한 주체가 *전부* 사라졌을 때만 그 스키마를
해제한다. startup에 로드된 빌트인 스키마는 해제 대상이 아니다.

## 2. ref 보유 모델

런타임 등록 스키마마다 holder 집합을 둔다 — `_refs[name]: set[str]` (holder id 집합).

**ref 획득:**
- **등록자** — `agora.register_schema`(워커) 또는 `register_bot`의 인라인 `schemas=`(봇)로
  스키마를 register한 주체.
- **구독자** — `register_bot`의 `subscribe_schemas`로 그 스키마를 구독한 봇.

**ref 해제:** holder가 사라질 때 — `agora.unregister`, `dead_session_sweep`(워커),
`dead_bot_sweep`(봇).

`_refs[name]`이 빈 집합이 되면 그 스키마를 등록 해제한다 — `_entries`·`_validators`·
`_refs`에서 제거. 단 permanent 스키마(§3)는 제외.

## 3. 빌트인 스키마 예외

startup에 `schemas.jsonl`에서 로드된 스키마 6종(`worker_freeform`·`default`·`closing`·
`ack`·`bot_reply`·`bot_error`)과 신규 `schema_conflict`(§5)는 **permanent**다.
`SchemaRegistry._permanent: set[str]`에 이름을 담아 표시하며, permanent 스키마는
`_refs` 추적 대상이 아니고 절대 해제되지 않는다.

permanent 판정: `register(holder=None)`로 등록된 스키마(= jsonl 로더·startup 코드가
호출). `register(holder="<id>")`로 등록된 스키마는 ref-counted.

permanent 스키마를 봇이 구독·재등록해도 ref-counting과 무관하다 — `acquire_ref`/
`register`가 permanent 이름에 대해서는 no-op(refset 미생성).

## 4. 봇 재등록

봇이 `register_bot`을 다시 호출하면 `BotRegistry`가 옛 `BotInfo`를 detach한다. 스키마
ref도 정합을 맞춘다 — 재등록 시 server 핸들러가 그 봇 holder id로 `release_holder`를
먼저 호출해 옛 ref를 모두 해제한 뒤, 새 인라인·구독 스키마에 대해 ref를 재획득한다.

## 5. 같은 이름 충돌

- 같은 이름 **+ 같은 body** → idempotent. holder를 `_refs[name]`에 추가한다(2번째
  등록자도 ref를 보유 — ref-counting 정상 동작). 에러 없음.
- 같은 이름 **+ 다른 body** → 충돌. 먼저 등록된 엔트리가 그대로 유지된다(불변).
  `register`는 기존대로 `AgoraError("schema_immutable")`를 raise한다. server의 등록
  핸들러는 이 에러를 잡아 ① 동기 tool 에러 응답을 반환하고 ② 추가로 등록 시도
  주체의 인박스에 에러 envelope를 enqueue한다.

**충돌 통지 메커니즘 — `Dispatcher.system_notify`:**

```python
async def system_notify(self, target: str, payload: dict) -> None
```

system-source 봉투를 `_queues[target]`에 넣고 `_wake(target)`만 한다 — comm-matrix·
conversation·in_flight 머신을 우회한다. 봉투는 `source="agora-system"`,
`conversation_id`는 신규 uuid, `expect_result=False`, `delivered_as="primary"`.
워커·봇 둘 다 `_queues[id]` 인박스를 공유하므로(워커는 채널 어댑터, 봇은 SDK 루프가
`wait_notify`로 깸) 한 메커니즘으로 양쪽에 통지된다.

`system_notify`는 in-memory enqueue + wake만 한다 — SQLite 영속화하지 않는다(충돌
통지는 transient 이벤트, 재시작 후 보존 불필요 — §10 비목표).

**`schema_conflict` 빌트인 스키마:** 충돌 통지 payload의 `msgtype`. `kind=conversation`.
body는 `msgtype`(필수 property)·`schema_name`·`reason`·`attempted_by`·`ts`. 번들
`default_schemas.jsonl`에 7번째 항목으로 추가하고, **서버 startup이 jsonl 로드 후
`schema_conflict`를 permanent로 idempotent 재등록**한다 — 기존 배포의 stale
`schemas.jsonl`(`ensure_schemas_file`이 기존 파일을 손대지 않으므로)에 항목이 없어도
보장된다.

## 6. `SchemaRegistry` API 변경

```python
# 신규 내부 상태
self._refs: dict[str, set[str]] = {}        # name -> holder ids (ref-counted 스키마)
self._permanent: set[str] = set()           # 해제 불가 스키마 이름
```

| 메서드 | 변경 |
|---|---|
| `register(name, body, kind, purpose, holder=None)` | `holder=None` → permanent(`_permanent`에 추가). `holder="<id>"` → `_refs[name]`에 holder 추가. 같은 body idempotent: permanent면 no-op, ref-counted면 holder 추가. 다른 body → `schema_immutable` raise (기존). |
| `acquire_ref(name, holder)` (신규) | 구독자 ref. name이 permanent거나 미존재면 no-op. 아니면 `_refs[name]`에 holder 추가. |
| `release_holder(holder) -> list[str]` (신규) | 모든 `_refs[name]`에서 holder 제거. refset이 비면 그 스키마를 `_unregister`. 해제된 스키마 이름 리스트 반환. |
| `_unregister(name)` (신규, 내부) | `_entries`·`_validators`·`_refs`에서 제거. permanent면 호출 안 됨. |

`SchemaEntry.registered_by`는 최초 등록자 정보로 그대로 둔다(라이프사이클의 진실은
`_refs`). 스레드 안전성은 기존 `_lock`로 보장.

## 7. 와이어링 (server.py · sweeps)

- `agora.register_schema` 핸들러 — `register(..., holder=<caller id>)`. `schema_immutable`
  catch → 동기 에러 + `dispatcher.system_notify(caller, schema_conflict payload)`.
- `agora.register_bot` 핸들러 — 봇 재등록이면 먼저 `release_holder(bot id)`. 인라인
  `schemas=` 각각 `register(..., holder=bot id)`; `subscribe_schemas` 각각
  `acquire_ref(name, bot id)`. 인라인 스키마 충돌 시 `system_notify`로 봇에 통지.
- `agora.unregister`(워커) 핸들러 — `release_holder(worker id)`.
- `dead_session_sweep` — 각 swept 워커에 `release_holder`.
- `dead_bot_sweep` — 각 swept 봇에 `release_holder`. (현재 `bot_registry.unregister_session`만
  호출 — `SchemaRegistry.release_holder`도 추가.)

`SchemaRegistry`는 `Dispatcher`가 이미 보유(`_schema_registry`) — sweep 메서드에서 접근 가능.

## 8. 테스트

`tests/test_v4_schema_*` 또는 신규 `tests/test_schema_refcounting.py`:
- `register(holder="A")` → `_refs["s"] == {"A"}`. `register` 같은 body `holder="B"` → `{"A","B"}`.
- `acquire_ref("s","C")` → `{"A","B","C"}`.
- `release_holder("A")` → 스키마 잔존(`{"B","C"}`). `release_holder("B")`·`release_holder("C")` → 스키마 해제, `get("s") is None`.
- permanent 스키마: `register(holder=None)` 후 `release_holder`로 그 이름의 어떤 holder를 빼도 해제 안 됨. `acquire_ref`/`register`가 permanent에 no-op.
- 다른 body 충돌 → `schema_immutable` raise, 기존 엔트리 불변.
- 봇 재등록 → 옛 ref 해제 + 새 ref 획득.
- `dead_bot_sweep`/`dead_session_sweep` 후 그 주체만 등록·구독한 스키마가 해제됨.
- `Dispatcher.system_notify` → target 인박스에 `schema_conflict` envelope, `flush`로 회수.
- `agora.register_schema` 충돌 → 동기 에러 + 발신자 인박스에 충돌 통지.

## 9. 비목표 (YAGNI)

- 충돌 통지 envelope의 SQLite 영속화 — transient 이벤트, 재시작 후 보존 불필요.
- 빌트인 스키마의 ref-counting — permanent는 영구.
- in-flight 메시지가 참조하는 스키마의 해제 보호 — dispatch는 발신 시점에 검증을
  마쳤고, 해제 후 그 msgtype 신규 dispatch는 `unknown_msgtype`로 정상 거부된다.
- `registered_by` 필드를 holder 집합으로 대체 — 최초 등록자 정보로 유지.

## 10. 플랜 분할 (독립 머지 가능)

- **Plan 1 — `SchemaRegistry` ref-counting + `schema_conflict` 빌트인.** `_refs`·
  `_permanent`·`register(holder=)`·`acquire_ref`·`release_holder`·`_unregister`,
  `default_schemas.jsonl`에 `schema_conflict` 추가 + startup permanent 재등록. 와이어링
  전이라 `release_holder` 호출처가 없어 관측 동작은 불변 — 단독 머지 가능.
- **Plan 2 — 와이어링 + `system_notify`.** `Dispatcher.system_notify`, server.py의
  `register_schema`·`register_bot`·`unregister` 핸들러에 holder 전달 + 충돌 통지,
  `dead_session_sweep`·`dead_bot_sweep`에 `release_holder`. Plan 1의 API에 의존.
