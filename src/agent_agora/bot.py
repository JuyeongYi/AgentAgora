"""AgoraBot — AgentAgora 봇 플러그인 베이스 클래스.

외부 봇 플러그인은 이 클래스를 상속하고 `handle()`만 구현하면 된다. 연결·
등록·wait 루프·결과 emit·해제 같은 프로토콜 보일러플레이트는 전부 베이스가
소유한다.

  서브클래스 선언   INSTANCE_ID / DESCRIPTION / SUBSCRIBE_SCHEMAS / SCHEMAS ...
  __aenter__       streamable HTTP 연결 + initialize + register_bot
  run()            구독 스키마로 fan-out된 메시지를 long-poll 수신 → handle()
  handle()         (추상) 처리 결과를 반환 → 베이스가 bot_reply로 감싸 emit
  __aexit__        unregister + 연결 해제 — graceful 종료 시 stale 등록 방지

생명주기를 async context manager로 묶었으므로, 정상 종료·예외·KeyboardInterrupt
무엇이든 세션이 닫히기 전에 unregister가 실행된다. BotRegistry에는 dead-session
sweep이 없어(InstanceRegistry만 청소된다) 명시적 unregister가 빠지면 죽은 봇
등록이 영구히 남는다 — 이 클래스가 그걸 구조적으로 막는다.

서버를 먼저 띄워야 한다:
    python -m agent_agora --port 8420 --no-tls --no-timeout
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import sys
import traceback
from abc import ABC, abstractmethod
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Windows 콘솔 코드 페이지와 무관하게 한글 print가 깨지지 않도록 UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass


def _result_json(result) -> dict:
    """call_tool 결과(CallToolResult)의 text content에서 첫 JSON 객체를 추출한다."""
    for item in result.content:
        text = getattr(item, "text", None)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


class BotRegistrationError(RuntimeError):
    """register_bot 단계 실패. AgoraBot.__aenter__에서 raise되어 봇이 기동하지 못한다."""


class SchemaConflictError(BotRegistrationError):
    """봇이 SCHEMAS로 선언한 스키마 이름이 이미 다른 body로 등록돼 있다.
    스키마는 immutable이다 — 이름을 바꾸거나 기존 정의에 맞춰야 한다."""


class AgoraBot(ABC):
    """Agora 봇 플러그인 베이스. 상속해서 `handle()`만 구현하면 된다."""

    # ── 서브클래스가 선언하는 설정 ──
    INSTANCE_ID: str = ""                  # 필수 — 봇의 instance_id
    DESCRIPTION: str = ""
    BOT_MODE: str = "handler"              # "handler" | "observer"
    SUBSCRIBE_SCHEMAS: list[str] = []      # handler 모드: 구독할 bot-task 스키마
    SCHEMAS: dict[str, dict] = {}          # 인라인 등록 스키마 {name: {kind,purpose,body}}
    EMIT_SCHEMAS: list[str] = []
    DEFAULT_URL = "http://127.0.0.1:8420/mcp"
    WAIT_TIMEOUT_MS: int = 30000           # wait_notify heartbeat 주기 — 서버에 heartbeat 갱신

    def __init__(self, url: str | None = None) -> None:
        if not self.INSTANCE_ID:
            raise ValueError("서브클래스는 INSTANCE_ID를 선언해야 한다")
        # url 우선순위: 인자 > AGORA_URL 환경변수 > DEFAULT_URL
        self.url = url or os.environ.get("AGORA_URL") or self.DEFAULT_URL
        self._session: ClientSession | None = None
        self._stack: contextlib.AsyncExitStack | None = None
        self._current_cmd_id: str | None = None   # handle() 진행 중인 cmd id
        self._emitted = False                     # handle() 중 직접 emit 했는지

    # ── 서브클래스가 구현 ──
    @abstractmethod
    async def handle(self, cmd: dict) -> Any:
        """수신 메시지 1건 처리.

        반환값이 None이 아니면 베이스가 `emit()`으로 회신한다(=① 경로).
        None이면 베이스는 회신하지 않는다 — 직접 `self.emit()`을 부른 경우
        (=③ 경로) 또는 의도적 무응답. handle()이 예외를 던지면 베이스가
        `bot_error`를 자동 emit하고 봇은 계속 돈다.
        """

    # ── 베이스 제공 ──
    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("세션이 없다 — `async with` 안에서 써야 한다")
        return self._session

    @staticmethod
    def now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _channel_wait_url(self) -> str:
        """GET /channel/wait의 전체 URL. self.url(MCP 엔드포인트)에서 /mcp
        꼬리를 떼어 같은 호스트·포트의 채널 경로를 유도한다."""
        base = self.url.rstrip("/")
        if base.endswith("/mcp"):
            base = base[: -len("/mcp")]
        return base.rstrip("/") + "/channel/wait"

    async def _http_wait(self, instance_id: str, timeout_ms: int) -> dict:
        """GET /channel/wait로 인박스 도착을 long-poll한다.

        blocking long-poll 도구 agora.wait_notify의 대체 경로 — 봇은 MCP 도구
        표면 대신 이 HTTP 엔드포인트를 쓴다. 호출 실패는 봇을 죽이지 않는다:
        {error:...}를 반환하고, 이어지는 flush가 인박스를 드레인하고
        last_seen heartbeat를 갱신한다."""
        try:
            async with httpx.AsyncClient(timeout=None) as http:
                resp = await http.get(
                    self._channel_wait_url(),
                    params={"instance_id": instance_id,
                            "timeout_ms": timeout_ms})
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001 — 봇은 wait 실패에 죽지 않는다
            return {"error": f"channel/wait HTTP 호출 실패: {exc!r}"}

    async def emit(
        self,
        payload: Any,
        *,
        in_reply_to: str | None = None,
        target: str | None = None,
    ) -> dict:
        """결과를 emit한다 (③ 경로 — handle 안에서 직접 호출 가능).

        payload가 `msgtype` 키를 가진 dict면 그대로 보내고, 아니면 `bot_reply`
        스키마로 감싼다.

        target 지정 시: 해당 워커/봇 인박스에 직접 전달. in_reply_to를 쓰지 않는다.
        target 미지정 시: in_reply_to 생략 시 현재 처리 중인 cmd에 회신하고,
        처리 중인 cmd가 없으면 msgtype 구독 봇에게 schema-routed fan-out 된다.
        """
        args: dict = {"payload": payload}
        if target is not None:
            args["target"] = target
            # target 직접 지정 시 in_reply_to 불필요 (서버가 동시 지정을 거부)
        else:
            effective_reply_to = in_reply_to if in_reply_to is not None else self._current_cmd_id
            if effective_reply_to is not None:
                args["in_reply_to"] = effective_reply_to
        if not (isinstance(payload, dict) and "msgtype" in payload):
            args["payload"] = {
                "msgtype": "bot_reply",
                "from": self.INSTANCE_ID,
                "ts": self.now(),
                "result": payload,
            }
        res = _result_json(await self.session.call_tool("agora.bot_emit", args))
        if "error" in res:
            print(f"[{self.INSTANCE_ID}] emit 실패: {res['error']}", flush=True)
        self._emitted = True
        return res

    async def run(self) -> None:
        """수신 루프. GET /channel/wait HTTP 엔드포인트로 도착을 기다리고
        (event-driven — 구독 스키마 메시지가 라우팅되면 즉시 리턴), flush로
        인박스를 드레인한다. 메시지 없이 heartbeat 주기로 wait가 리턴해도
        이어지는 flush가 last_seen을 갱신해 dead-bot sweep용 heartbeat를
        유지한다."""
        print(f"[{self.INSTANCE_ID}] 수신 루프 시작 "
              f"(mode={self.BOT_MODE}, subscribe={self.SUBSCRIBE_SCHEMAS}, "
              f"heartbeat={self.WAIT_TIMEOUT_MS}ms).", flush=True)
        while True:
            await self._http_wait(self.INSTANCE_ID, self.WAIT_TIMEOUT_MS)
            res = _result_json(await self.session.call_tool("agora.flush", {}))
            for cmd in res.get("commands", []):
                await self._dispatch(cmd)

    async def _dispatch(self, cmd: dict) -> None:
        """수신 cmd 1건을 handle()로 넘기고, ①/③ 회신 규칙·에러 처리를 적용한다."""
        source = cmd.get("source")
        # observer 모드에서 자기 자신이 emit한 메시지가 cc로 되돌아오는 루프 방지.
        if source == self.INSTANCE_ID:
            return
        cmd_id = cmd.get("id")
        self._current_cmd_id = cmd_id
        self._emitted = False
        try:
            result = await self.handle(cmd)
        except Exception as exc:  # noqa: BLE001 - 한 건 실패가 봇 전체를 죽이면 안 됨
            print(f"[{self.INSTANCE_ID}] handle 예외 <- {source}: {exc!r}", flush=True)
            await self._emit_error(exc, in_reply_to=cmd_id)
            return
        finally:
            self._current_cmd_id = None
        # ① 경로: handle이 값을 반환했고 ③ 경로(직접 emit)를 쓰지 않았으면 자동 회신.
        # 둘 다 했으면 직접 emit한 것이 유효하고 반환값은 무시된다.
        if result is not None and not self._emitted:
            await self.emit(result, in_reply_to=cmd_id)
        print(f"[{self.INSTANCE_ID}] handled <- {source}", flush=True)

    async def _emit_error(self, exc: Exception, *, in_reply_to: str | None) -> None:
        with contextlib.suppress(Exception):
            await self.session.call_tool("agora.bot_emit", {
                "payload": {
                    "msgtype": "bot_error",
                    "from": self.INSTANCE_ID,
                    "ts": self.now(),
                    "error_code": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                },
                "in_reply_to": in_reply_to,
            })

    # ── async context manager — 생명주기 ──
    async def __aenter__(self) -> "AgoraBot":
        stack = contextlib.AsyncExitStack()
        await stack.__aenter__()
        try:
            conn = await stack.enter_async_context(streamable_http_client(self.url))
            session = await stack.enter_async_context(
                ClientSession(conn[0], conn[1]))
            await session.initialize()
            reg = _result_json(await session.call_tool(
                "agora.register_bot", self._register_args()))
            if "error" in reg:
                raise self._registration_error(reg["error"])
            # 등록 성공 뒤에 unregister 콜백을 스택에 push한다. 종료 시 스택은
            # LIFO로 풀리므로 unregister → 세션 close → 트랜스포트 close 순서가
            # 보장된다 — 즉 세션이 살아있는 동안 unregister가 실행된다.
            stack.push_async_callback(self._unregister, session)
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._session = session
        print(f"[{self.INSTANCE_ID}] register_bot 완료 "
              f"(구독: {reg.get('subscribe_schemas', [])}).", flush=True)
        return self

    async def __aexit__(self, *_exc) -> None:
        stack, self._stack = self._stack, None
        if stack is not None:
            await stack.aclose()   # unregister → 세션 close → 트랜스포트 close
        self._session = None

    def _register_args(self) -> dict:
        args: dict[str, Any] = {
            "instance_id": self.INSTANCE_ID,
            "description": self.DESCRIPTION,
            "bot_mode": self.BOT_MODE,
        }
        if self.BOT_MODE == "handler":
            args["subscribe_schemas"] = self.SUBSCRIBE_SCHEMAS
        if self.SCHEMAS:
            args["schemas"] = self.SCHEMAS
        if self.EMIT_SCHEMAS:
            args["emit_schemas"] = self.EMIT_SCHEMAS
        return args

    def _registration_error(self, error: str) -> BotRegistrationError:
        """register_bot 에러 메시지를 분류한다. 서버는 에러 코드 없이 메시지
        문자열만 반환하므로(`{"error": "<msg>"}`), schema_immutable 메시지의
        안정적 부분('이미 등록')으로 스키마 이름 충돌을 식별한다 — 서버 메시지
        텍스트(errors.py의 ERROR_MESSAGES['schema_immutable'])에 결합돼 있다."""
        if self.SCHEMAS and "이미 등록" in error:
            names = ", ".join(sorted(self.SCHEMAS))
            return SchemaConflictError(
                f"register_bot 실패 — 스키마 이름 충돌: {error}\n"
                f"이 봇이 SCHEMAS로 선언한 스키마({names}) 중 하나가 이미 다른 "
                f"body로 등록돼 있습니다. 스키마는 immutable입니다 — SCHEMAS의 "
                f"이름을 바꾸거나 body를 기존 등록본과 일치시키세요."
            )
        return BotRegistrationError(f"register_bot 실패: {error}")

    async def _unregister(self, session: ClientSession) -> None:
        with contextlib.suppress(Exception):
            await session.call_tool("agora.unregister", {})
            print(f"[{self.INSTANCE_ID}] unregister 완료.", flush=True)

    @classmethod
    async def main(cls, url: str | None = None) -> None:
        """진입점. 서브클래스에서 `asyncio.run(MyBot.main())`으로 실행한다."""
        try:
            async with cls(url) as bot:
                await bot.run()
        except KeyboardInterrupt:
            print(f"\n[{cls.INSTANCE_ID}] 종료.", flush=True)
