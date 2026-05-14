from __future__ import annotations

import pytest

from agent_agora.registry import InstanceRegistry, NotRegisteredError


def test_register_and_resolve():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="orchestrator")
    info = reg.resolve_session("s1")
    assert info.instance_id == "A"
    assert info.role == "orchestrator"


def test_resolve_unknown_session_raises():
    reg = InstanceRegistry()
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("ghost")


def test_re_register_same_instance_id_overwrites():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r1")
    reg.register(session_id="s2", instance_id="A", role="r2")
    assert reg.resolve_session("s2").role == "r2"
    assert reg.resolve_instance_id("A").session_id == "s2"
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("s1")


def test_unregister_by_session():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r")
    reg.unregister_session("s1")
    with pytest.raises(NotRegisteredError):
        reg.resolve_session("s1")
    with pytest.raises(NotRegisteredError):
        reg.resolve_instance_id("A")


def test_list_returns_all_registered():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r1")
    reg.register(session_id="s2", instance_id="B", role="r2")
    listed = sorted(i.instance_id for i in reg.list_instances())
    assert listed == ["A", "B"]


def test_resolve_instance_id_returns_session():
    reg = InstanceRegistry()
    reg.register(session_id="s1", instance_id="A", role="r")
    assert reg.resolve_instance_id("A").session_id == "s1"
