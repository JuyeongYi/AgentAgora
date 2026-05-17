"""Unit tests for plugin/cc-agora-ops/scripts/comm_matrix.py."""
from __future__ import annotations

import pytest

from comm_matrix import build_request


def test_build_request_get():
    method, url, headers, body = build_request(
        action="get", server_url="http://127.0.0.1:8420", token="t0ken", csv=None)
    assert method == "GET"
    assert url == "http://127.0.0.1:8420/admin/comm-matrix"
    assert headers["Authorization"] == "Bearer t0ken"
    assert body is None


def test_build_request_post_includes_csv_body():
    method, url, headers, body = build_request(
        action="post", server_url="http://127.0.0.1:8420", token="t0ken",
        csv="A,B\n0,1\n1,0")
    assert method == "POST"
    assert body == "A,B\n0,1\n1,0"
    assert headers["Authorization"] == "Bearer t0ken"


def test_build_request_missing_token_raises():
    with pytest.raises(ValueError, match="AGORA_ADMIN_TOKEN"):
        build_request(action="get", server_url="http://127.0.0.1:8420",
                      token=None, csv=None)


def test_build_request_post_without_csv_raises():
    with pytest.raises(ValueError, match="csv"):
        build_request(action="post", server_url="http://127.0.0.1:8420",
                      token="t0ken", csv=None)
