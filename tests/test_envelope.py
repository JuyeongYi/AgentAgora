"""Envelope 직렬화·검증 단위 테스트."""
from __future__ import annotations

from agent_agora.envelope import Envelope, make_envelope, envelope_from_dict, envelope_to_dict


def test_envelope_reply_only_default_false():
    env = make_envelope(
        cmd_id="m1", source="operator:alice", target="worker1",
        payload={"q": 1}, created_at="2026-05-21T00:00:00Z",
        conversation_id="c1",
    )
    assert env.reply_only is False


def test_envelope_reply_only_roundtrip():
    env = make_envelope(
        cmd_id="m1", source="operator:alice", target="worker1",
        payload={"q": 1}, created_at="2026-05-21T00:00:00Z",
        conversation_id="c1",
        reply_only=True,
    )
    data = envelope_to_dict(env)
    assert data["reply_only"] is True
    back = envelope_from_dict(data)
    assert back.reply_only is True


def test_envelope_from_dict_missing_reply_only_defaults_false():
    data = {
        "id": "m1", "source": "operator:alice", "target": "worker1",
        "payload": {"q": 1}, "created_at": "2026-05-21T00:00:00Z",
        "conversation_id": "c1",
        "expect_result": False, "reply_to": None, "cc": None,
        "delivered_as": "primary", "dispatch_kind": "direct",
        "in_reply_to": None, "closing": False, "priority": "normal",
        "deadline_ts": None, "wait_age_ms": 0,
        # reply_only 누락
    }
    env = envelope_from_dict(data)
    assert env.reply_only is False
