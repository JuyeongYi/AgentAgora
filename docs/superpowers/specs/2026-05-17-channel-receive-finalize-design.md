# 채널 모드 수신 모델 확정 — Design Spec

- 날짜: 2026-05-17
- 대상 코드: `src/agent_agora/` (server·dispatcher·bot SDK·channel_adapter·__main__) + cc-agora 프리셋·문서
- 베이스: 채널 모드(구현·머지됨), comm-matrix 거버넌스(머지됨)
- 결정 방식: 사용자와 sequential 합의 (§5 결정 트레일)

## 1. 배경 / 목적

채널 모드가 정상 동작하면서 두 가지 폴링 시대 잔재가 문제로 드러났다.

1. **블로킹 `agora.wait`** — 워커가 `agora.wait`를 긴 timeout으로 호출하면 "계속 대기 상태에 빠지는" 일이 잦다. 채널이 wake를 담당하므로 워커는 깨어난 뒤 *이미 쌓인 것만 1회 드레인*하면 된다 — 블로킹 대기 자체가 불필요하고 해롭다.
2. **재시작 시 이전 대화 복구** — 서버 시작 때 `restore_from_persistence()`가 이전 실행의 미배달 메시지를 인박스 큐에 다시 채운다. 잦은 재시작(테스트 세션)에선 stale 메시지가 워커에게 드레인돼 혼란을 준다.

해결 — 채널 모드를 수신 모델의 기준으로 확정한다. 블로킹 `agora.wait`를 논블로킹 `agora.flush`로 대체하고, 서버 재시작은 기본 클린 스타트로 바꾼다.

## 2. 비범위

- **`agora.wait_notify`** — 채널 어댑터가 쓰는 비파괴 long-poll. 도착 즉시 리턴하므로 "stuck" 문제가 없다. 이름·동작 유지.
- **`wait_mode` 서버 잔재** — `agora.register`의 `wait_mode` 인자, `X-Agora-Wait-Mode` 헤더, `AutoRegisterMiddleware`의 처리. 폴링 시대 유물로 이제 무의미하나, 제거는 별도 cleanup — 본 spec 범위 밖.
- **comm-matrix·admin 엔드포인트** — 직전 작업, 무관.
- **저장소 밖 워커 디렉터리**(`C:\Users\Jooyo\AgoraTest\` 등) — 사용자 테스트 셋업. 본 spec 머지 후 사용자가 갱신.

## 3. 설계

### 3.1 서버 재시작 — 클린 스타트 기본

`run_server`는 현재 무조건 `dispatcher.restore_from_persistence()`를 호출한다. 이를 바꾼다:

- **기본** — restore하지 않는다. 시작 시 이전 실행의 미배달(undrained) 메시지를 전부 `drained_at=now, drop_reason='server_restart'`로 마킹해 논리적으로 비운다(인박스 큐에 싣지 않음). 대화 기록(conversations·messages 행)은 audit용으로 남는다.
- **`--restore` CLI 플래그** — 주면 기존 동작(`restore_from_persistence()` — 미배달 메시지를 인박스 큐로 복구, 크래시 내구성)을 한다.

`__main__.py`의 `parse_args`에 `--restore`(`action="store_true"`) 추가. `run_server`는 `args.restore`면 `dispatcher.restore_from_persistence()`, 아니면 `dispatcher.drop_inflight_on_restart()`(신규 — 미배달 메시지 일괄 drop 마킹)를 호출.

### 3.2 `agora.wait` 제거 → `agora.flush` 신설

블로킹 destructive drain `agora.wait`를 제거하고, 논블로킹 destructive drain `agora.flush`를 만든다.

- **`agora.flush`** — 호출 시점에 큐에 쌓인 메시지를 *즉시* 드레인해 반환한다. `timeout_ms` 인자 없음 — 절대 블로킹하지 않으므로 "stuck"이 구조적으로 불가능하다. 필터(`from_sources`·`by_conversation`·`sort`)는 `agora.wait`에서 그대로 가져온다. 반환 형태는 `{"commands": [...]}` 유지. 호출자는 등록돼 있어야 하며, 호출은 호출자의 `last_seen`을 갱신한다(heartbeat — §3.3).
- Dispatcher: `wait()` 블로킹 메서드를 제거하거나 논블로킹 `flush()`로 대체한다(`timeout_ms`/대기 로직 삭제, 큐 즉시 드레인만).
- **`taskSupport` 힌트 제거** — `server.py`의 `_WAIT_TOOL_NAME` + `_list_tools_with_wait_execution`(`agora.wait`에 `execution.taskSupport="optional"`을 붙이던 블록)을 제거한다. `flush`는 논블로킹이라 background task로 돌릴 이유가 없고, `wait_notify`는 비-Claude-Code 클라이언트(어댑터)만 쓰므로 힌트가 불필요하다.
- `X-Agora-Wait-Timeout-Ms` 헤더 처리(`agora.wait`의 timeout 해석)는 도구와 함께 사라진다.

### 3.3 `AgoraBot` SDK — `wait_notify` + `flush` 루프

봇은 구독 스키마로 fan-out된 메시지를 받는 event-driven 수신자다 — 블로킹 destructive wait가 애초에 불필요했다. `bot.py`의 `run()` 루프를 바꾼다:

- 현재: `while True: agora.wait(timeout_ms=WAIT_TIMEOUT_MS)` → commands 처리.
- 신규: `while True: agora.wait_notify(instance_id=INSTANCE_ID, timeout_ms=WAIT_TIMEOUT_MS)` (도착 즉시, 없으면 heartbeat 주기로 리턴) → `agora.flush()` (드레인) → commands 처리.

**heartbeat 보존** — 현재 봇의 bounded `agora.wait`는 `last_seen`을 갱신해 서버 `dead_bot_sweep`의 근거가 된다. 신규 루프에서는 `agora.flush` 호출이 `last_seen`을 갱신하므로, `wait_notify`가 메시지 없이 heartbeat-timeout으로 리턴해도 이어지는 `flush`가 heartbeat를 유지한다. `WAIT_TIMEOUT_MS`(기본 30000)는 `wait_notify`의 주기로 그대로 쓴다. 봇 *작성자*는 영향 없음 — `handle()` 인터페이스 불변, SDK 내부만 변경.

### 3.4 채널 메시지·프리셋·문서 갱신

- `channel_adapter.py` — `format_channel_notification`·`CHANNEL_INSTRUCTIONS`의 `agora.wait(timeout_ms=0)` → `agora.flush`.
- `plugin/cc-agora/templates/presets/*.md` — `## 메시지 수신` 절의 `agora.wait` 언급 → `agora.flush`.
- `docs/channel-mode.md`·`docs/usage-guide.md`·`README.md` — `agora.wait` 도구 레퍼런스·서술을 `agora.flush`로. `agora.wait_notify`는 그대로.
- 예제(`examples/`)·테스트 — `agora.wait`를 쓰는 곳을 `agora.flush`로 전환.

### 3.5 영향받는 파일 (요약)

| 파일 | 변경 |
| --- | --- |
| `src/agent_agora/__main__.py` | `--restore` 플래그, `run_server` 분기 |
| `src/agent_agora/dispatcher.py` | `wait()` → 논블로킹 `flush()`; `drop_inflight_on_restart()` 신규 |
| `src/agent_agora/server.py` | `agora.wait` 도구 → `agora.flush`; `taskSupport` 힌트 블록 제거 |
| `src/agent_agora/bot.py` | `run()` 루프 → `wait_notify` + `flush` |
| `src/agent_agora/channel_adapter.py` | 채널 메시지 `agora.wait` → `agora.flush` |
| `plugin/cc-agora/templates/presets/*.md` | `agora.wait` → `agora.flush` |
| `docs/*`·`README.md`·`examples/*` | 도구명 갱신 |
| `tests/*` | `agora.wait` 테스트를 `agora.flush`로 전환, 재시작 동작 테스트 추가 |

## 4. 동작 흐름 (확정 모델)

- **워커(채널 모드)** — idle → 채널 알림으로 wake → `agora.flush`로 인박스 드레인 → 처리 → `agora.dispatch` 답신 → idle. 블로킹 대기 없음.
- **봇** — `wait_notify`(도착 대기, event-driven) → `agora.flush` 드레인 → `handle()` → emit. destructive 블로킹 wait 없음.
- **서버 재시작** — 기본: 미배달 메시지 drop, 클린 스타트. `--restore`: 이전 in-flight 복구.

## 5. 결정 트레일

- **결정 1 — 클린 스타트 기본, `--restore` opt-in.** 대안: 복구 기본+`--fresh` / 복구 완전 제거. 사용자 — 잦은 재시작 용도에선 stale cruft 실이 내구성 득보다 크다. 기본을 클린으로, 크래시 내구성이 필요한 경우만 `--restore`. 복구 기능 자체는 보존.
- **결정 2 — 블로킹 `agora.wait` 제거, `agora.flush` 신설.** 채널이 wake를 담당하므로 워커는 논블로킹 1회 드레인이면 충분하다. `agora.wait(timeout_ms=0)`을 쓰지 않고 별도 `agora.flush` 도구를 두는 이유: 기존 `agora.wait`의 `timeout_ms=0`은 *무한 블로킹*을 의미해 의미가 정반대다 — 논블로킹 드레인은 별도 이름의 도구여야 혼동이 없다.
- **결정 3 — `agora.wait_notify`는 유지.** 비파괴 long-poll이고 도착 즉시 리턴한다 — "stuck" 문제의 원인이 아니다. 채널 어댑터 인프라이자 봇 수신 루프의 event 메커니즘.
- **결정 4 — 봇은 `wait_notify` + `flush`.** 봇은 구독 스키마 매칭 시 즉발하는 event-driven 수신자라 destructive 블로킹 wait가 불필요했다. `wait_notify`가 도착 즉시 리턴(event)하고 `flush`가 드레인한다. 봇의 heartbeat(`dead_bot_sweep` 근거)는 `agora.wait`가 갱신하던 `last_seen`을 `agora.flush`가 이어받아 유지한다.
- **결정 5 — `taskSupport` 힌트 제거.** `agora.wait`의 long-blocking 특성 때문에 붙였던 MCP `execution.taskSupport` 힌트는 논블로킹 `flush`엔 불필요하다.
