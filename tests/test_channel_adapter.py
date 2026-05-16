"""agora-channel 어댑터 단위 테스트."""
from __future__ import annotations

import pytest

from agent_agora.channel_adapter import parse_args, format_channel_notification


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
    assert "3건" in content
    assert "PM, Coder1" in content
    assert "agora.wait" in content
    assert meta == {"instance_id": "InstA", "pending": "3", "sources": "PM,Coder1"}


def test_format_channel_notification_no_sources():
    content, meta = format_channel_notification("InstA", 1, [])
    assert "(unknown)" in content
    assert meta["sources"] == ""
    assert meta["pending"] == "1"
