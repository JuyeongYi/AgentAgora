"""Unit tests for plugin/cc-agora/scripts/role_policy.py (spec §8.8.1)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from role_policy import (
    hook_for,
    is_defined,
    load_roles,
    preset_for,
    undefined_role_warning,
    wait_mode_for,
    warn_undefined_role,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora"
ROLES_PATH = PLUGIN_ROOT / "config" / "roles.json"


@pytest.fixture(scope="module")
def roles() -> dict:
    return load_roles(ROLES_PATH)


def test_hook_for_defined(roles: dict) -> None:
    assert hook_for("orchestrator", roles) == "none"
    assert hook_for("coder", roles) == "stop-auto-wait"
    assert hook_for("reviewer", roles) == "stop-auto-wait"


def test_hook_for_undefined(roles: dict) -> None:
    assert hook_for("phantom", roles) is None


def test_wait_mode_derive(roles: dict) -> None:
    assert wait_mode_for("coder", roles) == "auto"
    assert wait_mode_for("orchestrator", roles) == "manual"
    assert wait_mode_for("phantom", roles) is None


def test_preset_for(roles: dict) -> None:
    assert preset_for("coder", roles) == "coder"
    assert preset_for("orchestrator", roles) == "orchestrator"
    assert preset_for("reviewer", roles) == "reviewer"
    assert preset_for("phantom", roles) is None


def test_is_defined(roles: dict) -> None:
    assert is_defined("coder", roles) is True
    assert is_defined("phantom", roles) is False


def test_undefined_role_warning_contains_name_and_guide() -> None:
    msg = undefined_role_warning("phantom")
    assert "phantom" in msg
    assert "roles.json" in msg
    assert "hook" in msg
    # Editing guidance must include both the JSON snippet shape and the
    # settings.local.json follow-up to be actionable.
    assert "stop-auto-wait" in msg
    assert "settings.local.json" in msg


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
