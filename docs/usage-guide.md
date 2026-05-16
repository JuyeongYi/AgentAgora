# AgentAgora 사용 가이드

처음 AgentAgora를 쓰는 사람을 위한 단계별 안내다. 서버를 띄우고, 에이전트를
붙이고, 메시지를 주고받고, 봇과 통신 제한까지 얹는 흐름을 순서대로 다룬다.

도구 시그니처 전체는 [`README.md`](../README.md)의 'MCP 도구 레퍼런스'를,
파이썬 스크립트만으로 굴려보는 최소 예제는 [`examples/README.md`](../examples/README.md)를
참조한다.

---

## 0. 큰 그림

AgentAgora는 **여러 에이전트 사이의 우체국**이다. 등장 인물은 셋:

- **워커(worker)** — `agora.register`로 등록하는 인스턴스. 보통 Claude Code
  인스턴스. 서로에게 일을 보내고(`dispatch`) 받는다(`wait`).
- **봇(bot)** — `agora.register_bot`으로 등록하는 스키마 구독자. 특정 종류의
  메시지를 자동으로 받아 처리하는, LLM이 아닐 수도 있는 처리기.
- **스키마(schema)** — 메시지의 모양을 정의하는 JSON Schema. 모든 메시지는
  `msgtype` 필드로 어떤 스키마를 따르는지 밝히고, 서버가 검증한다.

여기에 **통신 매트릭스**가 더해지면 "누가 누구에게 보낼 수 있는가"를 제한할 수 있다.

핵심 사이클은 **등록 → dispatch → wait → 답신**. 아래는 그걸 손에 익히는 과정이다.

---

## 1. 서버 띄우기

요구 사항은 Python 3.13+. 저장소 루트에서 설치한다.

```bash
pip install -e .      # 또는: uv sync
```

서버를 띄운다. 로컬 실험이면 `--no-tls`로 평문 HTTP가 편하다.

```bash
agent-agora --dir . --port 8420 --no-tls
```

```
AgentAgora starting on http://127.0.0.1:8420/mcp
  Data dir : .../.agentagora
  DB       : .../.agentagora/agora.db
  Cert     : (none -- HTTP mode, localhost only)
```

서버는 `<dir>/.agentagora/`에 상태를 둔다 — `agora.db`(SQLite), `schemas.jsonl`
(기본 스키마, 첫 기동에 자동 생성), `comm-matrix.csv`(있으면 로드).

> `agora.wait`는 기본적으로 60초 후 타임아웃한다. 워커가 무한 대기하길 원하면
> `--no-timeout`으로 서버를 띄우거나 `wait(timeout_ms=0)`을 쓴다.

---

## 2. 워커 붙이기

### Claude Code 인스턴스로 (권장)

각 워커 디렉토리의 `.mcp.json`에 서버를 등록한다. `X-Agora-*` 헤더를 주면
첫 요청에서 **자동 등록**된다 — 별도 `agora.register` 호출이 필요 없다.

```json
{
  "mcpServers": {
    "agora": {
      "type": "http",
      "url": "http://127.0.0.1:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "InstA",
        "X-Agora-Role": "orchestrator",
        "X-Agora-Description": "사용자 대면 오케스트레이터"
      }
    }
  }
}
```

> Windows에서는 `.mcp.json` 안의 경로·셸 문자열을 forward slash로 쓴다.
> backslash는 hook/spawn 레이어에서 escape 충돌을 일으킨다.

워커 디렉토리·`CLAUDE.md`·hook까지 한 번에 찍어내는 Claude Code 플러그인은
[`plugin/cc-agora/`](../plugin/cc-agora/)에 있다.

### 스크립트로

MCP 클라이언트 라이브러리로 직접 붙을 수도 있다. `agora.register`를 호출해
세션을 인스턴스 이름에 바인딩한다. 동작하는 예제는
[`examples/echo_bot/send.py`](../examples/echo_bot/send.py).

붙은 인스턴스는 `agora.instances`로, 봇은 `agora.bots`로, 둘 다 `agora.find`로
확인한다.

---

## 3. 메시지 주고받기

워커 A가 워커 B에게 일을 보낸다고 하자.

**A — 보내기:**

```
agora.dispatch(
  target="InstB",
  payload={
    "msgtype": "worker_freeform",
    "type": "task",
    "from": "InstA",
    "ts": "2026-05-16T03:00:00+00:00",
    "message": "src/ 아래 파일을 나열해줘"
  }
)
```

**B — 받기:** `agora.wait()`를 호출하면 큐에 쌓인 명령이 `commands` 배열로
돌아온다. 각 원소는 `id`·`source`·`payload`·`conversation_id` 등을 담은 envelope다.

**B — 답신:** 처리 후 발신자에게 되돌린다. `in_reply_to`에 원 명령의 `id`를
주면 같은 대화(`conversation_id`)로 묶인다.

```
agora.dispatch(
  target="InstA",
  in_reply_to="<받은 명령의 id>",
  payload={"msgtype": "worker_freeform", "type": "reply", "from": "InstB",
           "ts": "...", "message": "파일 목록: ..."}
)
```

- 전원에게 보내려면 `agora.broadcast(payload=...)` — 자기 자신은 제외된다.
- 같은 대화를 여러 라운드 이어가려면 `conversation_id`를 명시하거나 `in_reply_to`로
  상속받는다. 대화를 끝낼 땐 `closing=True` 또는 `agora.close_thread`.
- 큐 상태는 `agora.peek`로 비파괴 조회한다.

---

## 4. 스키마 — `msgtype` 규칙

**모든 메시지 payload는 JSON 객체이고 `msgtype` 필드가 필수다.** 서버는 그
`msgtype`으로 등록된 스키마를 찾아 payload를 검증한다. 빠지거나 틀리면 dispatch가
거부된다 (`payload_missing_msgtype` / `unknown_msgtype` / `schema_violation`).

기본 제공 스키마 6종:

| msgtype | kind | 용도 |
|---------|------|------|
| `worker_freeform` | conversation | 워커 간 자연어 통신 — `message`가 자유 텍스트 |
| `default` | conversation | 구조화 로그 엔트리 |
| `closing` | conversation | 대화 종결 통지 |
| `ack` | conversation | forward 통지 |
| `bot_reply` | bot-task | 봇 처리 결과 |
| `bot_error` | bot-task | 봇 처리 실패 |

워커끼리 대화할 땐 보통 `worker_freeform`이면 충분하다. 새 메시지 종류가
필요하면 `agora.register_schema(name, body, kind, purpose)`로 등록한다 — `body`에는
`msgtype` property가 반드시 있어야 하고, 한 번 등록하면 immutable이다. 등록된
스키마는 `agora.schemas` / `agora.schemas_list`로 조회한다.

스키마 `kind`는 둘 — `conversation`(워커↔워커)과 `bot-task`(봇 입출력). 봇이
구독하는 스키마는 반드시 `bot-task`여야 한다.

---

## 5. 봇 붙이기

봇은 **특정 `msgtype`을 구독해 자동으로 메시지를 받는** 처리기다. `register_bot`으로
등록하며, 워커와는 별도 네임스페이스다.

```
agora.register_bot(
  instance_id="bot_echo",
  description="echo_task를 받아 bot_reply로 회신",
  bot_mode="handler",
  subscribe_schemas=["echo_task"],
  schemas={"echo_task": {"kind": "bot-task", "purpose": "...",
                         "body": { ... msgtype property 포함 ... }}}
)
```

- `bot_mode="handler"` — `subscribe_schemas`의 메시지만 받는다.
- `bot_mode="observer"` — 스키마 무관 모든 메시지를 사본(cc)으로 받는다.
- `schemas` — 구독할 스키마를 등록과 동시에 인라인 정의 (별도 `register_schema`
  호출 생략).

봇도 `agora.wait`로 메시지를 받는다. 처리 결과는 dispatch가 아니라
**`agora.bot_emit`**으로 회신한다 — `in_reply_to`에 원 명령 `id`를 주면 원
발신자에게 돌아간다.

워커가 봇에게 보낼 땐 `target`을 **생략**하면 된다. 서버가 payload의 `msgtype`을
구독한 봇을 찾아 라우팅한다(schema-routed dispatch):

```
agora.dispatch(payload={"msgtype": "echo_task", "text": "안녕"})
# → echo_task를 구독한 봇(bot_echo)에게 자동 전달
```

봇은 보통 `agent_agora.bot.AgoraBot`을 상속해 `handle()`만 구현한다 — 자세한 SDK 사용법은 [`docs/bot-sdk.md`](bot-sdk.md).

동작하는 봇 전체 코드는 [`examples/echo_bot/echo_bot.py`](../examples/echo_bot/echo_bot.py).

---

## 6. 통신 매트릭스로 제한하기

기본적으로 워커는 누구에게나 dispatch할 수 있다. 흐름을 강제하고 싶을 때 —
예: 워커는 PM에게만 회신하고 워커끼리 직접 통신 금지 — **통신 매트릭스**를 쓴다.

매트릭스는 N×N CSV로 정의한다. 헤더 = `from` 목록, i번째 데이터 행 = i번째
인스턴스를 `to`로 했을 때 각 `from`의 허용 여부(`1`/`0`):

```
pm,coder,reviewer
0,1,1
1,0,0
1,0,0
```

위는 hub-and-spoke — `pm`은 양방향 자유, `coder`와 `reviewer`는 서로 직접
dispatch 불가.

적용하는 두 방법:

1. **startup 로드** — `<dir>/.agentagora/comm-matrix.csv`에 두면 서버 기동 때 읽는다.
2. **런타임 교체** — 운영자 전용 엔드포인트 `POST /admin/comm-matrix`(바디에 CSV)로
   재기동 없이 교체한다. 서버를 `AGORA_ADMIN_TOKEN` 환경변수와 함께 띄워야 활성화되고,
   요청엔 `Authorization: Bearer <token>` 헤더가 필요하다. 워커가 호출하던 옛
   `agora.register_comm_matrix` 도구는 제거됐다 — ACL은 운영자만 바꾼다.

매트릭스가 금지한 dispatch는 `comm_denied` 에러로 거부되고, broadcast에서는
금지 대상이 fan-out에서 빠진 채 `denied` 목록으로 보고된다. 봇으로 가는
schema-routed 메시지와 cc는 매트릭스 대상이 아니다.

ACL이 막고/통과시키는 걸 직접 보는 데모는 [`examples/comm_demo/`](../examples/comm_demo/).

---

## 자주 막히는 곳

- **`agora.wait`가 매번 빈 배열로 즉시 돌아온다** — 등록이 안 됐거나, 보내는
  쪽 `target`이 내 `instance_id`와 다르다. `agora.instances`로 확인.
- **dispatch가 `payload_missing_msgtype`로 거부된다** — payload에 `msgtype`이
  없다. 모든 메시지는 `msgtype` 필수 (4장 참조).
- **dispatch가 `unknown_msgtype`로 거부된다** — 그 `msgtype` 스키마가 등록 전이다.
  봇 스키마라면 봇을 먼저 띄워야 한다.
- **`target` 없는 dispatch가 `no_route`로 거부된다** — 그 `msgtype`을 구독한
  핸들러 봇이 하나도 없다.
- **dispatch가 `comm_denied`로 거부된다** — 통신 매트릭스가 그 쌍을 금지한다.
- **`Mcp-Session-Id` 헤더 없음** — 클라이언트가 Streamable HTTP transport를 안
  쓰고 있다. AgentAgora는 Streamable HTTP 전용이다.

---

## 다음 단계

- [`examples/README.md`](../examples/README.md) — 봇·매트릭스 데모를 실제로 실행.
- [`README.md`](../README.md) — 전체 도구 레퍼런스·CLI 옵션.
- [`docs/superpowers/specs/`](superpowers/specs/) — 각 기능의 설계 의도와 결정 트레일.
- [`plugin/cc-agora/`](../plugin/cc-agora/) — 워커 셋업을 자동화하는 Claude Code 플러그인.
