"""라우팅 봇 단위 테스트 — FakeSession으로 서버 없이 handle() 로직 검증.

test_v4_bot_sdk.py 패턴을 그대로 따른다:
- FakeSession / _FakeResult 재사용
- bot._session을 직접 주입해 handle() + _dispatch()만 테스트
"""
from __future__ import annotations

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
    """호출을 기록하고, responses로 도구별 반환값을 지정한다."""

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

    def find_calls(self) -> list[dict]:
        return [a for n, a in self.calls if n == "agora.find"]


# ── RoutingBot import ─────────────────────────────────────────────────────────

try:
    from routing_bot import RoutingBot  # conftest.py가 sys.path 설정
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False
    RoutingBot = None  # type: ignore[assignment,misc]


pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="routing_bot.py 아직 없음 — Task 4에서 구현 후 통과 예정",
)


# ── 픽스처: agora.find 응답 빌더 ────────────────────────────────────────────

def _find_response(instance_id: str, role: str = "planner") -> dict:
    return {
        "results": [
            {"kind": "worker", "instance_id": instance_id,
             "role": role, "description": f"{role} 워커"}
        ]
    }


# ── 테스트 1: to_persona 직접 지정 → target으로 bot_emit ─────────────────────

@pytest.mark.asyncio
async def test_handle_to_persona_uses_target_emit():
    """to_persona가 있으면 agora.find 없이 곧바로 해당 instance_id를 target으로 bot_emit.

    Task 1에서 추가된 target 파라미터로 직접 전달 — 2-hop 우회 없이 한 번에.
    """
    bot = RoutingBot()
    bot._session = FakeSession()

    cmd = {
        "id": "cmd-1",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            "to_persona": "superpowers-implementer-001",
            "payload": {"msgtype": "worker_freeform", "type": "task",
                        "from": "superpowers-planner-001",
                        "ts": "2026-05-18T00:00:00Z",
                        "message": "플랜 실행을 시작하세요."},
            "context_summary": "플랜 작성 완료",
        },
    }
    await bot._dispatch(cmd)

    emits = bot._session.emit_calls()
    assert len(emits) == 1, "bot_emit이 정확히 1회 호출돼야 한다"
    # target이 to_persona여야 한다
    assert emits[0].get("target") == "superpowers-implementer-001", (
        "target이 agora.bot_emit에 전달돼야 한다")
    # in_reply_to는 없어야 한다 (target 직접 지정 경로)
    assert emits[0].get("in_reply_to") is None
    # 전달 payload는 delegation_request.payload여야 한다
    assert emits[0]["payload"]["msgtype"] == "worker_freeform"
    assert emits[0]["payload"]["message"].startswith("플랜 실행을 시작하세요.")
    # agora.find는 호출되지 않아야 한다
    assert bot._session.find_calls() == []


# ── 테스트 2: to_capability로 agora.find → 결과 target으로 bot_emit ──────────

@pytest.mark.asyncio
async def test_handle_to_capability_uses_agora_find_then_target_emit():
    """to_persona 없고 to_capability 있으면 agora.find로 대상 워커를 조회하고
    찾은 instance_id를 target으로 bot_emit한다."""
    bot = RoutingBot()
    bot._session = FakeSession(responses={
        "agora.find": _find_response("superpowers-implementer-001", role="implementer"),
    })

    cmd = {
        "id": "cmd-2",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            "to_capability": "implementer",
            "payload": {"msgtype": "worker_freeform", "type": "task",
                        "from": "superpowers-planner-001",
                        "ts": "2026-05-18T00:00:00Z",
                        "message": "구현을 시작하세요."},
            "context_summary": "플랜 작성 완료",
        },
    }
    await bot._dispatch(cmd)

    find_calls = bot._session.find_calls()
    assert len(find_calls) == 1, "agora.find가 1회 호출돼야 한다"
    assert find_calls[0]["query"] == "implementer"

    emits = bot._session.emit_calls()
    assert len(emits) == 1, "bot_emit이 정확히 1회 호출돼야 한다"
    assert emits[0].get("target") == "superpowers-implementer-001"
    assert emits[0].get("in_reply_to") is None


# ── 테스트 3: to_persona도 to_capability도 없으면 bot_error emit ─────────────

@pytest.mark.asyncio
async def test_handle_missing_target_emits_error():
    """to_persona, to_capability 둘 다 없으면 라우팅 불가 — 오류를 emit한다."""
    bot = RoutingBot()
    bot._session = FakeSession()

    cmd = {
        "id": "cmd-3",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            # to_persona, to_capability 둘 다 없음
            "payload": {"msgtype": "worker_freeform", "type": "task",
                        "from": "superpowers-planner-001",
                        "ts": "2026-05-18T00:00:00Z",
                        "message": "..."},
        },
    }
    await bot._dispatch(cmd)

    # handle()이 ValueError를 raise → _dispatch가 bot_error를 emit
    emits = bot._session.emit_calls()
    assert len(emits) == 1
    assert emits[0]["payload"]["msgtype"] == "bot_error"
    assert ("to_persona" in emits[0]["payload"]["error_message"] or
            "to_capability" in emits[0]["payload"]["error_message"])


# ── 테스트 4: agora.find 결과 없으면 bot_error emit ──────────────────────────

@pytest.mark.asyncio
async def test_handle_no_find_result_emits_error():
    """agora.find가 빈 결과를 반환하면 라우팅 불가 오류를 emit한다."""
    bot = RoutingBot()
    bot._session = FakeSession(responses={
        "agora.find": {"results": []},
    })

    cmd = {
        "id": "cmd-4",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            "to_capability": "nonexistent-role",
            "payload": {"msgtype": "worker_freeform", "type": "task",
                        "from": "superpowers-planner-001",
                        "ts": "2026-05-18T00:00:00Z",
                        "message": "..."},
        },
    }
    await bot._dispatch(cmd)

    emits = bot._session.emit_calls()
    assert len(emits) == 1
    assert emits[0]["payload"]["msgtype"] == "bot_error"
    assert "nonexistent-role" in emits[0]["payload"]["error_message"]


# ── 테스트 5: context_summary가 있으면 payload에 포함 ────────────────────────

@pytest.mark.asyncio
async def test_handle_context_summary_appended_to_payload():
    """context_summary가 있으면 전달하는 payload의 message에 요약이 추가된다."""
    bot = RoutingBot()
    bot._session = FakeSession()

    cmd = {
        "id": "cmd-5",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            "to_persona": "superpowers-implementer-001",
            "payload": {"msgtype": "worker_freeform", "type": "task",
                        "from": "superpowers-planner-001",
                        "ts": "2026-05-18T00:00:00Z",
                        "message": "구현을 시작하세요."},
            "context_summary": "플랜: 3단계 TDD 사이클",
        },
    }
    await bot._dispatch(cmd)

    emits = bot._session.emit_calls()
    assert len(emits) == 1
    forwarded = emits[0]["payload"]
    # context_summary가 message에 포함되거나 별도 필드로 전달돼야 한다
    msg_text = forwarded.get("message", "")
    assert ("플랜: 3단계 TDD 사이클" in msg_text or
            forwarded.get("context_summary") == "플랜: 3단계 TDD 사이클")


# ── 테스트 6: worker_freeform인데 message 필드 없으면 bot_error emit ──────────

@pytest.mark.asyncio
async def test_handle_worker_freeform_missing_message_emits_error():
    """delegation_request.payload가 worker_freeform이지만 message 필드가 없으면
    포워딩하지 않고 bot_error를 emit해야 한다 (조기 검증).

    현재 구현은 검증 없이 바로 포워딩해서 다운스트림에서 실패하므로 이 테스트는
    구현 추가 전까지 실패한다.
    """
    bot = RoutingBot()
    bot._session = FakeSession()

    cmd = {
        "id": "cmd-6",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            "to_persona": "superpowers-implementer-001",
            # worker_freeform에 필수 필드 message가 없음
            "payload": {"msgtype": "worker_freeform", "type": "task",
                        "from": "superpowers-planner-001",
                        "ts": "2026-05-18T00:00:00Z"},
            "context_summary": "컨텍스트",
        },
    }
    await bot._dispatch(cmd)

    emits = bot._session.emit_calls()
    assert len(emits) == 1, "bot_emit이 정확히 1회 호출돼야 한다"
    assert emits[0]["payload"]["msgtype"] == "bot_error", (
        "malformed payload를 포워딩하지 않고 bot_error를 emit해야 한다"
    )
    assert "message" in emits[0]["payload"]["error_message"], (
        "오류 메시지에 누락된 필드명 'message'가 포함돼야 한다"
    )


# ── 테스트 7: inner payload가 빈 dict이면 bot_error emit ─────────────────────

@pytest.mark.asyncio
async def test_handle_empty_inner_payload_emits_error():
    """delegation_request.payload가 빈 dict이면 (msgtype 없음)
    포워딩하지 않고 bot_error를 emit해야 한다."""
    bot = RoutingBot()
    bot._session = FakeSession()

    cmd = {
        "id": "cmd-7",
        "source": "superpowers-planner-001",
        "payload": {
            "msgtype": "delegation_request",
            "from_persona": "superpowers-planner-001",
            "to_persona": "superpowers-implementer-001",
            "payload": {},  # 빈 dict — msgtype도 없음
            "context_summary": "컨텍스트",
        },
    }
    await bot._dispatch(cmd)

    emits = bot._session.emit_calls()
    assert len(emits) == 1
    assert emits[0]["payload"]["msgtype"] == "bot_error", (
        "빈 inner payload는 bot_error를 emit해야 한다"
    )
