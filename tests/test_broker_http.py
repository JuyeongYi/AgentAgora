"""Unit tests for the shared broker HTTP-client glue (_broker_http).

This module is extracted from the duplicated logic in channel_adapter.py and
bot.py. The HTTP long-poll path (http_wait_notify) is additionally covered
transitively by test_channel_adapter.py's _make_http_wait_notify tests.
"""
import pytest


def test_channel_wait_base_url_strips_mcp_suffix():
    from agent_agora._broker_http import channel_wait_base_url
    assert channel_wait_base_url("http://127.0.0.1:8420/mcp") == "http://127.0.0.1:8420"
    assert channel_wait_base_url("http://h:9/mcp/") == "http://h:9"
    assert channel_wait_base_url("http://h:9") == "http://h:9"
    assert channel_wait_base_url("http://h:9/") == "http://h:9"


def test_channel_wait_url_appends_path():
    from agent_agora._broker_http import channel_wait_url
    assert channel_wait_url("http://127.0.0.1:8420/mcp") == "http://127.0.0.1:8420/channel/wait"
    assert channel_wait_url("http://h:9") == "http://h:9/channel/wait"


def test_result_to_json_extracts_first_json_object():
    from agent_agora._broker_http import result_to_json

    class _Item:
        def __init__(self, text):
            self.text = text

    class _Result:
        def __init__(self, content):
            self.content = content

    assert result_to_json(_Result([_Item("not json"), _Item('{"a": 1}')])) == {"a": 1}
    assert result_to_json(_Result([_Item('[1,2,3]')])) == {}  # non-dict JSON ignored
    assert result_to_json(_Result([])) == {}
    assert result_to_json(_Result(None)) == {}  # defensive: missing content
