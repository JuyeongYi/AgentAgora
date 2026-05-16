"""EchoBot — AgoraBot 세부 구현 예제.

`echo_task`(msgtype) 메시지를 구독해서, 들어온 text를 그대로 `bot_reply`로
회신하는 핸들러 봇이다. AgoraBot을 상속하면 봇 하나가 **설정 선언 + handle()
한 줄**로 끝난다는 걸 보여준다 — 연결·등록·wait 루프·envelope 조립·unregister는
전부 AgoraBot이 소유한다.

실행 (서버가 먼저 떠 있어야 한다):
    python -m agent_agora --port 8420 --no-tls --no-timeout   # 터미널 1
    python examples/echo_bot/echo_bot.py                       # 터미널 2

태스크는 examples/echo_bot/send.py 로 보낸다:
    python examples/echo_bot/send.py "안녕, 아고라!"
"""
from __future__ import annotations

import asyncio

from agent_agora.bot import AgoraBot


class EchoBot(AgoraBot):
    INSTANCE_ID = "bot_echo"
    DESCRIPTION = "예제 echo 봇 — echo_task의 text를 bot_reply로 회신한다."
    SUBSCRIBE_SCHEMAS = ["echo_task"]

    # 구독 스키마를 register_bot 때 인라인으로 같이 등록한다(idempotent).
    SCHEMAS = {
        "echo_task": {
            "kind": "bot-task",
            "purpose": "echo 봇 입력 — text를 그대로 되돌려받는다.",
            "body": {
                "type": "object",
                "required": ["msgtype", "text"],
                "properties": {
                    "msgtype": {"type": "string", "const": "echo_task"},
                    "text": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    }

    async def handle(self, cmd: dict):
        # 반환값은 AgoraBot이 bot_reply.result로 감싸 원 발신자에게 회신한다.
        text = (cmd.get("payload") or {}).get("text", "")
        return {"echo": text}


if __name__ == "__main__":
    asyncio.run(EchoBot.main())
