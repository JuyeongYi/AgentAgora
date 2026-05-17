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
    """pending 0->N 전이에만 emit — N 유지 중에는 재발화하지 않는다."""
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
