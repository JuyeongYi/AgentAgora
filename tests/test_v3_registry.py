import pytest
from agent_agora.registry import InstanceRegistry


def test_register_with_wait_mode_persists():
    reg = InstanceRegistry()
    info = reg.register("sess-1", "Inst1", role="orchestrator", description="d", wait_mode="auto")
    assert info.wait_mode == "auto"
    assert info.last_seen_at is None
    assert info.accepting is True


def test_register_without_wait_mode_defaults_unknown():
    reg = InstanceRegistry()
    info = reg.register("sess-2", "Inst2", role="worker")
    assert info.wait_mode == "unknown"


def test_touch_last_seen_updates_iso_timestamp():
    reg = InstanceRegistry()
    reg.register("sess-3", "Inst3")
    reg.touch_last_seen("Inst3")
    info = reg.resolve_instance_id("Inst3")
    assert info.last_seen_at is not None
    assert "T" in info.last_seen_at


def test_set_accepting_false_toggles():
    reg = InstanceRegistry()
    reg.register("sess-4", "Inst4")
    reg.set_accepting("Inst4", False)
    info = reg.resolve_instance_id("Inst4")
    assert info.accepting is False
