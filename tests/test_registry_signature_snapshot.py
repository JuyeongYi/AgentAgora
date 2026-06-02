"""Public-API signature snapshot for InstanceRegistry / BotRegistry.

Plan E unifies both behind a shared _BidirectionalRegistry base. Pyright is
unreliable in this repo (memory), so this import-time signature snapshot is the
safety net guaranteeing the unification preserves the public surface — method
names + parameter names + defaults. A signature drift fails loudly here.
"""
import inspect

from agent_agora.registry import BotRegistry
from agent_agora.registry import InstanceRegistry


def _params(cls, name):
    return list(inspect.signature(getattr(cls, name)).parameters)


def test_instance_registry_public_signatures():
    assert _params(InstanceRegistry, "register") == [
        "self", "session_id", "instance_id", "role", "description", "cwd", "wait_mode"]
    assert _params(InstanceRegistry, "unregister_session") == ["self", "session_id"]
    assert _params(InstanceRegistry, "resolve_session") == ["self", "session_id"]
    assert _params(InstanceRegistry, "resolve_instance_id") == ["self", "instance_id"]
    assert _params(InstanceRegistry, "list_instances") == ["self"]
    assert _params(InstanceRegistry, "touch_last_seen") == ["self", "instance_id"]
    assert _params(InstanceRegistry, "set_accepting") == ["self", "instance_id", "accepting"]


def test_instance_registry_register_defaults():
    params = inspect.signature(InstanceRegistry.register).parameters
    assert params["role"].default == "worker"
    assert params["description"].default == ""
    assert params["cwd"].default == ""
    assert params["wait_mode"].default is None


def test_bot_registry_public_signatures():
    assert _params(BotRegistry, "register") == [
        "self", "session_id", "instance_id", "description", "bot_mode",
        "subscribe_schemas", "emit_schemas"]
    assert _params(BotRegistry, "unregister_session") == ["self", "session_id"]
    assert _params(BotRegistry, "resolve_session") == ["self", "session_id"]
    assert _params(BotRegistry, "resolve_instance_id") == ["self", "instance_id"]
    assert _params(BotRegistry, "is_bot") == ["self", "instance_id"]
    assert _params(BotRegistry, "subscribers_of") == ["self", "schema_name"]
    assert _params(BotRegistry, "observers") == ["self"]
    assert _params(BotRegistry, "list_bots") == ["self"]
    assert _params(BotRegistry, "touch_last_seen") == ["self", "instance_id"]


def test_bot_registry_register_defaults():
    params = inspect.signature(BotRegistry.register).parameters
    assert params["subscribe_schemas"].default == ()
    assert params["emit_schemas"].default == ()
