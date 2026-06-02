# Plan E — 레지스트리 일원화: 공통 베이스 `_BidirectionalRegistry` 설계

작성일: 2026-06-03
브랜치(예정): `refactor/registry-plan-e`
선행 분석: `docs/backlog.md`(§"후속 — 레지스트리 일원화 Plan E"), 2026-06-03 리팩토링 워크플로(전수 분석 → 적대적 검증)
선행 plan(의존): `dispatcher-hook-fire-public-api` — register/unregister/dead-sweep hook 발화를 공개 API로 먼저 승격해, Plan E가 건드리는 레이어 churn을 줄인다.

## 1. 배경과 문제

`InstanceRegistry`(`registry.py`)와 `BotRegistry`(`bot_registry.py`)는 **양방향 매핑
레지스트리**라는 동일한 골격을 각자 재구현한다. 둘 다:

- `_by_session: dict[str, InfoT]` + `_by_instance: dict[str, InfoT]` + `threading.Lock`
- `register`의 충돌 해소(같은 instance_id/session_id 재등록 시 stale 엔트리 제거 후 양쪽 dict 갱신)
- `resolve_session` / `resolve_instance_id`(미등록 시 `NotRegisteredError`)
- `unregister_session`
- `touch_last_seen`(`dataclasses.replace(info, last_seen_at=now)` 후 양쪽 dict 갱신)
- `list_*`(`list(self._by_instance.values())`)

이 중복은 두 레지스트리가 등록/해소/last-seen/dead-sweep 경로에서 **나란히 진화해야**
하는 부담을 낳는다(한쪽 수정 시 다른 쪽 누락 위험). backlog가 공통 베이스 추출을
"유력 후보"로 식별했다.

단, **봇과 워커의 동작 차이는 일원화 후에도 명시적으로 남아야 한다**:

| 구분 | `InstanceRegistry`(워커) | `BotRegistry`(봇) |
|------|--------------------------|-------------------|
| Info 타입 | `InstanceInfo`(role/cwd/wait_mode/accepting) | `BotInfo`(bot_mode/subscribe_schemas/emit_schemas) |
| 파생 인덱스 | 없음 | `_subscribers`(schema→handler봇), `_observers`(observer봇 집합) |
| `register` 후처리 | 없음 | bot_mode별 observer/subscriber 인덱스 채움 |
| detach 시 정리 | 양쪽 dict pop만 | dict pop + 파생 인덱스 정리(`_detach_locked`) |
| 고유 메서드 | `set_accepting` | `is_bot`, `subscribers_of`, `observers` |
| 에러 라벨 | "Session"/"Instance" | "Bot session"/"Bot" |
| operator 네임스페이스 | `is_operator`/`OPERATOR_PREFIX`(워커 전용) | 해당 없음 |
| ACL/expect_result | 매트릭스 ACL 대상·expect_result 대상 | ACL 면제·expect_result 대상 아님 |
| 재시작 복원 | (registry는 in-memory, 재접속 시 재등록) | 동일(주석에 명시) |

**핵심 위험:** `InstanceInfo`·`BotInfo`가 모두 `@dataclass(frozen=True)`이고 필드셋이
다르다. Generic 베이스가 두 이질적 frozen 타입의 `replace`·파생 인덱스를 추상화하는
과정에서 **타입이 아니라 런타임 회귀**가 주 위험이다(메모리: Pyright 신뢰 불가,
pytest가 정답). 영향 범위도 최대다 — `server.py`·`dispatcher.py`·`sweeper.py`·
`auto_register.py`가 곳곳에서 두 레지스트리를 구분해 쓴다. 따라서 risk = **medium-high**.

## 2. 설계 결정 트레일

### 2-1. detach 시맨틱을 `_detach_locked`로 통일한다

두 `register`의 충돌 해소는 **네트 효과가 동일**하다:

- `InstanceRegistry.register`: 충돌하는 cross-key만 pop(`existing_by_inst.session_id`를
  `_by_session`에서, `existing_by_sess.instance_id`를 `_by_instance`에서) 후 양쪽 덮어씀.
- `BotRegistry.register`: `_detach_locked(prior)`로 prior info를 **양쪽 dict + 파생 인덱스**에서
  완전 제거 후 양쪽 set.

베이스는 `BotRegistry`의 `_detach_locked` 방식(상위집합·더 깨끗)으로 통일한다.
워커는 파생 인덱스가 없으므로 `_on_detach_locked` 훅이 no-op이 되어 **현행 동작이
정확히 보존**된다. `InstanceRegistry.register`의 인라인 2-pop은 파생 인덱스가 없어
순수 cosmetic 통일이므로, 베이스 `register_info` 호출로 바꾸되 관측 동작은 불변.

### 2-2. 봇 고유 로직은 훅(hook)으로만 베이스에 노출한다

베이스는 봇을 **모른다**. 봇 고유 처리는 두 개의 빈 훅으로 격리:

- `_on_store_locked(info)`: register에서 info 저장 직후(락 보유) 호출 — `BotRegistry`가
  observer/subscriber 인덱스를 채움. `InstanceRegistry`는 미오버라이드(no-op).
- `_on_detach_locked(info)`: detach 시(락 보유) 호출 — `BotRegistry`가 파생 인덱스 정리.

이 훅 경계가 "봇은 ACL 면제·schema 구독·observer"라는 정책 분기를 **일원화가
자동 처리하지 않는다**는 backlog 경고를 구조로 못 박는다 — 베이스엔 그 개념이 없다.

### 2-3. 공개 시그니처 100% 보존 + 스냅샷 테스트로 강제

`register`/`resolve_session`/`resolve_instance_id`/`touch_last_seen`/`set_accepting`/
`list_instances`/`list_bots`/`is_bot`/`subscribers_of`/`observers`/`unregister_session`의
이름·인자·반환은 전부 보존한다. 호출처(server/dispatcher/sweeper/auto_register)는
**무변경**이 목표. Pyright를 못 믿으므로, 공개 표면을 import-time에 단언하는
**시그니처 스냅샷 테스트**를 선행 step으로 둔다(런타임 회귀 차단).

### 2-4. `threading.Lock`은 그대로 둔다

`registry.py:49`·`bot_registry.py:35`의 `threading.Lock`은 단일 asyncio 루프 환경에선
잉여지만(동기 메서드라 await 없음 → 원자적), **무해**하다. 락 타입 변경은 별개
관심사이며 Plan E의 동작-보존 범위를 벗어나므로 **하지 않는다**(베이스도 `threading.Lock` 유지).

## 3. 비목표 (Non-goals)

- 봇/워커 **동작 차이 변경 금지** — expect_result 대상 여부, schema 구독/fan-out,
  observer, ACL 면제는 현행 그대로. 일원화는 *중복 제거*지 *정책 통합*이 아니다.
- operator 네임스페이스(`is_operator`/`OPERATOR_PREFIX`/operator_id)를 베이스로 끌어올리지
  않는다 — 워커(대시보드 pseudo-instance) 전용. `registry.py`에 명시 유지.
- 공개 메서드 시그니처 변경 금지(스냅샷 테스트로 강제).
- 레지스트리 영속/재시작 복원 추가 금지 — 현행대로 in-memory + 재접속 재등록.
- `threading.Lock` → `asyncio.Lock` 전환 금지(§2-4).
- register 충돌 해소의 *정책* 변경 금지(큐 보존 등은 dispatcher 소관, 본 spec 무관).

## 4. 범위 — 작업 항목

### E-1. 공통 베이스 `_BidirectionalRegistry[InfoT]`

`agent_agora/registry.py`(또는 신규 `_registry_base.py`)에 Generic 베이스 도입.
`InfoT`는 `.instance_id: str`·`.session_id: str`·`.last_seen_at: str | None`을 갖는
frozen dataclass(Protocol로 경계 표현 가능, 런타임 영향 없음).

```python
InfoT = TypeVar("InfoT")

class _BidirectionalRegistry(Generic[InfoT]):
    _SESSION_LABEL: str = "Session"
    _INSTANCE_LABEL: str = "Instance"

    def __init__(self) -> None:
        self._by_session: dict[str, InfoT] = {}
        self._by_instance: dict[str, InfoT] = {}
        self._lock = threading.Lock()

    # --- 서브클래스 훅(락 보유 상태에서 호출) ---
    def _on_store_locked(self, info: InfoT) -> None: ...     # 봇: 파생 인덱스 채움
    def _on_detach_locked(self, info: InfoT) -> None: ...    # 봇: 파생 인덱스 정리

    def _detach_locked(self, info: InfoT) -> None:
        self._by_session.pop(info.session_id, None)
        self._by_instance.pop(info.instance_id, None)
        self._on_detach_locked(info)

    def register_info(self, info: InfoT) -> InfoT:
        with self._lock:
            prior = self._by_instance.get(info.instance_id)
            if prior is not None:
                self._detach_locked(prior)
            prior_sess = self._by_session.get(info.session_id)
            if prior_sess is not None:
                self._detach_locked(prior_sess)
            self._by_session[info.session_id] = info
            self._by_instance[info.instance_id] = info
            self._on_store_locked(info)
        return info

    def unregister_session(self, session_id: str) -> None:
        with self._lock:
            info = self._by_session.get(session_id)
            if info is not None:
                self._detach_locked(info)

    def resolve_session(self, session_id: str) -> InfoT:
        with self._lock:
            info = self._by_session.get(session_id)
        if info is None:
            raise NotRegisteredError(f"{self._SESSION_LABEL} '{session_id}' is not registered")
        return info

    def resolve_instance_id(self, instance_id: str) -> InfoT:
        with self._lock:
            info = self._by_instance.get(instance_id)
        if info is None:
            raise NotRegisteredError(f"{self._INSTANCE_LABEL} '{instance_id}' is not registered")
        return info

    def _replace_and_store_locked(self, instance_id: str, **changes) -> InfoT | None:
        info = self._by_instance.get(instance_id)
        if info is None:
            return None
        updated = replace(info, **changes)   # frozen dataclass면 타입 무관 동작
        self._by_instance[instance_id] = updated
        self._by_session[updated.session_id] = updated
        return updated

    def touch_last_seen(self, instance_id: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            self._replace_and_store_locked(instance_id, last_seen_at=now)

    def _list_all(self) -> list[InfoT]:
        with self._lock:
            return list(self._by_instance.values())
```

- 에러 라벨은 클래스 속성(`_SESSION_LABEL`/`_INSTANCE_LABEL`)로 분기 — 메시지 문자열
  현행 보존("Session/Instance" vs "Bot session/Bot").
- `_replace_and_store_locked`가 `touch_last_seen`·`set_accepting`의 공통 패턴을 흡수.
- `dataclasses.replace`는 `InfoT`를 몰라도 frozen dataclass면 동작 — Generic 안전.

### E-2. `InstanceRegistry`를 베이스로 구체화

```python
class InstanceRegistry(_BidirectionalRegistry[InstanceInfo]):
    _SESSION_LABEL = "Session"
    _INSTANCE_LABEL = "Instance"

    def register(self, session_id, instance_id, role="worker", description="",
                 cwd="", wait_mode=None) -> InstanceInfo:
        info = InstanceInfo(..., wait_mode=wait_mode or "unknown")
        return self.register_info(info)

    def set_accepting(self, instance_id, accepting) -> None:
        with self._lock:
            updated = self._replace_and_store_locked(instance_id, accepting=accepting)
        if updated is None:
            raise NotRegisteredError(f"Instance '{instance_id}' is not registered")

    def list_instances(self) -> list[InstanceInfo]:
        return self._list_all()
```

- `_on_store_locked`/`_on_detach_locked` 미오버라이드(no-op) — 파생 인덱스 없음.
- `is_operator`/`OPERATOR_PREFIX`는 모듈 레벨 그대로(베이스 무관).
- 주의: `set_accepting`은 미등록 시 raise — 베이스 헬퍼가 `None` 반환하므로 서브클래스에서
  raise(현행 동작 보존).

### E-3. `BotRegistry`를 베이스로 구체화

```python
class BotRegistry(_BidirectionalRegistry[BotInfo]):
    _SESSION_LABEL = "Bot session"
    _INSTANCE_LABEL = "Bot"

    def __init__(self):
        super().__init__()
        self._subscribers: dict[str, set[str]] = {}
        self._observers: set[str] = set()

    def _on_store_locked(self, info: BotInfo) -> None:
        if info.bot_mode == "observer":
            self._observers.add(info.instance_id)
        else:
            for s in info.subscribe_schemas:
                self._subscribers.setdefault(s, set()).add(info.instance_id)

    def _on_detach_locked(self, info: BotInfo) -> None:
        self._observers.discard(info.instance_id)
        for s in info.subscribe_schemas:
            subs = self._subscribers.get(s)
            if subs is not None:
                subs.discard(info.instance_id)
                if not subs:
                    self._subscribers.pop(s, None)

    def register(self, session_id, instance_id, description, bot_mode,
                 subscribe_schemas=(), emit_schemas=()) -> BotInfo:
        info = BotInfo(...)
        return self.register_info(info)

    def is_bot(self, instance_id) -> bool: ...
    def subscribers_of(self, schema_name) -> set[str]: ...
    def observers(self) -> set[str]: ...
    def list_bots(self) -> list[BotInfo]:
        return self._list_all()
```

- 봇 파생 인덱스 정리·채움이 훅으로만 일어나므로 `register_info`/`unregister_session`/
  `_detach_locked`는 베이스에서 공유.

### E-4. `registry-last-seen-test-seam` 흡수 (dropped 항목 통합)

리팩토링 워크플로에서 단독 머지 가치 낮아 drop된 `registry-last-seen-test-seam`(테스트
위생 — `_backdate` 대체)을 여기서 함께 정리한다. `touch_last_seen`이 베이스로 옮겨가므로,
테스트가 last_seen을 과거로 조작하던 seam을 `dead_session_sweep(now=future)` 같은
**무-API 방식**으로 대체한다(테스트 전용, 공개 표면 무변경).

## 5. 데이터/상태 변경 요약

| 위치 | 변경 |
|------|------|
| `registry.py` (또는 `_registry_base.py`) | `_BidirectionalRegistry[InfoT]` 신설; `InstanceRegistry`가 상속, `register`/`set_accepting`/`list_instances`만 구체화. `is_operator`/`OPERATOR_PREFIX` 유지 |
| `bot_registry.py` | `BotRegistry`가 베이스 상속; `_on_store_locked`/`_on_detach_locked` 훅으로 파생 인덱스 처리; `register`/`is_bot`/`subscribers_of`/`observers`/`list_bots` 구체화 |
| `server.py`·`dispatcher.py`·`sweeper.py`·`auto_register.py` | **무변경 목표**(공개 시그니처 보존). 변경 발생 시 회귀로 간주 |
| `tests/` | 시그니처 스냅샷 테스트 신설 + last-seen-seam 대체 |

## 6. 에러/엣지 케이스

- **워커 instance_id 재등록(다른 세션)**: `register_info`가 prior를 `_detach_locked` →
  새 info로 양쪽 갱신. 현행 2-pop과 네트 동일(§2-1).
- **봇 session 충돌**: prior_sess `_detach_locked`가 파생 인덱스까지 정리 → 누수 없음(현행 보존).
- **observer 봇 detach**: `_on_detach_locked`가 `_observers.discard` — schema 구독 봇과 분기 보존.
- **`set_accepting` 미등록 instance**: 베이스 헬퍼 `None` 반환 → 서브클래스 raise(현행 메시지 보존).
- **frozen `replace` 호환**: `InstanceInfo`/`BotInfo` 모두 frozen이라 `dataclasses.replace`
  동작 — 단, 미래에 비-dataclass Info가 들어오면 깨짐(Protocol·테스트로 경계 명시).
- **에러 메시지 회귀**: "Bot session '...' is not registered" 등 문자열을 테스트가 substring으로
  매칭할 수 있으므로 라벨 분기를 정확히 보존.

## 7. 테스트 계획 (TDD — 선행 동작 고정 → 베이스 추출)

선행(베이스 추출 *전*에 그린 상태로 작성):

1. **시그니처 스냅샷 테스트** (신규, 핵심): `InstanceRegistry`/`BotRegistry`의 공개
   메서드 존재·인자명·기본값을 import-time에 단언(`inspect.signature`). Pyright 불신
   대응 — 런타임 회귀 차단.
2. **충돌 해소 동작 고정**: 워커 instance_id 2-pop, 봇 session-collision `_detach` 정합.
3. **봇 파생 인덱스 정합**: subscribe→`subscribers_of`, observer→`observers`, detach 후 정리.
4. **`touch_last_seen` frozen replace** 양쪽 dict 갱신.
5. **에러 라벨**: 미등록 resolve가 "Session/Instance" vs "Bot session/Bot" 메시지 반환.

추출 후: 위 + 기존 `test_registry.py`·`test_v4_bot_registry.py` + 의존 소스 테스트
(`test_v4_routing`·`test_sweeper`·`test_auto_register`·`test_v4_server_cwd`·server 경로)가
**안전망**. `dispatcher-hook-fire-public-api` 선행으로 register/unregister/dead-sweep 레이어
churn이 줄어, Plan E는 레지스트리 두 파일에 집중.

검증: `.venv/Scripts/python.exe -m pytest tests/ -v` 전체 통과. 단계별 명시 경로 커밋.

## 8. 후속 (이 spec 범위 밖)

- 패키지 재구성(평면 28모듈 → 서브패키지)에서 `registry.py`/`bot_registry.py`/베이스가
  `identity/` 같은 서브패키지로 묶일 경우, 그 plan에서 import 경로만 갱신(별도 워크플로 판단 중).
- `register_bot`의 server→domain 이동(effort S 변형)은 Plan E 스코핑 시 함께 고려(현재 drop).
