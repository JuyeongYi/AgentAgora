import pytest
from agent_agora.registry import BotInfo, BotRegistry
from agent_agora.registry import NotRegisteredError


def test_register_handler_bot_and_resolve():
    br = BotRegistry()
    info = br.register(
        session_id="sess-b1", instance_id="bot_pytest",
        description="run pytest", bot_mode="handler",
        subscribe_schemas=["pytest_run"], emit_schemas=["bot_reply"])
    assert isinstance(info, BotInfo)
    assert info.subscribe_schemas == ("pytest_run",)
    assert info.emit_schemas == ("bot_reply",)
    assert br.resolve_session("sess-b1").instance_id == "bot_pytest"
    assert br.resolve_instance_id("bot_pytest").bot_mode == "handler"


def test_subscribers_of_reverse_index():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["pytest_run"])
    br.register(session_id="s2", instance_id="bot_b", description="d",
                bot_mode="handler", subscribe_schemas=["pytest_run", "metric_log"])
    assert br.subscribers_of("pytest_run") == {"bot_a", "bot_b"}
    assert br.subscribers_of("metric_log") == {"bot_b"}
    assert br.subscribers_of("nope") == set()


def test_observer_bot_not_in_subscriber_index():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_obs", description="d", bot_mode="observer")
    assert br.observers() == {"bot_obs"}
    assert br.subscribers_of("anything") == set()


def test_unregister_removes_from_indexes():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["pytest_run"])
    br.unregister_session("s1")
    assert br.subscribers_of("pytest_run") == set()
    with pytest.raises(NotRegisteredError):
        br.resolve_instance_id("bot_a")


def test_reregister_same_instance_replaces_old_subscriptions():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["old_schema"])
    br.register(session_id="s2", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["new_schema"])
    assert br.subscribers_of("old_schema") == set()
    assert br.subscribers_of("new_schema") == {"bot_a"}
    assert br.resolve_instance_id("bot_a").session_id == "s2"


def test_list_bots_and_is_bot():
    br = BotRegistry()
    br.register(session_id="s1", instance_id="bot_a", description="d",
                bot_mode="handler", subscribe_schemas=["x"])
    assert [b.instance_id for b in br.list_bots()] == ["bot_a"]
    assert br.is_bot("bot_a") is True
    assert br.is_bot("worker_x") is False


def test_resolve_session_unknown_raises():
    br = BotRegistry()
    with pytest.raises(NotRegisteredError):
        br.resolve_session("nope")
