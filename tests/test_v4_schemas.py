import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES


def test_agora_error_carries_code_and_korean_message():
    e = AgoraError("payload_missing_msgtype")
    assert e.code == "payload_missing_msgtype"
    assert str(e) == "[agora] payload에 msgtype이 없습니다. 모든 메시지는 msgtype이 필수입니다."


def test_agora_error_formats_detail():
    e = AgoraError("unknown_msgtype", msgtype="foo")
    assert str(e) == "[agora] msgtype 'foo'는 registry에 없습니다."


def test_plan1_schema_codes_present():
    expected = {
        "payload_missing_msgtype", "unknown_msgtype", "schema_violation",
        "schema_immutable", "schema_missing_msgtype",
    }
    assert expected <= set(ERROR_MESSAGES)
