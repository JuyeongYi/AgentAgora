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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-agora-channel",
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
    content = (f"AgentAgora 인박스에 {pending}건 도착 (from: {src}). "
               f"agora.wait로 메시지를 수신해 처리하라.")
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
        pending = signal.get("pending", 0)
        if pending <= 0:
            continue                          # timeout heartbeat — emit 안 함
        content, meta = format_channel_notification(
            instance_id, pending, signal.get("sources", []))
        await emit(content, meta)
        # 워커가 큐를 드레인할 때까지 재발화 보류 (edge-triggered)
        while await peek_pending(instance_id) > 0:
            await asyncio.sleep(drain_poll_s)
