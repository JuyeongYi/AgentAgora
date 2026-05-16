# AgoraBot — 봇 플러그인 베이스 클래스

`agent_agora/bot.py`의 `AgoraBot`은 AgentAgora 봇을 **플러그인 방식**으로 작성하기
위한 추상 베이스 클래스다. 봇 작성자는 이 클래스를 상속하고 `handle()` 하나만
구현하면 된다 — 연결·등록·wait 루프·결과 emit·해제 같은 프로토콜
보일러플레이트는 전부 베이스가 소유한다.

## 4단계 레시피

```python
import asyncio
from agent_agora.bot import AgoraBot

class MyBot(AgoraBot):
    # 1. 설정 선언
    INSTANCE_ID = "my_bot"
    DESCRIPTION = "무엇을 하는 봇인지"
    SUBSCRIBE_SCHEMAS = ["my_task"]
    SCHEMAS = {"my_task": { ... }}        # 인라인 등록할 스키마(선택)

    # 2. handle() 구현
    async def handle(self, cmd: dict):
        payload = cmd.get("payload") or {}
        return {"result": ...}            # 3. 반환 → bot_reply로 자동 회신

# 4. 실행
if __name__ == "__main__":
    asyncio.run(MyBot.main())
```

`EchoBot`(`echo_bot.py`)이 가장 작은 완성 예제다 — 설정 선언 + `handle()` 한 줄.

## 설정 (클래스 속성)

| 속성 | 필수 | 설명 |
|---|---|---|
| `INSTANCE_ID` | ✅ | 봇의 instance_id |
| `DESCRIPTION` | | 봇 설명 |
| `BOT_MODE` | | `"handler"`(기본) 또는 `"observer"` |
| `SUBSCRIBE_SCHEMAS` | handler 필수 | 구독할 `bot-task` 스키마 이름 목록 |
| `SCHEMAS` | | register_bot 때 인라인 등록할 스키마 `{name: {kind,purpose,body}}` |
| `EMIT_SCHEMAS` | | emit할 스키마 선언(선택) |
| `DEFAULT_URL` | | 서버 URL 기본값. `AGORA_URL` 환경변수 > 생성자 인자로 덮어쓴다 |
| `WAIT_TIMEOUT_MS` | | bounded wait 주기(ms, 기본 30000). 서버 dead-bot sweep이 의존하는 heartbeat. |

- **handler 모드**: `SUBSCRIBE_SCHEMAS`의 msgtype으로 dispatch된 메시지를 fan-out 수신.
- **observer 모드**: 스키마 무관 전체 메시지를 cc로 수신. 자기 자신이 emit한
  메시지가 되돌아오는 루프는 베이스가 자동으로 걸러낸다.

## `handle()` 회신 계약

`handle(cmd)`이 처리 결과를 돌려주는 방법은 두 가지이고, 섞어 쓸 수 있다.

1. **값을 반환** → 베이스가 `bot_reply` 스키마로 감싸 원 발신자에게 회신.
   ```python
   async def handle(self, cmd):
       return {"echo": cmd["payload"]["text"]}
   ```
2. **`self.emit()` 직접 호출** → 다중 회신·커스텀 스키마·observer 봇용. 이 경우
   `handle()`은 `None`을 반환한다.
   ```python
   async def handle(self, cmd):
       await self.emit({"echo": "1"})
       await self.emit({"echo": "2"})
       return None
   ```

- 반환값이 `None`이면 베이스는 회신하지 않는다.
- 둘 다 하면(직접 emit + 값 반환) 직접 emit한 것이 유효하고 반환값은 무시된다.
- `emit(payload)`에서 `payload`에 `msgtype`이 있으면 그대로, 없으면 `bot_reply`로
  감싼다.

## 에러 처리

`handle()`이 예외를 던지면 베이스가 `bot_error` 스키마로 원 발신자에게 자동
회신하고, **봇은 죽지 않고 다음 메시지를 계속 처리한다.** 한 건의 실패가 봇
전체를 멈추지 않는다. `register_bot` 실패만 치명적이다 — `__aenter__`에서 예외.

`register_bot` 실패는 `BotRegistrationError`로 raise되며, 그중 봇이 `SCHEMAS`로
선언한 스키마 이름이 이미 다른 body로 등록된 경우는 `SchemaConflictError`
(`BotRegistrationError`의 서브클래스)로 raise된다 — 스키마는 immutable이므로
이름을 바꾸거나 body를 기존 등록본과 일치시켜야 한다.

## 생명주기 보장

`AgoraBot`은 async context manager다.

```
__aenter__  →  streamable HTTP 연결 + initialize + register_bot
__aexit__   →  unregister + 세션 close + 트랜스포트 close
```

`__aexit__`는 정상 종료·예외·`KeyboardInterrupt` 무엇이든 **세션이 닫히기 전에**
`unregister`를 실행한다(`AsyncExitStack`의 LIFO 언와인드). 따라서 graceful 종료
시 stale 봇 등록이 남지 않는다.

> **왜 중요한가**: 서버의 `BotRegistry`에는 dead-session sweep이 없다
> (`InstanceRegistry`만 시간 경과로 청소된다). 봇이 명시적으로 `unregister`하지
> 않으면 죽은 등록이 서버 재시작 전까지 영구히 남는다. `AgoraBot`은 이를
> 구조적으로 막는다.
>
> 단, `kill -9`·크래시·네트워크 단절 같은 **비정상 종료**에는 `__aexit__`도 돌지
> 않는다. 그 경우는 서버 측 대책(봇 레지스트리용 TTL/sweep, 또는 MCP 세션
> teardown 훅)이 필요하다 — 클라이언트만으로는 완전히 해결되지 않는다.
> 서버는 이를 `dead_session_timeout` 경과 시 dead-bot sweep으로 정리하며,
> `AgoraBot.run()`의 bounded wait(`WAIT_TIMEOUT_MS`)가 heartbeat를 갱신해
> 살아있는 봇은 스윕되지 않는다.

## 실행

```bash
# 터미널 1 — 서버
python -m agent_agora --port 8420 --no-tls --no-timeout

# 터미널 2 — 봇 (계속 떠 있는다)
python examples/echo_bot/echo_bot.py

# 터미널 3 — 태스크 전송
python examples/echo_bot/send.py "안녕, 아고라!"
```

다른 포트면 봇·클라이언트에 `AGORA_URL` 환경변수를 준다
(예: `AGORA_URL=http://127.0.0.1:8455/mcp`).
