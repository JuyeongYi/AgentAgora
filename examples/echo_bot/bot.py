"""테스트용 Agora echo 봇.

AgentAgora 서버에 MCP client로 붙어 agora.wait long-poll로 메시지를 받고,
받은 payload를 발신자에게 그대로 echo 회신한다.

봇 spec(register_bot · schema registry)은 아직 구현 전이므로, 본 봇은 현재
v3 서버 도구만으로 동작한다 — agora.register / agora.wait / agora.dispatch.
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Windows 콘솔 코드 페이지와 무관하게 한글 print가 깨지지 않도록 UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

AGORA_URL = "http://127.0.0.1:8420/mcp"
INSTANCE_ID = "bot_echo"


def _extract_commands(result) -> list[dict]:
    """call_tool 결과(CallToolResult)의 text content에서 commands 배열을 추출한다."""
    for item in result.content:
        text = getattr(item, "text", None)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and "commands" in data:
            return data["commands"]
    return []


async def main() -> None:
    async with streamablehttp_client(AGORA_URL) as conn:
        # streamablehttp_client는 (read, write, ...) 형태를 yield — 앞 둘만 사용.
        read, write = conn[0], conn[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "agora.register",
                {
                    "instance_id": INSTANCE_ID,
                    "role": "bot",
                    "description": "테스트용 echo 봇 — 받은 메시지를 발신자에게 그대로 회신한다.",
                },
            )
            print(f"[{INSTANCE_ID}] 등록 완료. wait 루프 시작.", flush=True)
            while True:
                res = await session.call_tool("agora.wait", {"timeout_ms": 0})
                for cmd in _extract_commands(res):
                    source = cmd.get("source")
                    if not source:
                        continue
                    await session.call_tool(
                        "agora.dispatch",
                        {
                            "target": source,
                            "payload": {"echoed": cmd.get("payload"), "from": INSTANCE_ID},
                            "in_reply_to": cmd.get("id"),
                        },
                    )
                    print(f"[{INSTANCE_ID}] echo -> {source}", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n[{INSTANCE_ID}] 종료.", flush=True)
