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
