"""agora.bot_emit target 파라미터 확장 단위 테스트.

FakeSession 패턴(test_v4_bot_sdk.py)을 그대로 따른다.
Dispatcher 레벨 통합 테스트는 test_v4_wait_notify.py 패턴을 따른다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agent_agora.bot import AgoraBot


# ── FakeSession 헬퍼 ─────────────────────────────────────────────────────────

class _FakeItem:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(self, payload: dict) -> None:
        self.content = [_FakeItem(json.dumps(payload, ensure_ascii=False))]


class FakeSession:
    def __init__(self, responses: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.responses = responses or {}

    async def initialize(self) -> None:
        pass

    async def call_tool(self, name: str, args: dict) -> _FakeResult:
        self.calls.append((name, args))
        return _FakeResult(self.responses.get(name, {"status": "ok"}))

    def emit_calls(self) -> list[dict]:
        return [a for n, a in self.calls if n == "agora.bot_emit"]


# ── 테스트용 봇 ──────────────────────────────────────────────────────────────

class _TargetEmitBot(AgoraBot):
    INSTANCE_ID = "t_target_emit"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        # 직접 target을 지정해 emit
        await self.emit(
            {"msgtype": "worker_freeform", "type": "task",
             "from": self.INSTANCE_ID, "ts": self.now(), "message": "hi"},
            target="worker-001",
        )
        return None


# ── 테스트 1: emit(target=...) → agora.bot_emit에 target이 전달된다 ──────────

@pytest.mark.asyncio
async def test_emit_with_target_passes_target_to_bot_emit():
    """AgoraBot.emit(target=X) → agora.bot_emit 호출 시 target=X가 포함돼야 한다."""
    bot = _TargetEmitBot()
    bot._session = FakeSession()

    await bot._dispatch({"id": "cmd-1", "source": "worker-000", "payload": {"x": 1}})

    emits = bot._session.emit_calls()
    assert len(emits) == 1, "bot_emit이 1회 호출돼야 한다"
    assert emits[0].get("target") == "worker-001", (
        "target이 agora.bot_emit 인자로 전달돼야 한다")
    # in_reply_to는 None이어야 한다 (target 지정 시 명시적 대상이므로 reply 불필요)
    assert emits[0].get("in_reply_to") is None


# ── 테스트 2: emit(target=None) → 기존 동작 유지 (in_reply_to 경로) ─────────

class _NoTargetBot(AgoraBot):
    INSTANCE_ID = "t_no_target"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        await self.emit(
            {"msgtype": "bot_reply", "from": self.INSTANCE_ID,
             "ts": self.now(), "result": "ok"},
        )
        return None


@pytest.mark.asyncio
async def test_emit_without_target_uses_in_reply_to():
    """AgoraBot.emit(target 미지정) → agora.bot_emit에 in_reply_to가 전달된다."""
    bot = _NoTargetBot()
    bot._session = FakeSession()

    await bot._dispatch({"id": "cmd-2", "source": "worker-000", "payload": {}})

    emits = bot._session.emit_calls()
    assert len(emits) == 1
    # target 없음 (또는 None)
    assert emits[0].get("target") is None
    # in_reply_to = 현재 cmd id
    assert emits[0].get("in_reply_to") == "cmd-2"
