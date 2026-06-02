"""SchemaRegistry reference-counting (schema lifecycle spec)."""
from __future__ import annotations

import pytest

from agent_agora.errors import AgoraError
from agent_agora.storage.schemas import SchemaRegistry, SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY

_BODY = {"type": "object", "properties": {"msgtype": {"const": "s"}}}
_BODY2 = {"type": "object", "properties": {"msgtype": {"const": "s"}, "x": {"type": "string"}}}


def _reg(r: SchemaRegistry, name="s", body=None, holder=None):
    return r.register(name, body or _BODY, kind="bot-task", purpose="p",
                      registered_by=holder)


def test_register_with_holder_creates_refset():
    r = SchemaRegistry()
    _reg(r, holder="A")
    assert r.get("s") is not None
    assert r.refs_of("s") == {"A"}


def test_second_same_body_register_adds_holder():
    r = SchemaRegistry()
    _reg(r, holder="A")
    _reg(r, holder="B")
    assert r.refs_of("s") == {"A", "B"}


def test_acquire_ref_adds_subscriber():
    r = SchemaRegistry()
    _reg(r, holder="A")
    r.acquire_ref("s", "C")
    assert r.refs_of("s") == {"A", "C"}


def test_release_holder_keeps_schema_while_refs_remain():
    r = SchemaRegistry()
    _reg(r, holder="A")
    r.acquire_ref("s", "B")
    assert r.release_holder("A") == []
    assert r.get("s") is not None
    assert r.refs_of("s") == {"B"}


def test_release_last_holder_unregisters_schema():
    r = SchemaRegistry()
    _reg(r, holder="A")
    released = r.release_holder("A")
    assert released == ["s"]
    assert r.get("s") is None
    assert r.validator("s") is None


def test_holder_none_is_permanent_and_never_released():
    r = SchemaRegistry()
    _reg(r, holder=None)  # builtin-style
    assert r.release_holder("anything") == []
    assert r.get("s") is not None
    # acquire_ref / register on a permanent schema is a no-op
    r.acquire_ref("s", "X")
    assert r.refs_of("s") == set()


def test_different_body_same_name_raises_immutable():
    r = SchemaRegistry()
    _reg(r, holder="A")
    with pytest.raises(AgoraError) as ei:
        _reg(r, body=_BODY2, holder="B")
    assert ei.value.code == "schema_immutable"
    assert r.get("s").body == _BODY


def test_release_holder_returns_only_emptied_schemas():
    r = SchemaRegistry()
    _reg(r, name="s1", holder="A")
    _reg(r, name="s2", holder="A")
    r.acquire_ref("s2", "B")
    released = r.release_holder("A")
    assert released == ["s1"]  # s2 still held by B
    assert r.get("s1") is None and r.get("s2") is not None


def test_schema_conflict_constant_has_msgtype_property():
    props = SCHEMA_CONFLICT_BODY.get("properties", {})
    assert "msgtype" in props
    assert SCHEMA_CONFLICT_NAME == "schema_conflict"


def test_schema_conflict_registers_as_permanent():
    r = SchemaRegistry()
    r.register(SCHEMA_CONFLICT_NAME, SCHEMA_CONFLICT_BODY,
               kind="conversation", purpose="schema name conflict notice")
    assert r.get(SCHEMA_CONFLICT_NAME) is not None
    assert r.release_holder("anyone") == []  # permanent
