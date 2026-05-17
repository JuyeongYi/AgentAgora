"""comm-matrix(워커↔워커 dispatch ACL) 데모.

한 프로세스에서 워커 두 개(worker_a, worker_b)를 각각 별도 MCP 세션으로 띄운 뒤,
dispatch가 ACL대로 막히는지/통과하는지 보여준다.

comm-matrix는 서버 기동 시 `.agentagora/comm-matrix.csv`에서 읽어 들인다.
`run-demo.bat`이 임시 데이터 디렉터리에 CSV를 심고 서버를 기동한 뒤 이 스크립트를
실행한다.

적용되는 매트릭스(comm-matrix.csv):
    worker_a,worker_b
    0,1            <- to=worker_a : worker_b 에게서만 수신 허용
    0,0            <- to=worker_b : 아무에게도 수신 불허

따라서 worker_a -> worker_b 는 거부(comm_denied), worker_b -> worker_a 는 허용.

사전 조건: comm-matrix.csv가 심어진 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
    run-demo.bat 이 서버 기동까지 자동으로 처리한다.
    수동으로 띄우려면:
        mkdir mydir\\.agentagora
        copy examples\\comm_demo\\comm-matrix.csv mydir\\.agentagora\\comm-matrix.csv
        python -m agent_agora --dir mydir --port 8420 --no-tls --no-timeout
"""
from __future__ import annotations

import asyncio
import datetime
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


def _freeform(sender: str, message: str) -> dict:
    """worker_freeform 스키마(서버 기본 제공)에 맞는 payload."""
    return {
        "msgtype": "worker_freeform",
        "type": "task",
        "from": sender,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "message": message,
    }


async def main() -> bool:
    """ACL이 기대대로 동작하면 True를 반환한다."""
    async with (
        streamable_http_client(AGORA_URL) as ca,
        streamable_http_client(AGORA_URL) as cb,
    ):
        async with (
            ClientSession(ca[0], ca[1]) as sa,
            ClientSession(cb[0], cb[1]) as sb,
        ):
            await sa.initialize()
            await sb.initialize()
            await sa.call_tool("agora.register", {"instance_id": "worker_a", "role": "worker"})
            await sb.call_tool("agora.register", {"instance_id": "worker_b", "role": "worker"})

            # 1) worker_a -> worker_b : 매트릭스상 거부되어야 한다.
            r1 = _result_json(await sa.call_tool(
                "agora.dispatch",
                {"target": "worker_b", "payload": _freeform("worker_a", "a가 b에게")},
            ))
            ok1 = "error" in r1 and "comm_denied" in r1["error"]
            print(f"\n[a -> b] {'거부됨 (기대대로)' if ok1 else '예상과 다름'} : {r1}", flush=True)

            # 2) worker_b -> worker_a : 매트릭스상 허용되어야 한다.
            r2 = _result_json(await sb.call_tool(
                "agora.dispatch",
                {"target": "worker_a", "payload": _freeform("worker_b", "b가 a에게")},
            ))
            ok2 = r2.get("status") == "ok"
            print(f"[b -> a] {'허용됨 (기대대로)' if ok2 else '예상과 다름'} : {r2}", flush=True)

            await sa.call_tool("agora.unregister", {})
            await sb.call_tool("agora.unregister", {})

            ok = ok1 and ok2
            print(f"\n=== {'PASS — ACL이 기대대로 동작' if ok else 'FAIL'} ===", flush=True)
            return ok


if __name__ == "__main__":
    # sys.exit는 async with(anyio TaskGroup) 바깥에서 — 안에서 부르면 예외로 감싸진다.
    sys.exit(0 if asyncio.run(main()) else 1)
