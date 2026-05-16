"""AgoraBot SDK 단위 테스트 — 가짜 MCP 세션으로 transport 없이 검증."""
from __future__ import annotations

import json

import pytest

from agent_agora.bot import AgoraBot


class _FakeItem:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(self, payload: dict) -> None:
        self.content = [_FakeItem(json.dumps(payload, ensure_ascii=False))]


class FakeSession:
    """AgoraBot이 기대하는 ClientSession 표면(initialize·call_tool)만 흉내낸다.
    호출을 calls에 기록하고, responses로 도구별 반환 payload를 지정한다."""

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


class _FakeConn:
    """streamable_http_client가 yield하는 (read, write, ...) 튜플 대용 async CM."""
    async def __aenter__(self):
        return (None, None)

    async def __aexit__(self, *exc):
        return False


class _FakeClientSessionCM:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *exc):
        return False


def _patch_transport(monkeypatch, session: FakeSession) -> None:
    """AgoraBot.__aenter__의 streamable_http_client·ClientSession을 가짜로 교체."""
    monkeypatch.setattr("agent_agora.bot.streamable_http_client",
                        lambda url: _FakeConn())
    monkeypatch.setattr("agent_agora.bot.ClientSession",
                        lambda r, w: _FakeClientSessionCM(session))


# ── 회신 계약 ① — 반환값이 bot_reply로 자동 wrap ───────────────────────────

class _ReturnBot(AgoraBot):
    INSTANCE_ID = "t_return"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        return {"echo": cmd["payload"]["text"]}


@pytest.mark.asyncio
async def test_handle_return_value_emitted_as_bot_reply():
    bot = _ReturnBot()
    bot._session = FakeSession()
    await bot._dispatch({"id": "c1", "source": "w1", "payload": {"text": "hi"}})
    emits = bot._session.emit_calls()
    assert len(emits) == 1
    assert emits[0]["payload"]["msgtype"] == "bot_reply"
    assert emits[0]["payload"]["result"] == {"echo": "hi"}
    assert emits[0]["in_reply_to"] == "c1"


# ── 회신 계약 ③ — handle 안 직접 emit, 자동회신 없음 ────────────────────────

class _DirectEmitBot(AgoraBot):
    INSTANCE_ID = "t_direct"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        await self.emit({"echo": "1"})
        await self.emit({"echo": "2"})
        return None


@pytest.mark.asyncio
async def test_direct_emit_path_emits_each_call_and_no_auto_reply():
    bot = _DirectEmitBot()
    bot._session = FakeSession()
    await bot._dispatch({"id": "c1", "source": "w1", "payload": {}})
    assert len(bot._session.emit_calls()) == 2  # 직접 2회, 자동회신 없음


# ── handle이 None 반환 → 회신 없음 ──────────────────────────────────────────

class _SilentBot(AgoraBot):
    INSTANCE_ID = "t_silent"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        return None


@pytest.mark.asyncio
async def test_handle_returns_none_emits_nothing():
    bot = _SilentBot()
    bot._session = FakeSession()
    await bot._dispatch({"id": "c1", "source": "w1", "payload": {}})
    assert bot._session.emit_calls() == []


# ── handle 예외 → bot_error 자동 emit + 봇 생존 ─────────────────────────────

class _BrokenBot(AgoraBot):
    INSTANCE_ID = "t_broken"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        raise RuntimeError("처리 실패")


@pytest.mark.asyncio
async def test_handle_exception_emits_bot_error_and_survives():
    bot = _BrokenBot()
    bot._session = FakeSession()
    # 예외가 _dispatch 밖으로 새지 않는다 (봇 생존)
    await bot._dispatch({"id": "c1", "source": "w1", "payload": {}})
    emits = bot._session.emit_calls()
    assert len(emits) == 1
    assert emits[0]["payload"]["msgtype"] == "bot_error"
    assert emits[0]["payload"]["error_code"] == "RuntimeError"


# ── observer 자기루프 차단 ──────────────────────────────────────────────────

class _ObserverBot(AgoraBot):
    INSTANCE_ID = "t_obs"
    BOT_MODE = "observer"

    async def handle(self, cmd):
        raise AssertionError("observer는 자기 메시지를 handle하면 안 된다")


@pytest.mark.asyncio
async def test_observer_skips_own_message():
    bot = _ObserverBot()
    bot._session = FakeSession()
    # source가 자기 자신 → handle 호출 안 됨, 예외 안 남
    await bot._dispatch({"id": "c1", "source": "t_obs", "payload": {}})
    assert bot._session.emit_calls() == []


# ── 생명주기 — register/unregister 보장 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_lifecycle_registers_and_unregisters(monkeypatch):
    session = FakeSession(responses={
        "agora.register_bot": {"status": "ok", "subscribe_schemas": ["x"]},
    })
    _patch_transport(monkeypatch, session)
    async with _ReturnBot():
        pass
    names = [n for n, _ in session.calls]
    assert "agora.register_bot" in names
    assert "agora.unregister" in names


@pytest.mark.asyncio
async def test_lifecycle_unregisters_even_on_exception(monkeypatch):
    session = FakeSession(responses={
        "agora.register_bot": {"status": "ok", "subscribe_schemas": ["x"]},
    })
    _patch_transport(monkeypatch, session)
    with pytest.raises(RuntimeError, match="boom"):
        async with _ReturnBot():
            raise RuntimeError("boom")
    # 예외 종료에도 unregister는 세션이 닫히기 전에 실행된다
    assert "agora.unregister" in [n for n, _ in session.calls]
