"""AgoraBot SDK 단위 테스트 — 가짜 MCP 세션으로 transport 없이 검증."""
from __future__ import annotations

import json

import pytest

from agent_agora.bot import AgoraBot, BotRegistrationError, SchemaConflictError


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


# ── run() — bounded wait heartbeat ──────────────────────────────────────────

class _StopLoop(Exception):
    pass


@pytest.mark.asyncio
async def test_run_uses_bounded_wait_timeout():
    """run()의 wait 루프는 WAIT_TIMEOUT_MS로 bounded 호출해야 한다 (무한 wait 금지)."""
    seen_timeouts: list = []

    class _WaitSession(FakeSession):
        async def call_tool(self, name, args):
            if name == "agora.wait":
                seen_timeouts.append(args.get("timeout_ms"))
                if len(seen_timeouts) >= 2:
                    raise _StopLoop()  # 루프 탈출
                return _FakeResult({"commands": []})
            return await super().call_tool(name, args)

    bot = _ReturnBot()
    bot._session = _WaitSession()
    with pytest.raises(_StopLoop):
        await bot.run()
    assert seen_timeouts
    assert all(t == _ReturnBot.WAIT_TIMEOUT_MS for t in seen_timeouts)


# ── 스키마 이름 충돌 에러 명확화 ────────────────────────────────────────────

class _SchemaBot(AgoraBot):
    INSTANCE_ID = "t_schema"
    SUBSCRIBE_SCHEMAS = ["echo_task"]
    SCHEMAS = {
        "echo_task": {
            "kind": "bot-task", "purpose": "p",
            "body": {"type": "object",
                     "properties": {"msgtype": {"const": "echo_task"}}},
        },
    }

    async def handle(self, cmd):
        return None


def test_registration_error_schema_conflict_is_typed():
    bot = _SchemaBot()
    err = bot._registration_error(
        "[agora] schema 'echo_task'는 다른 body로 이미 등록됨.")
    assert isinstance(err, SchemaConflictError)
    assert "echo_task" in str(err)
    assert "immutable" in str(err)


def test_registration_error_other_failure_is_generic():
    bot = _SchemaBot()
    err = bot._registration_error("[agora] 봇 mode는 description이 필수입니다.")
    assert isinstance(err, BotRegistrationError)
    assert not isinstance(err, SchemaConflictError)


@pytest.mark.asyncio
async def test_aenter_raises_schema_conflict_on_immutable_error(monkeypatch):
    session = FakeSession(responses={
        "agora.register_bot": {
            "error": "[agora] schema 'echo_task'는 다른 body로 이미 등록됨."},
    })
    _patch_transport(monkeypatch, session)
    with pytest.raises(SchemaConflictError):
        async with _SchemaBot():
            pass


# ── 회신 계약 — 직접 emit + 반환값 동시: 직접 emit이 유효, 반환값 무시 ────────

class _EmitAndReturnBot(AgoraBot):
    INSTANCE_ID = "t_both"
    SUBSCRIBE_SCHEMAS = ["x"]

    async def handle(self, cmd):
        await self.emit({"echo": "direct"})
        return {"echo": "returned"}  # _emitted=True라 이 반환값은 무시된다


@pytest.mark.asyncio
async def test_direct_emit_suppresses_auto_reply_when_value_also_returned():
    bot = _EmitAndReturnBot()
    bot._session = FakeSession()
    await bot._dispatch({"id": "c1", "source": "w1", "payload": {}})
    emits = bot._session.emit_calls()
    assert len(emits) == 1                       # 직접 emit 1회만 — 자동회신 없음
    assert emits[0]["payload"]["result"] == {"echo": "direct"}
