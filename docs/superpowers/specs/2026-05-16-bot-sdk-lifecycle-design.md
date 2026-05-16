# Bot SDK + 봇 생명주기 — Design Spec

- 날짜: 2026-05-16
- 대상 코드: AgentAgora 서버 (`src/agent_agora/`) + 예제·문서
- 베이스: [`2026-05-15-cc-agora-bots-design.md`](2026-05-15-cc-agora-bots-design.md) §3.1·§3.10·§3.11
- 결정 방식: 사용자와 sequential 합의 (§6 결정 트레일). 트리거 — 사용자가
  `AgoraBot` 베이스 클래스를 직접 구현해 두고 "설계에 반영" 요청.

## 1. 배경 / 목적

bots-design spec §3.10·§3.11은 봇 클라이언트 boilerplate를 wrap하는 SDK
(`agora_bot_sdk` 패키지의 `BotClient`)를 예고했으나, 그 구현을 cc-agora plugin
v2.2 범위로 미뤄두었다. plugin v2.2는 아직 미구현이다.

그 사이 사용자가 동등한 SDK를 `AgoraBot`이라는 이름으로 직접 구현했다
(`examples/echo_bot/agora_bot.py` + `echo_bot.py` + `AGORA_BOT.md`). spec 원안의
"register + wait loop + handler 디스패치 + reply 전송 wrap, 작성자는 handler만
구현"을 충족하고, 다음을 더 갖췄다:

- async context manager 기반 **생명주기 보장** — 정상 종료·예외·`KeyboardInterrupt`
  무엇이든 세션이 닫히기 전에 `agora.unregister`가 실행된다.
- `handle()` 예외 → `bot_error` 자동 emit, 봇은 죽지 않고 계속.
- observer 봇이 자기 emit을 cc로 되받는 루프를 자동 차단.
- `handle()` 회신 계약 — ① 반환값을 `bot_reply`로 자동 wrap, ③ `self.emit()`
  직접 호출. 둘 다 가능, 섞어 쓸 수 있음.

이 SDK는 동시에 **서버 측 설계 갭**을 드러냈다. `AGORA_BOT.md`가 명시하듯,
서버의 `BotRegistry`에는 dead-session sweep이 없다 — `Dispatcher.dead_session_sweep`은
`InstanceRegistry`(워커)만 청소한다. 봇이 `agora.unregister` 없이 죽으면(crash,
`kill -9`, 네트워크 단절) 그 등록이 서버 재시작 전까지 영구히 남고, 죽은 봇이
여전히 `BotRegistry.subscribers_of(msgtype)`에 잡혀 라우팅 대상이 된다 — 메시지가
죽은 봇의 큐에 쌓이고, 그 봇이 유일 구독자였다면 새 dispatch가 `no_route`도
못 받는다. SDK의 graceful unregister는 정상 종료만 막을 뿐 비정상 종료는 못 막는다.

본 spec은 둘을 하나의 설계로 묶는다 — **SDK를 정식 아티팩트로 승격**하고,
**서버가 죽은 봇을 TTL sweep으로 정리**하게 한다. 클라이언트와 서버 양쪽이 함께
있어야 견고한 봇 스토리가 된다.

## 2. 비범위 (후속)

- **swept 봇 자동 재등록** — `agora.wait`가 `NotRegisteredError`(스윕당함)를
  반환하면 SDK가 `register_bot`을 다시 호출해 복구하는 것. bounded heartbeat +
  넉넉한 sweep 임계 조합에서 healthy 봇은 절대 스윕되지 않으므로, 이는 장기
  네트워크 단절 대비용 nice-to-have다. 후속.
- **비정상 종료 즉시 감지** — MCP 세션 teardown 훅으로 연결 끊김 즉시 unregister.
  TTL sweep으로 충분하고, streamable-HTTP 세션 수명 훅은 까다롭다. 후속.
- **cc-agora plugin v2.2** — `/agora-spawn-bot` 슬래시, bot manifest 등. 본 spec은
  파이썬 SDK만 다룬다. plugin은 별도.
- **클라이언트 측 schema 검증** — SDK는 서버측 검증에 의존하고 로컬 사전 검증은
  하지 않는다. 서버가 모든 payload를 검증하므로 중복.

## 3. 설계

### 3.1 클라이언트 SDK — `agent_agora.bot.AgoraBot`

`examples/echo_bot/agora_bot.py`를 **`src/agent_agora/bot.py`**로 이동한다. 봇
작성자는 `from agent_agora.bot import AgoraBot`로 임포트한다. 별도 설치 패키지를
만들지 않는다 — `agent_agora` 패키지 하나에 서버와 봇 SDK가 함께 들어간다. 봇이
쓰는 `mcp` 클라이언트 라이브러리는 이미 `agent_agora`의 의존성이므로 새 의존성은
없다.

공개 표면은 사용자 구현을 그대로 채택한다:

- **설정 (클래스 속성)** — `INSTANCE_ID`(필수), `DESCRIPTION`, `BOT_MODE`
  (`"handler"`|`"observer"`), `SUBSCRIBE_SCHEMAS`, `SCHEMAS`(인라인 등록),
  `EMIT_SCHEMAS`, `DEFAULT_URL`, **`WAIT_TIMEOUT_MS`(신규 — §3.3)**.
- **`handle(cmd)`** — 추상. 작성자가 구현하는 유일한 메서드.
- **`emit(payload, in_reply_to=None)`** — 결과 emit. `payload`에 `msgtype`이
  있으면 그대로, 없으면 `bot_reply`로 wrap.
- **`run()`** — wait 루프. §3.3에서 bounded로 변경.
- **`main(url=None)`** — 클래스메서드 진입점. `asyncio.run(MyBot.main())`.
- **생명주기** — async context manager. `__aenter__` = streamable HTTP 연결 +
  `initialize` + `register_bot`. `__aexit__` = `unregister` → 세션 close →
  트랜스포트 close (`AsyncExitStack` LIFO 언와인드). 따라서 graceful 종료 시
  stale 봇 등록이 남지 않는다.
- **회신 계약** — ① `handle()`이 `None`이 아닌 값을 반환하면 베이스가 `emit()`으로
  회신. ③ `handle()` 안에서 `self.emit()`을 직접 호출(다중 회신·커스텀 스키마).
  둘 다 했으면 직접 emit이 유효, 반환값은 무시. `None` 반환 시 회신 없음.
- **에러 처리** — `handle()`이 예외를 던지면 베이스가 `bot_error` 스키마로 원
  발신자에게 자동 회신하고 봇은 다음 메시지를 계속 처리한다. `register_bot`
  실패만 치명적(`__aenter__`에서 raise).
- **observer 자기루프 차단** — `cmd["source"] == self.INSTANCE_ID`인 메시지는
  `handle()`에 넘기지 않는다.

### 3.2 서버 — BotRegistry dead-bot TTL sweep

`Dispatcher`에 `dead_bot_sweep()`을 추가한다 — `dead_session_sweep`의 봇 버전.

```
def dead_bot_sweep(self, now=None) -> list[str]:
    """last_seen_at(없으면 registered_at)이 dead_session_timeout을 넘은
    봇을 unregister한다. 정리된 봇 instance_id 목록을 반환."""
```

- `bot_registry.list_bots()`를 순회한다.
- 각 봇의 기준 시각 = `last_seen_at or registered_at`. 워커용 `dead_session_sweep`은
  `last_seen_at is None`이면 건너뛰지만, 봇 sweep은 `registered_at`으로 폴백한다 —
  등록 직후 첫 `wait` 전에 죽은 봇도 정리되도록.
- 기준 시각이 `now - dead_session_timeout_ms`보다 오래면 `bot_registry.unregister_session(bot.session_id)`로
  정리한다. `unregister_session`은 `_detach_locked`로 구독 역인덱스에서도 봇을
  떼어내므로, 정리 즉시 죽은 봇은 라우팅 대상에서 빠진다.
- 임계값은 기존 `Dispatcher._dead_session_timeout_ms`(`--dead-session-timeout-ms`,
  기본 30분)를 재사용한다 — 별도 CLI knob을 만들지 않는다.
- 스윕된 봇의 큐(`Dispatcher._queues[bot_id]`)에 남은 메시지는 건드리지 않는다 —
  워커용 `dead_session_sweep`과 동일하다. 같은 `instance_id`로 재등록하면 다음
  `wait`가 그 큐를 드레인하고, 재등록이 없으면 메시지 GC가 결국 정리한다.

`__main__.py`의 기존 60초 `_sweep_loop_60s`에 `dispatcher.dead_bot_sweep()` 한 줄을
추가한다. 새 백그라운드 태스크나 인프라는 없다.

`last_seen_at` 갱신은 추가 배선이 필요 없다 — `Dispatcher.wait()`가 이미
`_touch_last_seen()`을 통해 봇이면 `bot_registry.touch_last_seen()`을 호출한다.

### 3.3 SDK↔서버 heartbeat 계약

현재 SDK `run()`은 `agora.wait(timeout_ms=0)`(무한 블록)을 쓴다. 이러면 메시지를
받지 못하는 idle 봇은 `last_seen_at`이 갱신되지 않아 — `wait`가 리턴해야 갱신된다 —
TTL sweep에 살아있는데도 잘못 정리된다.

해결: `run()`의 wait 루프를 **bounded wait 반복**으로 바꾼다.

- 새 클래스 속성 **`WAIT_TIMEOUT_MS`**, 기본 `30000`(30초).
- `run()`은 `agora.wait(timeout_ms=self.WAIT_TIMEOUT_MS)`를 반복 호출한다. 빈
  결과(타임아웃)면 그냥 다시 호출한다. 따라서 idle 봇도 최소 `WAIT_TIMEOUT_MS`
  주기로 `last_seen_at`을 갱신한다.

**명문 계약** — spec·문서에 박는다:

> 봇은 `--dead-session-timeout-ms`보다 충분히 짧은 주기로 `agora.wait`를 호출해
> 살아있음을 알려야 한다. `AgoraBot` SDK는 bounded wait 루프로 이를 보장한다.
> SDK를 쓰지 않는 raw 봇 작성자는 이 heartbeat를 직접 책임진다.

기본값 조합(heartbeat 30초 ≪ 임계 30분)에서 healthy 봇은 절대 스윕되지 않는다.
진짜 죽은 봇과 30분 이상 단절된 봇만 정리된다.

### 3.4 examples · 문서 정리

- **`examples/echo_bot/bot.py` 삭제** — standalone 봇. AgoraBot 기반 `echo_bot.py`와
  중복이다. `echo_bot.py`가 표준 봇 예제가 된다.
- **`examples/echo_bot/agora_bot.py` 삭제** — `src/agent_agora/bot.py`로 이동했다.
- **`examples/echo_bot/echo_bot.py`** — 임포트를 `from agent_agora.bot import AgoraBot`로
  바꾼다. cwd 의존 임포트(`from agora_bot import ...`)를 제거.
- **`examples/echo_bot/run-bot.bat`** — `echo_bot.py`를 실행하도록 갱신.
- **`AGORA_BOT.md` → `docs/bot-sdk.md`** — SDK가 패키지 모듈이 되었으므로 정식 SDK
  문서로 격상해 `docs/`로 옮긴다. 임포트 경로·실행 경로를 갱신.
- **`examples/README.md` · `docs/usage-guide.md` · `README.md`** — 봇 작성 항목을
  `AgoraBot` SDK 기준으로 갱신하고 `docs/bot-sdk.md`를 링크.

### 3.5 테스트

- **`tests/test_v4_bot_sdk.py`** (신규) — SDK 단위 테스트. in-process 서버에 대고:
  생명주기(`__aenter__`/`__aexit__`가 register/unregister 보장), 회신 계약 ①/③,
  `handle()` 예외 → `bot_error` 자동 emit + 봇 생존, observer 자기루프 차단.
- **`dead_bot_sweep` 테스트** (`tests/test_v4_*`) — stale 봇 정리 + 구독 역인덱스
  detach 확인, healthy(최근 `last_seen`) 봇 보존, `last_seen_at is None`이면
  `registered_at` 폴백.

## 4. 구현 plan 분할

독립 머지 가능한 2개 plan으로 나눈다:

1. **서버측 dead-bot sweep** — `Dispatcher.dead_bot_sweep`, `__main__.py` 배선,
   sweep 테스트. 서버 단독 변경, 클라이언트와 독립.
2. **SDK 패키지화 + heartbeat + 예제·문서 정리** — `src/agent_agora/bot.py` 신설,
   `run()` bounded wait, examples 정리, `docs/bot-sdk.md`, SDK 테스트, 문서 갱신.

두 plan은 순서 무관하다 — sweep 임계(30분)가 넉넉해, SDK가 bounded wait를 쓰기
전에 sweep이 먼저 머지돼도 메시지를 가끔 받는 봇은 `last_seen`이 갱신돼 안전하다
(완전 idle + 무한 wait 봇만 30분 후 스윕되는데, 그건 SDK plan이 곧 해소한다).

## 5. 영향받는 파일 (요약)

| 파일 | 변경 |
| --- | --- |
| `src/agent_agora/bot.py` | 신규 — `AgoraBot` (examples에서 이동) |
| `src/agent_agora/dispatcher.py` | `dead_bot_sweep()` 추가 |
| `src/agent_agora/__main__.py` | `_sweep_loop_60s`에 `dead_bot_sweep` 호출 추가 |
| `examples/echo_bot/bot.py` | 삭제 |
| `examples/echo_bot/agora_bot.py` | 삭제 (`src/`로 이동) |
| `examples/echo_bot/echo_bot.py` | 임포트 경로 변경 |
| `examples/echo_bot/run-bot.bat` | `echo_bot.py` 실행으로 변경 |
| `examples/echo_bot/AGORA_BOT.md` | `docs/bot-sdk.md`로 이동·갱신 |
| `examples/README.md`·`docs/usage-guide.md`·`README.md` | 봇 섹션 갱신 |
| `tests/test_v4_bot_sdk.py` | 신규 |
| `tests/test_v4_*` | `dead_bot_sweep` 테스트 추가 |

## 6. 결정 트레일

- **결정 1 — 범위: 둘 다.** SDK 정식화와 서버측 dead-bot 정리를 하나의 설계로.
  대안 (SDK만 / 서버만 / 문서만)을 제시했으나, SDK의 graceful unregister가
  비정상 종료를 못 막는다는 한계를 SDK 문서 스스로 적시했으므로 — 견고한 봇
  스토리는 양쪽이 함께 있어야 성립한다.
- **결정 2 — SDK 배치: `src/agent_agora/bot.py`.** 대안은 별도 설치 패키지
  `agora-bot-sdk`(bots-design §3.11 원안)와 examples 유지. 별도 패키지는 PyPI
  배포 계획이 없는 현 단계에 버전·관리 부담만 크다(YAGNI). 봇이 쓰는 `mcp`
  클라이언트는 이미 의존성이므로 단일 패키지로 충분하다.
- **결정 3 — dead-bot 감지: last_seen TTL sweep.** 대안은 MCP 세션 teardown
  훅과 명시적 `agora.bot_heartbeat` 도구. TTL sweep은 `dead_session_sweep`·60초
  sweep 루프·`wait`의 `touch_last_seen`을 모두 재사용해 새 인프라가 없다. 세션
  teardown 훅은 streamable-HTTP에서 역사적으로 불안정했고(없는데 있다고 적혔던
  `SessionCloseMiddleware`), heartbeat 도구는 `wait`의 last_seen과 중복이다.
- **결정 4 — heartbeat 책임: SDK가 bounded wait로 보장.** TTL sweep은 봇이
  주기적으로 `last_seen`을 갱신해야 성립한다. 무한 wait는 idle 봇을 잘못 스윕하게
  하므로, SDK `run()`을 bounded wait 루프로 바꿔 SDK가 heartbeat를 소유한다.
  결정 1(둘 다)이 옳은 이유의 구체적 사례 — 서버 변경만으로는 안 되고 SDK 변경이
  짝을 이뤄야 한다.
