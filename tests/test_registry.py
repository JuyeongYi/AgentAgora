from __future__ import annotations

import pytest

from agent_agora.registry import InstanceRegistry, NotRegisteredError, is_operator


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


def test_register_stores_cwd():
    reg = InstanceRegistry()
    info = reg.register(session_id="s1", instance_id="w1", cwd="C:/Users/x/source/Dep/w1")
    assert info.cwd == "C:/Users/x/source/Dep/w1"
    assert reg.resolve_instance_id("w1").cwd == "C:/Users/x/source/Dep/w1"


def test_register_cwd_defaults_to_empty():
    reg = InstanceRegistry()
    reg.register(session_id="s2", instance_id="w2")
    assert reg.resolve_instance_id("w2").cwd == ""


def test_cwd_survives_replace_based_updates():
    reg = InstanceRegistry()
    reg.register(session_id="s3", instance_id="w3", cwd="C:/dep/w3")
    reg.touch_last_seen("w3")
    reg.set_accepting("w3", False)
    assert reg.resolve_instance_id("w3").cwd == "C:/dep/w3"


def test_register_operator_pseudo_instance():
    reg = InstanceRegistry()
    reg.register(
        session_id="dashboard:alice", instance_id="operator:alice",
        role="operator", description="Dashboard operator",
    )
    info = reg.resolve_instance_id("operator:alice")
    assert info.instance_id == "operator:alice"
    assert info.role == "operator"


def test_is_operator_helper():
    assert is_operator("operator:alice") is True
    assert is_operator("operator:") is False  # 접두사만 있고 username 없음
    assert is_operator("Worker1") is False
    assert is_operator("") is False
