"""agora-channel 어댑터 단위 테스트."""
from __future__ import annotations

import pytest

from agent_agora.channel_adapter import (
    parse_args, format_channel_notification, watch_loop)


def test_parse_args_requires_instance_id():
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_defaults():
    ns = parse_args(["--instance-id", "InstA"])
    assert ns.instance_id == "InstA"
    assert ns.broker == "http://127.0.0.1:8420/mcp"
    assert ns.wait_timeout_ms == 30000


def test_parse_args_overrides():
    ns = parse_args(["--instance-id", "InstA",
                     "--broker", "http://h:9/mcp", "--wait-timeout-ms", "5000"])
    assert ns.broker == "http://h:9/mcp"
    assert ns.wait_timeout_ms == 5000


def test_format_channel_notification():
    content, meta = format_channel_notification("InstA", 3, ["PM", "Coder1"])
    assert "PM, Coder1" in content
    assert "agora.flush" in content
    assert "drain everything currently queued" in content
    assert meta == {"instance_id": "InstA", "pending": "3", "sources": "PM,Coder1"}


def test_format_channel_notification_no_sources():
    content, meta = format_channel_notification("InstA", 1, [])
    assert "(unknown)" in content
    assert meta["sources"] == ""
    assert meta["pending"] == "1"


import asyncio


class _Stop(BaseException):
    """watch_loop 무한 루프를 테스트에서 탈출시키는 센티넬."""


@pytest.mark.asyncio
async def test_watch_loop_emits_once_per_rising_edge():
    """pending 0->N 전이에 emit — drain 폴링은 재발화를 누적하지 않는다(drain_poll_s=0)."""
    emits: list = []
    wait_calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        wait_calls[0] += 1
        if wait_calls[0] == 1:
            return {"instance_id": iid, "pending": 2, "sources": ["PM"]}
        raise _Stop()                       # 2번째 wait_notify → 루프 종료

    peek_seq = [2, 2, 0]                     # 워커가 세 번째 peek에 드레인
    async def fake_peek(iid):
        return peek_seq.pop(0)

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0)
    assert len(emits) == 1                   # rising edge 1회만
    assert emits[0][1]["pending"] == "2"


@pytest.mark.asyncio
async def test_watch_loop_skips_emit_on_timeout():
    """pending 0(timeout heartbeat)이면 emit하지 않는다."""
    emits: list = []
    calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        calls[0] += 1
        if calls[0] == 1:
            return {"instance_id": iid, "pending": 0, "sources": []}   # timeout heartbeat
        raise _Stop()

    async def fake_peek(iid):
        return 0

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0)
    assert emits == []


@pytest.mark.asyncio
async def test_watch_loop_refires_on_second_rising_edge():
    """드레인 감지 후 다음 rising edge에 다시 emit한다 — 두 번째 발화 확인."""
    emits: list = []
    wait_calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        wait_calls[0] += 1
        if wait_calls[0] <= 2:                       # 두 번의 rising edge
            return {"instance_id": iid, "pending": 1, "sources": ["PM"]}
        raise _Stop()                                # 3번째 wait_notify → 루프 종료

    # 두 번의 emit 각각 뒤에 워커가 드레인(peek 0)
    peek_seq = [1, 0, 1, 0]
    async def fake_peek(iid):
        return peek_seq.pop(0)

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0)
    assert len(emits) == 2                           # 두 rising edge → 두 emit


@pytest.mark.asyncio
async def test_watch_loop_backs_off_on_error_signal():
    """브로커 에러 신호({error:...})면 즉시 재시도하지 않고 backoff한다."""
    emits: list = []
    calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        calls[0] += 1
        if calls[0] == 1:
            return {"error": "broker tool failed"}    # 에러 신호
        raise _Stop()

    async def fake_peek(iid):
        return 0

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0)
    assert emits == []                               # 에러 신호엔 emit 안 함


@pytest.mark.asyncio
async def test_watch_loop_reemits_while_inbox_stays_pending():
    """워커가 드레인하지 않으면 reemit_interval_s마다 claude/channel을 재발화한다."""
    emits: list = []

    async def fake_wait_notify(iid, timeout_ms):
        return {"instance_id": iid, "pending": 1, "sources": ["PM"]}

    async def fake_peek(iid):
        return 1                                     # 워커가 영원히 드레인 안 함

    async def fake_emit(content, meta):
        emits.append((content, meta))
        if len(emits) >= 3:                          # 최초 1 + 재발화 2
            raise _Stop()

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0.01,
                         reemit_interval_s=0.015)
    assert len(emits) == 3


@pytest.mark.asyncio
async def test_watch_loop_no_reemit_if_drained_before_interval():
    """reemit_interval_s 전에 워커가 드레인하면 재발화하지 않는다."""
    emits: list = []
    wait_calls = [0]

    async def fake_wait_notify(iid, timeout_ms):
        wait_calls[0] += 1
        if wait_calls[0] == 1:
            return {"instance_id": iid, "pending": 1, "sources": ["PM"]}
        raise _Stop()                                # 2번째 wait_notify → 루프 종료

    peek_seq = [1, 1, 0]                             # interval 전에 드레인
    async def fake_peek(iid):
        return peek_seq.pop(0)

    async def fake_emit(content, meta):
        emits.append((content, meta))

    with pytest.raises(_Stop):
        await watch_loop("InstA", fake_wait_notify, fake_peek, fake_emit,
                         wait_timeout_ms=1000, drain_poll_s=0.01,
                         reemit_interval_s=0.1)
    assert len(emits) == 1                           # 최초 emit만 — 재발화 없음


def test_channel_wait_base_url_strips_mcp_suffix():
    from agent_agora.channel_adapter import _channel_wait_base_url
    assert _channel_wait_base_url("http://127.0.0.1:8420/mcp") == "http://127.0.0.1:8420"
    assert _channel_wait_base_url("http://h:9/mcp/") == "http://h:9"
    # no /mcp suffix → returned unchanged (minus any trailing slash)
    assert _channel_wait_base_url("http://h:9") == "http://h:9"
    assert _channel_wait_base_url("http://h:9/") == "http://h:9"


@pytest.mark.asyncio
async def test_http_wait_notify_calls_channel_wait_endpoint(monkeypatch):
    """HTTP wait_notify 콜러블이 GET /channel/wait를 올바른 파라미터로 호출한다."""
    from agent_agora.channel_adapter import _make_http_wait_notify

    seen = {}

    class _FakeResponse:
        def json(self):
            return {"instance_id": "InstA", "pending": 2, "sources": ["PM"]}

        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            seen["url"] = url
            seen["params"] = params
            return _FakeResponse()

    monkeypatch.setattr("agent_agora._broker_http.httpx.AsyncClient",
                        _FakeAsyncClient)
    wait_notify = _make_http_wait_notify("http://127.0.0.1:8420/mcp")
    result = await wait_notify("InstA", 5000)
    assert result == {"instance_id": "InstA", "pending": 2, "sources": ["PM"]}
    assert seen["url"] == "http://127.0.0.1:8420/channel/wait"
    assert seen["params"] == {"instance_id": "InstA", "timeout_ms": 5000}


@pytest.mark.asyncio
async def test_http_wait_notify_returns_error_dict_on_failure(monkeypatch):
    """HTTP 호출 실패 시 {error:...} dict를 반환한다 — watch_loop가 backoff한다."""
    from agent_agora.channel_adapter import _make_http_wait_notify

    class _BoomClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("agent_agora._broker_http.httpx.AsyncClient",
                        _BoomClient)
    wait_notify = _make_http_wait_notify("http://127.0.0.1:8420/mcp")
    result = await wait_notify("InstA", 5000)
    assert "error" in result


def test_cli_entrypoint_registered():
    """agora-channel 콘솔 스크립트가 pyproject에 등록되고 cli()가 동기 호출 가능하다."""
    import pathlib
    from agent_agora import channel_adapter

    assert callable(channel_adapter.cli)
    # cli는 동기 함수여야 한다 (콘솔 스크립트 엔트리는 코루틴을 못 받는다)
    import inspect
    assert not inspect.iscoroutinefunction(channel_adapter.cli)

    pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'agora-channel = "agent_agora.channel_adapter:cli"' in text


# ---------------------------------------------------------------------------
# lifespan cleanup: _unregister_from_broker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unregister_calls_agora_unregister(monkeypatch):
    """_unregister_from_broker가 브로커 MCP 세션으로 agora.unregister를 호출한다."""
    from agent_agora.channel_adapter import _unregister_from_broker

    calls: list[dict] = []

    class _FakeBrokerSession:
        async def initialize(self):
            pass

        async def call_tool(self, name: str, args: dict):
            calls.append({"name": name, "args": args})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    _read_obj = object()
    _write_obj = object()

    class _FakeConn:
        def __getitem__(self, idx):
            return (_read_obj, _write_obj)[idx]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    _conn = _FakeConn()
    _session = _FakeBrokerSession()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_http_client(url):
        yield _conn

    monkeypatch.setattr(
        "agent_agora.channel_adapter.streamable_http_client", _fake_http_client)
    monkeypatch.setattr(
        "agent_agora.channel_adapter.ClientSession",
        lambda *_: _session)

    await _unregister_from_broker("http://127.0.0.1:8420/mcp", "InstA")

    assert len(calls) == 1
    assert calls[0]["name"] == "agora.unregister"
    assert calls[0]["args"]["instance_id"] == "InstA"


@pytest.mark.asyncio
async def test_unregister_does_not_raise_on_broker_error(monkeypatch):
    """브로커 연결 실패 시 _unregister_from_broker가 예외를 전파하지 않는다."""
    from agent_agora.channel_adapter import _unregister_from_broker
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _boom(*_):
        raise RuntimeError("broker is down")
        yield  # noqa: unreachable — makes this an asynccontextmanager

    monkeypatch.setattr(
        "agent_agora.channel_adapter.streamable_http_client", _boom)

    # 예외가 전파되지 않아야 한다
    await _unregister_from_broker("http://127.0.0.1:8420/mcp", "InstA")


@pytest.mark.asyncio
async def test_unregister_timeout_does_not_hang(monkeypatch):
    """느린 브로커가 _unregister_from_broker를 무한 hang시키지 않는다 — timeout 발동."""
    import agent_agora.channel_adapter as ca

    async def _slow(broker, instance_id):
        await asyncio.sleep(10.0)                # timeout(5s)보다 훨씬 김

    # _do_unregister를 느린 버전으로 교체하고 timeout을 짧게 줄여 테스트 가속.
    monkeypatch.setattr(ca, "_do_unregister", _slow)
    monkeypatch.setattr(ca, "_UNREGISTER_TIMEOUT_S", 0.05)

    loop = asyncio.get_event_loop()
    start = loop.time()
    await ca._unregister_from_broker("http://x", "W1")     # 예외 없이 반환해야
    elapsed = loop.time() - start
    # timeout=0.05s + 여유. 10s sleep을 끝까지 기다리면 안 됨.
    assert elapsed < 1.0
