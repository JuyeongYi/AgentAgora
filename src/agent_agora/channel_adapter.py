"""agora-channel 어댑터 — per-worker stdio MCP 채널 서버.

워커 Claude Code가 자식으로 spawn하는 stdio MCP 서버. 브로커의
agora.wait_notify로 워커 인박스 도착을 감지하고, claude/channel 알림으로
워커 턴을 깨운다. 자세한 설계는
docs/superpowers/specs/2026-05-16-channel-adapter-design.md.

실행: python -m agent_agora.channel_adapter --instance-id <id> --broker <url>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification

CHANNEL_INSTRUCTIONS = (
    "AgentAgora channel adapter. When an inbox notification arrives as a "
    "<channel source=\"agora-channel\"> tag, call agora.wait(timeout_ms=0) to "
    "drain your inbox (non-blocking — the channel already woke you), handle the "
    "messages, and reply with agora.dispatch. Do not enter a long blocking wait."
)

# 브로커 재연결 backoff (초) — 1, 2, 4, ... 30 cap.
_BACKOFF_START_S = 1.0
_BACKOFF_CAP_S = 30.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agora-channel",
        description="AgentAgora claude/channel 어댑터 — 워커 인박스 도착을 push 알림으로 전환",
    )
    parser.add_argument("--instance-id", required=True,
                        help="감시할 워커 instance_id")
    parser.add_argument("--broker", default="http://127.0.0.1:8420/mcp",
                        help="AgentAgora 브로커 MCP URL")
    parser.add_argument("--wait-timeout-ms", type=int, default=30000,
                        help="wait_notify 주기(ms) — heartbeat 겸 timeout")
    return parser.parse_args(argv)


def format_channel_notification(
    instance_id: str, pending: int, sources: list[str],
) -> tuple[str, dict[str, str]]:
    """claude/channel 알림의 (content, meta)를 만든다.

    content는 <channel> 태그 본문, meta의 각 키는 태그 속성이 된다.
    meta 키는 식별자만(letters/digits/underscore), 값은 문자열이어야 한다."""
    src = ", ".join(sources) if sources else "(unknown)"
    content = (f"New messages in your AgentAgora inbox (from: {src}). "
               f"Call agora.wait(timeout_ms=0) once to drain everything currently "
               f"queued and process all of it, then reply with agora.dispatch. "
               f"Do not block on a long wait — the channel wakes you again when "
               f"more arrives.")
    meta = {
        "instance_id": instance_id,
        "pending": str(pending),
        "sources": ",".join(sources),
    }
    return content, meta


async def watch_loop(
    instance_id: str,
    wait_notify,
    peek_pending,
    emit,
    *,
    wait_timeout_ms: int = 30000,
    drain_poll_s: float = 2.0,
) -> None:
    """edge-triggered 감시 루프.

    wait_notify(instance_id, timeout_ms) -> dict{pending, sources} 로 인박스
    도착을 블로킹 감지하고, pending이 0->N으로 올라설 때만 emit(content, meta)
    한다. emit 후에는 peek_pending(instance_id) -> int 가 0을 반환할 때까지
    폴링하다 wait_notify로 복귀한다 — 워커가 드레인하기 전 중복 알림 방지."""
    while True:
        signal = await wait_notify(instance_id, wait_timeout_ms)
        if isinstance(signal, dict) and "error" in signal:
            # 브로커 도구 에러 — 즉시 재시도하면 busy-loop. 잠깐 쉬고 재시도.
            await asyncio.sleep(drain_poll_s)
            continue
        pending = signal.get("pending", 0)
        if pending <= 0:
            continue                          # timeout heartbeat — emit 안 함
        content, meta = format_channel_notification(
            instance_id, pending, signal.get("sources", []))
        await emit(content, meta)
        # 워커가 큐를 드레인할 때까지 재발화 보류 (edge-triggered)
        while await peek_pending(instance_id) > 0:
            await asyncio.sleep(drain_poll_s)


# --- 브로커(HTTP MCP 클라이언트) 글루 ----------------------------------------

def _result_json(result) -> dict:
    """tool 호출 결과의 text content 중 첫 JSON 객체를 꺼낸다."""
    for item in getattr(result, "content", []) or []:
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


def _make_broker_callables(broker_session: ClientSession):
    """브로커 ClientSession에 바인딩된 (wait_notify, peek_pending)을 만든다."""

    async def wait_notify(instance_id: str, timeout_ms: int) -> dict:
        result = await broker_session.call_tool(
            "agora.wait_notify",
            {"instance_id": instance_id, "timeout_ms": timeout_ms},
        )
        return _result_json(result)

    async def peek_pending(instance_id: str) -> int:
        result = await broker_session.call_tool(
            "agora.peek", {"targets": [instance_id]},
        )
        data = _result_json(result)
        entry = data.get(instance_id) or {}
        depth = entry.get("queue_depth")
        return depth if isinstance(depth, int) else 0

    return wait_notify, peek_pending


# --- 채널(stdio MCP 서버) 글루 ----------------------------------------------

async def _emit(session: ServerSession, content: str, meta: dict[str, str]) -> None:
    """활성 ServerSession으로 notifications/claude/channel 알림을 raw로 보낸다.

    타입드 send_notification은 비표준 메서드를 받지 못하므로 write stream에
    JSONRPCNotification을 직접 쓴다."""
    raw = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/claude/channel",
        params={"content": content, "meta": meta},
    )
    await session._write_stream.send(SessionMessage(message=JSONRPCMessage(raw)))


# --- main() — stdio 채널 서버 + 브로커 감시 동시 실행 -------------------------

async def _run_watch(
    instance_id: str,
    session: ServerSession,
    broker: str,
    wait_timeout_ms: int,
) -> None:
    """브로커에 HTTP MCP 클라이언트로 붙어 watch_loop를 돌린다.

    연결이 끊기면 backoff 후 재연결한다 — 절대 크래시하지 않는다."""
    backoff = _BACKOFF_START_S
    while True:
        try:
            async with streamable_http_client(broker) as conn:
                async with ClientSession(conn[0], conn[1]) as broker_session:
                    await broker_session.initialize()
                    backoff = _BACKOFF_START_S  # 연결 성공 — backoff 리셋
                    wait_notify, peek_pending = _make_broker_callables(
                        broker_session)

                    async def emit(content: str, meta: dict[str, str]) -> None:
                        # 채널 측 write stream이 닫힌 경우(부모 Claude Code
                        # 종료로 stdin EOF → ServerSession 스트림 close)는
                        # 브로커 장애가 아니라 정상 종료 신호다. anyio의
                        # closed/broken 예외를 CancelledError로 변환해
                        # 아래 backoff(브로커 재연결) 핸들러가 아니라
                        # _run_watch의 CancelledError re-raise로 빠지게 한다.
                        try:
                            await _emit(session, content, meta)
                        except (anyio.ClosedResourceError,
                                anyio.BrokenResourceError) as exc:
                            raise asyncio.CancelledError from exc

                    await watch_loop(
                        instance_id, wait_notify, peek_pending, emit,
                        wait_timeout_ms=wait_timeout_ms,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 브로커 도달 불가/연결 끊김 — backoff 재연결
            print(
                f"[agora-channel] 브로커 연결 실패 ({exc!r}); "
                f"{backoff:.0f}s 후 재시도",
                file=sys.stderr, flush=True,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_CAP_S)


async def _serve_channel(
    instance_id: str, broker: str, wait_timeout_ms: int,
) -> None:
    """stdio 채널 서버를 띄우고, 핸드셰이크 완료 후 감시 태스크를 시작한다."""
    server = Server("agora-channel", instructions=CHANNEL_INSTRUCTIONS)
    init_opts = server.create_initialization_options(
        experimental_capabilities={"claude/channel": {}})

    async with stdio_server() as (read_stream, write_stream):
        async with ServerSession(read_stream, write_stream, init_opts) as session:
            watch_task: asyncio.Task | None = None
            try:
                # 첫 incoming_messages 항목 = 핸드셰이크 완료 신호.
                # 그 전에는 emit이 채널로 나가도 유실되므로 watch_loop를
                # 시작하지 않는다.
                async for _msg in session.incoming_messages:
                    if watch_task is None:
                        watch_task = asyncio.create_task(
                            _run_watch(instance_id, session, broker,
                                       wait_timeout_ms))
                # stdin EOF — 부모 Claude Code 종료. incoming_messages 소진.
            finally:
                if watch_task is not None:
                    watch_task.cancel()
                    try:
                        await watch_task
                    except asyncio.CancelledError:
                        pass  # cancel()로 인한 정상 종료
                    except Exception as exc:
                        # watch task의 비-CancelledError 예외는 진짜 버그다.
                        # 종료를 크래시시키진 않되 stderr로 가시화한다.
                        print(
                            f"[agora-channel] watch task 종료 중 예외: {exc!r}",
                            file=sys.stderr, flush=True,
                        )


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        await _serve_channel(
            args.instance_id, args.broker, args.wait_timeout_ms)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


def cli() -> None:
    """콘솔 스크립트 진입점 (동기). pyproject [project.scripts]가 가리킨다.

    채널 어댑터의 main은 async라 콘솔 스크립트 엔트리로 직접 못 쓴다 —
    이 동기 래퍼가 asyncio 런루프를 연다."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
