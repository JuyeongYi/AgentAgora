import pytest
from agent_agora.envelope import (
    Envelope, _PRIORITY_RANK, validate_payload_size, validate_priority, make_envelope,
)


def test_priority_rank_mapping_high_zero_normal_one_low_two():
    assert _PRIORITY_RANK == {"high": 0, "normal": 1, "low": 2}


def test_priority_string_orders_high_before_normal_before_low_via_rank():
    items = [("low", 2), ("high", 0), ("normal", 1)]
    items.sort(key=lambda kv: kv[1])
    assert [k for k, _ in items] == ["high", "normal", "low"]


def test_validate_payload_size_accepts_under_1mb():
    payload = {"x": "a" * 100}
    payload_bytes = validate_payload_size(payload)
    assert isinstance(payload_bytes, bytes)
    assert len(payload_bytes) < 1_048_576


def test_validate_payload_size_rejects_over_1mb():
    big = {"x": "a" * 2_000_000}
    with pytest.raises(ValueError, match="payload_too_large"):
        validate_payload_size(big)


def test_validate_priority_returns_rank():
    assert validate_priority("high") == 0
    assert validate_priority("normal") == 1
    assert validate_priority("low") == 2


def test_validate_priority_rejects_unknown():
    with pytest.raises(ValueError, match="invalid_priority"):
        validate_priority("urgent")


def test_make_envelope_primary_default():
    env = make_envelope(
        cmd_id="c1", source="Inst1", target="Inst2", payload={"m": 1},
        created_at="2026-05-14T00:00:00+00:00",
        conversation_id="conv-1",
    )
    assert env.delivered_as == "primary"
    assert env.dispatch_kind == "direct"
    assert env.priority == "normal"
    assert env.closing is False


def test_make_envelope_cc_marker():
    env = make_envelope(
        cmd_id="c1", source="Inst1", target="Inst3", payload={"m": 1},
        created_at="2026-05-14T00:00:00+00:00",
        conversation_id="conv-1",
        delivered_as="cc",
        cc=["Inst3", "Inst4"],
    )
    assert env.delivered_as == "cc"
    assert env.cc == ["Inst3", "Inst4"]
