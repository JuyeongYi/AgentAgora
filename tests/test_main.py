from __future__ import annotations

from agent_agora.__main__ import parse_args


def test_no_tls_default_false():
    args = parse_args([])
    assert args.no_tls is False


def test_no_tls_flag_enables_http():
    args = parse_args(["--no-tls"])
    assert args.no_tls is True


def test_port_default():
    args = parse_args([])
    assert args.port == 8420


def test_no_timeout_and_default_wait_are_exclusive():
    import pytest

    with pytest.raises(SystemExit):
        parse_args(["--no-timeout", "--default-wait-timeout-ms", "5000"])


def test_build_app_wires_schema_registry(tmp_path):
    from agent_agora.__main__ import _build_app
    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    mcp = _build_app(agora_dir=agora_dir, port=0)
    schema_registry = mcp._agora_schema_registry
    # 기본 schema 6종이 시작 시 로드됨
    assert schema_registry.get("worker_freeform") is not None
    assert schema_registry.get("bot_reply") is not None
    # .agentagora/schemas.jsonl이 동봉본에서 복사됨
    assert (agora_dir / "schemas.jsonl").is_file()
    # SQLite에도 영속됨
    assert len(mcp._agora_persistence.restore_schemas()) >= 6
