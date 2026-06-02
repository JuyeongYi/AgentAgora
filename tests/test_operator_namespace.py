"""operator pseudo-instance namespace helpers — registry.operator_id /
strip_operator_prefix. Replaces scattered 'operator:' magic strings."""
from agent_agora.registry import (
    OPERATOR_PREFIX,
    is_operator,
    operator_id,
    strip_operator_prefix,
)


def test_operator_id_round_trips():
    assert operator_id("alice") == "operator:alice"
    assert strip_operator_prefix(operator_id("alice")) == "alice"
    assert is_operator(operator_id("alice"))


def test_strip_returns_none_for_non_operator():
    assert strip_operator_prefix("WorkerA") is None
    assert strip_operator_prefix("alice") is None


def test_bare_operator_prefix_is_not_an_operator():
    # 'operator:' with empty suffix is NOT a real operator — this guards the
    # dashboard_events behaviour (bare 'operator:' must not emit operator events).
    assert is_operator(OPERATOR_PREFIX) is False
    assert strip_operator_prefix(OPERATOR_PREFIX) is None
