import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES
from agent_agora.schemas import SchemaRegistry, SchemaEntry


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


_WF_BODY = {
    "type": "object",
    "required": ["msgtype", "message"],
    "properties": {
        "msgtype": {"type": "string", "const": "wf"},
        "message": {"type": "string"},
    },
    "additionalProperties": True,
}
_NO_MSGTYPE_BODY = {
    "type": "object",
    "required": ["x"],
    "properties": {"x": {"type": "string"}},
    "additionalProperties": False,
}


def test_register_returns_entry_with_kind_and_purpose():
    reg = SchemaRegistry()
    entry = reg.register("wf", _WF_BODY, kind="conversation", purpose="자유 통신")
    assert isinstance(entry, SchemaEntry)
    assert entry.name == "wf" and entry.kind == "conversation"
    assert entry.purpose == "자유 통신"
    assert reg.get("wf").body == _WF_BODY


def test_register_rejects_body_without_msgtype_property():
    reg = SchemaRegistry()
    with pytest.raises(AgoraError) as ei:
        reg.register("bad", _NO_MSGTYPE_BODY, kind="conversation", purpose="p")
    assert ei.value.code == "schema_missing_msgtype"


def test_register_same_body_is_idempotent():
    reg = SchemaRegistry()
    a = reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    b = reg.register("wf", dict(_WF_BODY), kind="conversation", purpose="p")
    assert a == b


def test_register_different_body_raises_schema_immutable():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    other = dict(_WF_BODY, required=["msgtype"])
    with pytest.raises(AgoraError) as ei:
        reg.register("wf", other, kind="conversation", purpose="p")
    assert ei.value.code == "schema_immutable"


def test_validator_validates_and_caches():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    v1 = reg.validator("wf")
    v2 = reg.validator("wf")
    assert v1 is v2  # cached, not recompiled
    assert list(v1.iter_errors({"msgtype": "wf", "message": "hi"})) == []
    assert list(v1.iter_errors({"msgtype": "wf"})) != []  # missing required


def test_get_and_validator_return_none_for_unknown():
    reg = SchemaRegistry()
    assert reg.get("nope") is None
    assert reg.validator("nope") is None


def test_register_isolates_body_from_caller_mutation():
    reg = SchemaRegistry()
    body = {"type": "object", "required": ["msgtype"],
            "properties": {"msgtype": {"type": "string"}}}
    reg.register("iso", body, kind="conversation", purpose="p")
    body["required"].append("injected")
    body["properties"]["extra"] = {"type": "string"}
    stored = reg.get("iso").body
    assert "injected" not in stored["required"]
    assert "extra" not in stored["properties"]


def test_register_rejects_malformed_schema_body():
    reg = SchemaRegistry()
    bad = {"type": "object", "properties": {"msgtype": {"type": "string"}},
           "required": "not-a-list"}  # required must be an array
    with pytest.raises(AgoraError) as ei:
        reg.register("bad_schema", bad, kind="conversation", purpose="p")
    assert ei.value.code == "schema_violation"


def test_list_meta_exposes_kind_and_purpose_no_body():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="자유 통신")
    meta = reg.list_meta()
    assert len(meta) == 1
    assert meta[0]["name"] == "wf"
    assert meta[0]["kind"] == "conversation"
    assert meta[0]["purpose"] == "자유 통신"
    assert "body" not in meta[0]


def test_list_all_returns_entries_with_body():
    reg = SchemaRegistry()
    reg.register("wf", _WF_BODY, kind="conversation", purpose="p")
    entries = reg.list_all()
    assert len(entries) == 1 and entries[0].body == _WF_BODY


from agent_agora.schemas import (
    parse_schema_lines, ensure_schemas_file, load_schemas_into,
    BUNDLED_DEFAULT_SCHEMAS,
)


def test_bundled_default_schemas_file_exists_and_has_eleven():
    assert BUNDLED_DEFAULT_SCHEMAS.is_file()
    lines = [l for l in BUNDLED_DEFAULT_SCHEMAS.read_text("utf-8").splitlines() if l.strip()]
    assert len(lines) == 11


def test_parse_schema_lines_yields_name_kind_purpose_body():
    parsed = parse_schema_lines(BUNDLED_DEFAULT_SCHEMAS.read_text("utf-8"))
    names = {p["name"] for p in parsed}
    assert names == {
        "default", "worker_freeform", "bot_reply", "bot_error",
        "closing", "ack", "schema_conflict", "file_share",
        "operator_message", "status_report", "agora.error",
    }
    for p in parsed:
        assert "properties" in p["body"] and "msgtype" in p["body"]["properties"]


def test_ensure_schemas_file_copies_bundle_when_absent(tmp_path):
    target = tmp_path / "schemas.jsonl"
    assert not target.exists()
    ensure_schemas_file(target)
    assert target.is_file()
    assert len([l for l in target.read_text("utf-8").splitlines() if l.strip()]) == 11


def test_ensure_schemas_file_keeps_existing(tmp_path):
    target = tmp_path / "schemas.jsonl"
    target.write_text("", encoding="utf-8")
    ensure_schemas_file(target)
    assert target.read_text("utf-8") == ""  # not overwritten


def test_load_schemas_into_registers_all_eleven():
    reg = SchemaRegistry()
    count = load_schemas_into(reg, BUNDLED_DEFAULT_SCHEMAS)
    assert count == 11
    assert reg.get("worker_freeform").kind == "conversation"
    assert reg.get("bot_reply").kind == "bot-task"
    assert reg.get("schema_conflict").kind == "conversation"
    assert reg.get("file_share").kind == "conversation"
    assert reg.get("operator_message").kind == "conversation"
    assert reg.get("status_report").kind == "conversation"


def test_plan2_bot_codes_present():
    expected = {
        "no_route", "unhandled_schema", "bot_emit_not_a_bot",
        "description_required", "subscribe_required",
        "cannot_subscribe_conversation", "schema_kind_not_bot_task",
    }
    assert expected <= set(ERROR_MESSAGES)


def test_no_route_message_formats_msgtype():
    e = AgoraError("no_route", msgtype="pytest_run")
    assert e.code == "no_route"
    assert "pytest_run" in str(e)


def test_unhandled_schema_message_formats_bot_and_msgtype():
    e = AgoraError("unhandled_schema", bot="bot_x", msgtype="deploy")
    assert "bot_x" in str(e) and "deploy" in str(e)
