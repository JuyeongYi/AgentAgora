"""echo 봇에게 태스크 하나를 보내고 회신을 받아 출력하는 일회성 워커 클라이언트.

워커 입장에서 본 v4 흐름을 보여준다:

  register   — 세션을 워커로 등록
  dispatch   — target 생략 → payload의 msgtype(`echo_task`)을 구독한 봇에게
               schema-routed fan-out (결정 25). 어떤 봇에게 갔는지는 응답으로 확인.
  flush      — 봇의 bot_emit이 in_reply_to로 되돌려준 `bot_reply`를 즉시 드레인

사전 조건: 서버가 떠 있고 `bot_echo`(bot.py)가 먼저 등록돼 있어야 한다.
`echo_task` 스키마는 봇이 register_bot 때 등록하므로, 봇이 없으면 dispatch가
`no_route`/`unknown_msgtype`로 실패한다.

사용:
    python send.py "보낼 메시지"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

# 기본 포트는 8420. 다른 포트면 AGORA_URL 환경변수로 덮어쓴다.
AGORA_URL = os.environ.get("AGORA_URL", "http://127.0.0.1:8420/mcp")
INSTANCE_ID = "worker_demo"


def _result_json(result) -> dict:
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


async def main(message: str) -> None:
    async with streamable_http_client(AGORA_URL) as conn:
        read, write = conn[0], conn[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "agora.register",
                {"instance_id": INSTANCE_ID, "role": "worker",
                 "description": "echo 봇 데모용 일회성 워커."},
            )

            # target 생략 → echo_task를 구독한 봇에게 schema-routed.
            disp = _result_json(await session.call_tool(
                "agora.dispatch",
                {"payload": {"msgtype": "echo_task", "text": message}},
            ))
            if "error" in disp:
                print(f"[{INSTANCE_ID}] dispatch 실패: {disp['error']}", flush=True)
                print("  → echo 봇(bot.py)이 먼저 떠 있는지 확인하세요.", flush=True)
                return
            routed = [d["instance_id"] for d in disp.get("dispatched_to", [])]
            print(f"[{INSTANCE_ID}] dispatch 완료 — 라우팅된 봇: {routed}", flush=True)

            # 봇의 bot_reply 회신을 드레인. agora.flush는 즉시 반환 — 봇이 빠르게 처리하지 못했다면 재시도 필요.
            res = _result_json(await session.call_tool("agora.flush", {}))
            commands = res.get("commands", [])
            if not commands:
                print(f"[{INSTANCE_ID}] 회신 없음 — 봇이 살아 있는지 확인하거나 잠시 뒤 재시도하세요.", flush=True)
            for cmd in commands:
                print(f"[{INSTANCE_ID}] <- {cmd.get('source')} : "
                      f"{json.dumps(cmd.get('payload'), ensure_ascii=False)}", flush=True)

            await session.call_tool("agora.unregister", {})


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "안녕, 아고라!"
    asyncio.run(main(msg))
