"""Unit tests for plugin/cc-agora-ops/scripts/role_policy.py."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from role_policy import (
    is_defined,
    load_roles,
    plugin_for,
    undefined_role_warning,
    warn_undefined_role,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora-ops"
ROLES_PATH = PLUGIN_ROOT / "config" / "roles.json"


@pytest.fixture(scope="module")
def roles() -> dict:
    return load_roles(ROLES_PATH)


def test_plugin_for_defined_role():
    roles = load_roles(ROLES_PATH)
    assert plugin_for("coder", roles) == "cc-agora-coder"


def test_plugin_for_undefined_role_is_none():
    roles = load_roles(ROLES_PATH)
    assert plugin_for("phantom", roles) is None


def test_all_seven_roles_map_to_persona_plugins():
    roles = load_roles(ROLES_PATH)
    for role in ("orchestrator", "coder", "reviewer", "tester", "writer", "planner", "general"):
        assert plugin_for(role, roles) == f"cc-agora-{role}"


def test_is_defined(roles: dict) -> None:
    assert is_defined("coder", roles) is True
    assert is_defined("phantom", roles) is False


def test_undefined_role_warning_contains_name_and_guide() -> None:
    msg = undefined_role_warning("phantom")
    assert "phantom" in msg
    assert "roles.json" in msg
    assert "plugin" in msg


def test_warn_undefined_role_writes_to_stream() -> None:
    buf = io.StringIO()
    warn_undefined_role("phantom", stream=buf)
    out = buf.getvalue()
    assert "phantom" in out
    assert out.endswith("\n")


def test_load_roles_invalid_root(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError, match="object at top level"):
        load_roles(bad)
