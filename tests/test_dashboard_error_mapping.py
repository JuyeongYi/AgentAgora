"""Unit tests for dashboard_routes error/parse helpers (narrowing + dedup).

These map broker/dispatch exceptions to HTTP responses without leaking internal
text, and centralise the JSON-parse / msgtype-injection boilerplate.
"""
import json

from agent_agora.dashboard_routes import _error_to_response, _inject_msgtype
from agent_agora.dispatcher import DispatcherClosed
from agent_agora.errors import AgoraError
from agent_agora.registry import NotRegisteredError


def _status_body(resp):
    return resp.status_code, json.loads(resp.body)


def test_inject_msgtype_adds_when_absent():
    assert _inject_msgtype({"a": 1}, "sch") == {"a": 1, "msgtype": "sch"}


def test_inject_msgtype_preserves_existing():
    assert _inject_msgtype({"msgtype": "x"}, "sch") == {"msgtype": "x"}


def test_inject_msgtype_passes_non_dict_through():
    assert _inject_msgtype("nope", "sch") == "nope"


def test_error_to_response_agora_error_is_422_with_code():
    s, b = _status_body(_error_to_response(AgoraError("comm_denied", from_="a", to="b")))
    assert s == 422
    assert b["code"] == "comm_denied"
    assert "error" in b


def test_error_to_response_not_registered_is_404():
    s, _ = _status_body(_error_to_response(NotRegisteredError("nope")))
    assert s == 404


def test_error_to_response_dispatcher_closed_is_503():
    s, _ = _status_body(_error_to_response(DispatcherClosed("closed")))
    assert s == 503


def test_error_to_response_plain_value_error_is_422():
    s, _ = _status_body(_error_to_response(ValueError("bad input")))
    assert s == 422


def test_error_to_response_unknown_is_500_without_leaking_internals():
    s, b = _status_body(_error_to_response(RuntimeError("secret internal detail")))
    assert s == 500
    assert "secret internal detail" not in b["error"]  # internal text must not leak
