"""RoutingBot — superpowers 페르소나 간 위임 라우팅 봇.

`delegation_request` 스키마를 구독한다. 페르소나 워커가
다른 역할에 작업을 위임할 때 이 스키마로 메시지를 emit하면,
이 봇이 대상 워커를 찾아 payload를 직접 전달한다.

실행 (서버와 라우팅 봇을 함께 기동):
    python -m agent_agora --port 8420 --no-tls --no-timeout   # 터미널 1
    python plugin/superpowers/routing-bot/routing_bot.py       # 터미널 2

Task 1에서 추가된 agora.bot_emit의 target 파라미터를 활용한다.
봇 세션은 agora.dispatch를 호출할 수 없지만(서버 가드),
agora.bot_emit(target=<instance_id>)으로 특정 워커 인박스에 직접 전달한다.
"""
from __future__ import annotations

import asyncio
import json

import httpx
from mcp import ClientSession

from agent_agora.bot import AgoraBot, _result_json

_INSTANCE_ID = "bot_superpowers_router"


class RoutingBot(AgoraBot):
    INSTANCE_ID = _INSTANCE_ID
    DESCRIPTION = "superpowers persona routing bot. Subscribes delegation_request, resolves target worker, and delivers payload directly via agora.bot_emit(target=...)."
    SUBSCRIBE_SCHEMAS = ["delegation_request"]

    # delegation_request 스키마는 .agentagora/schemas.jsonl에 등록되어
    # 서버 기동 시 permanent 스키마로 로드된다. 봇이 인라인 SCHEMAS로
    # 중복 등록하면 body 일치 시 idempotent이지만, permanent 스키마와
    # body가 달라지는 실수를 막기 위해 SCHEMAS를 선언하지 않는다.
    SCHEMAS = {}

    async def handle(self, cmd: dict):
        """delegation_request 1건을 처리한다.

        처리 흐름:
        1. payload에서 to_persona / to_capability 추출
        2. to_persona 있으면 곧바로 사용; 없으면 agora.find(to_capability)로 resolve
        3. self.emit(forwarded_payload, target=resolved_instance_id) 로 직접 전달
           — Task 1에서 추가된 agora.bot_emit target 파라미터 활용
        """
        p = cmd.get("payload") or {}
        from_persona: str = p.get("from_persona", cmd.get("source", "unknown"))
        to_persona: str | None = p.get("to_persona")
        to_capability: str | None = p.get("to_capability")
        inner_payload: dict = p.get("payload") or {}
        context_summary: str | None = p.get("context_summary")

        # 대상 검증
        if not to_persona and not to_capability:
            raise ValueError(
                "delegation_request에 to_persona 또는 to_capability가 필요합니다. "
                f"수신 메시지 source={from_persona}"
            )

        # to_capability로 agora.find 조회
        if not to_persona:
            find_result = await self._call_find(to_capability)  # type: ignore[arg-type]
            results = find_result.get("results", [])
            workers = [r for r in results if r.get("kind") == "worker"]
            if not workers:
                raise ValueError(
                    f"to_capability='{to_capability}'에 해당하는 워커를 찾을 수 없습니다. "
                    "대상 페르소나 워커가 등록돼 있는지 확인하세요."
                )
            to_persona = workers[0]["instance_id"]
            print(
                f"[{self.INSTANCE_ID}] {from_persona} -> {to_persona} "
                f"(capability='{to_capability}' resolve 결과)",
                flush=True,
            )
        else:
            print(
                f"[{self.INSTANCE_ID}] {from_persona} -> {to_persona} "
                f"(to_persona 직접 지정)",
                flush=True,
            )

        # context_summary를 message에 주입한다
        forwarded = dict(inner_payload)
        if context_summary:
            existing_msg = forwarded.get("message", "")
            if existing_msg:
                forwarded["message"] = (
                    f"{existing_msg}\n\n[위임 컨텍스트] {context_summary}"
                )
            else:
                forwarded["context_summary"] = context_summary

        # agora.bot_emit(target=to_persona)으로 직접 전달.
        # Task 1에서 추가된 target 파라미터를 사용한다.
        # in_reply_to 없이 target만 지정 — 발신자 회신이 아닌 직접 push.
        await self.emit(forwarded, target=to_persona)
        return None  # 직접 emit했으므로 자동 회신 없음

    async def _call_find(self, query: str) -> dict:
        """agora.find를 호출해 워커를 검색한다."""
        result = await self.session.call_tool("agora.find", {"query": query})
        return _result_json(result)


if __name__ == "__main__":
    asyncio.run(RoutingBot.main())
