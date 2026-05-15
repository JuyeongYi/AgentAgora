"""Unit tests for plugin/cc-agora/scripts/payload.py (spec §5.3 + §8.8.1)."""
from __future__ import annotations

from datetime import datetime

import pytest

from payload import make_payload


def test_task_requires_message() -> None:
    with pytest.raises(ValueError, match="requires 'message'"):
        make_payload("task", "Coder1")


def test_reply_includes_message() -> None:
    p = make_payload("reply", "Coder1", message="done")
    assert p["type"] == "reply"
    assert p["from"] == "Coder1"
    assert p["message"] == "done"
    assert "reason" not in p
    assert "ack_for" not in p


def test_task_includes_message_and_rejects_extras() -> None:
    p = make_payload("task", "Orch1", message="do this")
    assert p == {**p, "type": "task", "from": "Orch1", "message": "do this"}
    with pytest.raises(ValueError, match="rejects 'reason'/'ack_for'"):
        make_payload("task", "Orch1", message="do this", reason="why")


def test_closing_rejects_message() -> None:
    with pytest.raises(ValueError, match="rejects 'message'"):
        make_payload("closing", "Orch1", message="x")


def test_closing_with_reason() -> None:
    p = make_payload("closing", "Orch1", reason="completed")
    assert p["type"] == "closing"
    assert p["from"] == "Orch1"
    assert p["reason"] == "completed"
    assert "message" not in p
    assert "ack_for" not in p


def test_closing_without_reason_omits_field() -> None:
    p = make_payload("closing", "Orch1")
    assert p["type"] == "closing"
    assert "reason" not in p


def test_ack_requires_ack_for() -> None:
    with pytest.raises(ValueError, match="requires 'ack_for'"):
        make_payload("ack", "Coder1")


def test_ack_rejects_message_reason() -> None:
    with pytest.raises(ValueError, match="rejects 'message'/'reason'"):
        make_payload("ack", "Coder1", ack_for="cmd_123", message="x")
    with pytest.raises(ValueError, match="rejects 'message'/'reason'"):
        make_payload("ack", "Coder1", ack_for="cmd_123", reason="y")


def test_ack_builds_correctly() -> None:
    p = make_payload("ack", "Coder1", ack_for="cmd_123")
    assert p == {**p, "type": "ack", "from": "Coder1", "ack_for": "cmd_123"}


def test_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown payload type"):
        make_payload("invalid", "Coder1")  # type: ignore[arg-type]


def test_ts_default_iso_utc() -> None:
    p = make_payload("reply", "Coder1", message="ok")
    ts = p["ts"]
    assert isinstance(ts, str)
    # Must round-trip through fromisoformat AND carry an explicit UTC offset.
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0.0
    # Default ISO formatting from datetime.isoformat() ends with "+00:00".
    assert ts.endswith("+00:00")


def test_ts_explicit_passthrough() -> None:
    custom = "2026-05-15T12:00:00+00:00"
    p = make_payload("reply", "Coder1", message="ok", ts=custom)
    assert p["ts"] == custom


def test_from_required() -> None:
    with pytest.raises(ValueError, match="'from_' is required"):
        make_payload("reply", "", message="ok")
