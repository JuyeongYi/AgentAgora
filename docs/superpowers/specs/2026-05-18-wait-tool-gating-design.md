# wait-tool-gating — 설계

- 상태: 설계 완료, 구현 대상
- 작성: 2026-05-18
- 브랜치: `wait-tool-gating`

## 1. 문제

채널 모드 워커(Claude Code 인스턴스)의 MCP 도구 표면에 블로킹 long-poll
도구 `agora.wait_notify`가 노출돼 있다. 이 도구는 `agora-channel` 어댑터와
`AgoraBot` SDK가 인박스 도착을 감지하려고 쓰는 내부용 도구다. 그런데 MCP
도구로 등록돼 있으므로 워커 Claude Code 본체에도 그대로 보인다.

워커가 `agora.wait_notify`를 직접 호출하면:

- **턴이 블로킹된다.** `wait_notify`는 메시지가 올 때까지(또는 timeout까지)
  리턴하지 않는다. 채널 모드의 전제 — "워커는 idle로 기다리다 push 알림에
  깨어난다" — 가 깨진다. 워커가 스스로 long-poll에 들어가면 채널 알림을
  처리할 턴 자체가 없다.
- **혼란을 준다.** 워커 입장에서 `agora.flush`(논블로킹 드레인)와
  `agora.wait_notify`(블로킹 대기)가 둘 다 보이면 어느 쪽을 써야 할지
  모호하다. 채널 모드 워커는 `agora.flush`만 쓰면 된다.

`agora.wait_notify`는 어댑터·봇 SDK의 인프라 도구이지 워커용 도구가 아니다.
워커의 도구 표면에서 들어내야 한다.

## 2. 목표

1. 채널 모드 워커의 MCP 도구 표면에서 `agora.wait_notify`를 기본 제거한다.
2. `agora-channel` 어댑터가 인박스 도착을 감지하는 경로를 MCP 도구가 아닌
   별도 채널로 옮긴다 — 어댑터는 워커와 같은 도구 표면을 공유하지 않아야
   한다.
3. `AgoraBot` SDK도 같은 별도 채널을 쓰게 한다 — 봇은 MCP 도구를 쓰지만
   `wait_notify`만은 인프라 경로로 분리한다.
4. `wait_notify`를 도구로 여전히 필요로 하는 호출자(수동 디버깅, 레거시
   클라이언트)를 위해 옵트인 플래그(`--add-wait`)를 남긴다.

비목표:

- `dispatcher.wait_notify` 메서드 자체의 시맨틱은 바꾸지 않는다 (블로킹
  long-poll, 비파괴, advisory, 미등록 instance_id 허용).
- 컴팩션/SessionStart 훅 관련 작업은 별도 트랙 — 건드리지 않는다.

## 3. 설계

### 3.1 `GET /channel/wait` HTTP 엔드포인트 (always-on)

브로커에 항상 켜진 HTTP 라우트를 새로 둔다. `dashboard_routes`·`file_routes`와
같은 패턴 — Starlette `Route`를 `streamable_http_app()`에 append한다.

```
GET /channel/wait?instance_id=<id>&timeout_ms=<ms>
```

- `instance_id` (필수, 쿼리 파라미터) — 감시할 instance_id.
- `timeout_ms` (선택, 쿼리 파라미터) — long-poll timeout(ms). 생략 시 서버
  기본값(`--default-wait-timeout-ms` / `--no-timeout`). `wait_notify` 도구와
  동일한 의미.

핸들러는 `dispatcher.wait_notify(instance_id, timeout_ms)`를 그대로
호출하고 그 결과 dict(`{instance_id, pending, sources}`)를 JSON으로 반환한다.
`wait_notify` 도구가 하던 일과 정확히 같다 — 단지 전송 경로가 MCP 도구
호출이 아니라 HTTP GET이다.

오류 처리:

- `instance_id` 누락 → `400 {"error": "..."}`.
- `DispatcherClosed` (서버 셧다운 중) → `503 {"error": "server is
  shutting down"}`.

localhost 전용·토큰 없음 — `file_routes`·`dashboard_routes`와 동일하게
서버의 `127.0.0.1` 바인딩에 의존한다. `wait_notify`는 advisory·비파괴
peek이므로 인박스 내용을 노출하지 않는다 (`pending` 개수와 `sources`
목록만).

이 라우트는 `--add-wait` 플래그와 무관하게 **항상** 등록된다 — 어댑터·봇
SDK의 동작이 의존하기 때문이다.

### 3.2 MCP `agora.wait_notify` 도구는 기본 비등록 + `--add-wait` 게이팅

`create_agora_app`에 `add_wait: bool = False` 파라미터를 추가한다.
`agora.wait_notify` 도구의 `@mcp.tool` 등록을 `if add_wait:` 블록 안으로
옮긴다. 기본값이 `False`이므로 도구는 기본적으로 등록되지 않는다.

CLI(`__main__.py`)에 `--add-wait` 플래그(`action="store_true"`)를 추가한다.
`_build_app`에 `add_wait` 파라미터를 더해 `create_agora_app`까지 전달한다.

- `agent-agora ...` (플래그 없음) → 워커 도구 표면에 `wait_notify` 없음.
- `agent-agora --add-wait ...` → `wait_notify` 도구 등록 (레거시·디버깅용).

`file_store`가 `share_file`·`fetch_file` 도구를 옵셔널 등록하는 기존
패턴과 같은 방식이다.

### 3.3 `agora-channel` 어댑터를 HTTP로 전환

어댑터의 `_make_broker_callables`가 `agora.wait_notify`를 MCP 도구로
호출하는 부분(`broker_session.call_tool("agora.wait_notify", ...)`)을
`GET /channel/wait` HTTP 호출로 바꾼다.

- 어댑터는 이미 `--broker`로 브로커 MCP URL(`http://127.0.0.1:8420/mcp`)을
  받는다. `/channel/wait`의 베이스 URL은 이 MCP URL에서 `/mcp` 경로
  꼬리를 떼어 유도한다 (`http://127.0.0.1:8420`).
- `peek_pending`은 그대로 `agora.peek` MCP 도구를 쓴다 — `agora.peek`는
  논블로킹·비파괴이고 워커 도구 표면에 그대로 남아도 무해하다. 이 작업의
  범위는 블로킹 `wait_notify` 한 도구만이다.
- HTTP 클라이언트는 `httpx` (이미 의존성 — `mcp`가 끌어온다)를 쓴다.
- HTTP 호출이 실패하면 `wait_notify` 콜러블이 `{"error": ...}` dict를
  반환한다. `watch_loop`는 이미 `{"error": ...}` 신호를 보면 backoff하므로
  이 계약을 유지하면 루프 로직은 변경 없다.

`_run_watch`가 브로커 MCP 세션을 여는 구조는 유지한다 (`peek` 도구 호출에
여전히 필요). `wait_notify` 콜러블만 HTTP를 쓰도록 바꾼다.

### 3.4 `AgoraBot` SDK를 HTTP로 전환

`AgoraBot.run()`의 수신 루프가 `agora.wait_notify` MCP 도구를 호출하는
부분(`self.session.call_tool("agora.wait_notify", ...)`)을 `GET
/channel/wait` HTTP 호출로 바꾼다.

- 봇은 `self.url`(`http://127.0.0.1:8420/mcp`)을 안다. `/channel/wait`
  베이스 URL은 어댑터와 같은 방식으로 `/mcp` 꼬리를 떼어 유도한다.
- `agora.flush`·`agora.bot_emit`·`agora.register_bot` 등 다른 도구
  호출은 모두 그대로 MCP 세션을 쓴다.
- HTTP 호출이 실패해도 봇은 죽지 않는다 — 로그를 남기고 다음 루프로
  넘어간다(`flush`가 어차피 인박스를 드레인하고 `last_seen` heartbeat를
  갱신한다). 봇의 `WAIT_TIMEOUT_MS` heartbeat 시맨틱은 유지된다.

봇은 더 이상 `wait_notify` MCP 도구에 의존하지 않으므로, `--add-wait`
없이 뜬 브로커에서도 정상 동작해야 한다.

### 3.5 도구 표면 정리 요약

| 경로 | 워커 도구 표면 | 어댑터·봇 사용 경로 |
| ---- | ------------- | ------------------ |
| `agora.wait_notify` (MCP 도구) | 기본 **없음**, `--add-wait` 시에만 | 사용 안 함 |
| `GET /channel/wait` (HTTP) | (도구 아님) | 어댑터·봇이 인박스 감지에 사용 |
| `agora.flush` (MCP 도구) | 있음 | 워커·봇이 인박스 드레인에 사용 |
| `agora.peek` (MCP 도구) | 있음 | 어댑터가 드레인 폴링에 사용 |

## 4. 영향 범위

수정 파일:

- `src/agent_agora/server.py` — `create_agora_app`에 `add_wait` 파라미터,
  `wait_notify` 도구 등록을 게이팅.
- `src/agent_agora/channel_routes.py` (신규) — `GET /channel/wait` 라우트.
- `src/agent_agora/__main__.py` — `--add-wait` CLI 플래그, `_build_app`에
  `add_wait` 전달, `run_server`에서 `channel_routes.register` 호출.
- `src/agent_agora/channel_adapter.py` — `wait_notify` 콜러블을 HTTP로.
- `src/agent_agora/bot.py` — `run()` 수신 루프를 HTTP `wait_notify`로.

테스트:

- `tests/test_channel_routes.py` (신규) — `GET /channel/wait` 라우트.
- `tests/test_main.py` — `--add-wait` 플래그 파싱·게이팅.
- `tests/test_v4_wait_notify.py` — `wait_notify` 도구는 기본 비등록,
  `--add-wait` 시 등록.
- `tests/test_channel_adapter.py` — HTTP `wait_notify` 콜러블.
- `tests/test_v4_bot_sdk.py` — 봇 `run()`이 HTTP `wait_notify`를 쓴다.

문서:

- `docs/channel-mode.md` — 동작 흐름의 `agora.wait_notify` 언급을
  `GET /channel/wait`로 갱신.

## 5. 결정 트레일

- **왜 HTTP 라우트인가 (MCP 도구 분리가 아니라)?** 어댑터는 워커 Claude
  Code의 자식 stdio 프로세스다. 어댑터가 자기만의 MCP 도구 네임스페이스를
  가질 수는 없다 — 브로커가 단일 도구 카탈로그를 모든 MCP 클라이언트에
  노출하기 때문이다. HTTP 라우트는 도구 카탈로그 바깥이므로 워커 표면을
  오염시키지 않는다. `file_routes`·`dashboard_routes`가 이미 같은 이유로
  HTTP 라우트를 쓴다.
- **왜 `/channel/wait`는 always-on인가?** 어댑터·봇 SDK의 동작이
  의존한다. `--add-wait` 게이팅 뒤에 두면 플래그 없는 브로커에서 채널
  모드가 통째로 깨진다. 라우트는 advisory·비파괴 peek이라 always-on이어도
  안전하다.
- **왜 `--add-wait` 옵트인 플래그를 남기나?** 수동 디버깅·레거시 MCP
  클라이언트가 `wait_notify` 도구를 호출하는 시나리오가 있을 수 있다.
  완전 제거 대신 옵트인으로 두면 회귀 안전망이 된다. 기본값은 비등록 —
  워커 표면 정리가 기본 동작이다.
- **왜 `agora.peek`는 그대로 두나?** `peek`는 논블로킹·비파괴 스냅샷이라
  워커 턴을 막지 않는다. 이 작업의 문제는 *블로킹* long-poll 한 도구다.
  `peek` 게이팅은 범위 밖.
