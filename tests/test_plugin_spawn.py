"""Unit tests for plugin/cc-agora/scripts/spawn.py::do_spawn (spec §8.8).

Each test calls ``do_spawn`` directly with target_dir=tmp_path so created files
are isolated and the test stays deterministic. We assert on the four-file
layout, mcp.json validity + headers, and stderr behaviour for undefined roles.

WHY pass sys.stderr/sys.stdout explicitly: ``do_spawn``'s default arguments
``stderr=sys.stderr``/``stdout=sys.stdout`` bind at import time, *before*
pytest's ``capsys`` swaps the real ``sys.stderr``. Passing them at call time
forces the freshly rebound stream so captured output is non-empty.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spawn import DEFAULT_SERVER_URL, DEFAULT_WAIT_TIMEOUT_MS, do_spawn

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora"


def _call(
    tmp_path: Path,
    **overrides,
) -> int:
    """Common ``do_spawn`` invocation. Override keyword arguments as needed."""
    kwargs = dict(
        instance_id="Worker1",
        role="coder",
        description="테스트용 워커.",
        preset=None,
        target_dir=tmp_path,
        force=False,
        server_url=DEFAULT_SERVER_URL,
        wait_timeout_ms=DEFAULT_WAIT_TIMEOUT_MS,
        plugin_root=PLUGIN_ROOT,
        stderr=sys.stderr,
        stdout=sys.stdout,
    )
    kwargs.update(overrides)
    return do_spawn(**kwargs)


def test_spawn_defined_role_creates_three_files(tmp_path: Path) -> None:
    rc = _call(tmp_path, instance_id="Coder1", role="coder")
    assert rc == 0
    worker = tmp_path / "Coder1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    assert (worker / ".claude" / "settings.local.json").is_file()
    # type:"prompt" Stop hook — no separate stop-hook.py file.
    assert not (worker / ".claude" / "stop-hook.py").exists()

    claude_md = (worker / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Coder1" in claude_md
    assert "coder" in claude_md
    assert "테스트용 워커" in claude_md
    # Coder preset header is the body that gets appended after the auto header.
    assert "Coder 페르소나" in claude_md

    mcp = json.loads((worker / ".mcp.json").read_text(encoding="utf-8"))
    headers = mcp["mcpServers"]["agentagora"]["headers"]
    assert headers["X-Agora-Instance-Id"] == "Coder1"
    assert headers["X-Agora-Role"] == "coder"
    assert headers["X-Agora-Description"] == "테스트용 워커."
    assert headers["X-Agora-Wait-Mode"] == "auto"
    assert headers["X-Agora-Wait-Timeout-Ms"] == "0"
    # Five header keys total for a defined role (id, role, desc, wait-mode,
    # wait-timeout-ms).
    assert len(headers) == 5


def test_spawn_undefined_role_omits_hook_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _call(tmp_path, instance_id="Ghost1", role="phantom")
    assert rc == 0
    worker = tmp_path / "Ghost1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    assert not (worker / ".claude").exists()

    captured = capsys.readouterr()
    assert "phantom" in captured.err
    assert "roles.json" in captured.err

    mcp = json.loads((worker / ".mcp.json").read_text(encoding="utf-8"))
    headers = mcp["mcpServers"]["agentagora"]["headers"]
    assert "X-Agora-Wait-Mode" not in headers
    # Undefined role still has the four other headers; sentinel line must be
    # dropped entirely (no empty key, no trailing comma corruption).
    assert len(headers) == 4
    assert headers["X-Agora-Instance-Id"] == "Ghost1"
    # CLAUDE.md falls back to general preset for undefined role.
    claude_md = (worker / "CLAUDE.md").read_text(encoding="utf-8")
    assert "General 페르소나" in claude_md


def test_spawn_existing_dir_without_force_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _call(tmp_path, instance_id="Dup1", role="coder") == 0
    capsys.readouterr()  # drain success message
    rc = _call(tmp_path, instance_id="Dup1", role="coder")
    assert rc == 1
    err = capsys.readouterr().err
    assert "이미 존재" in err
    assert "--force" in err


def test_spawn_existing_dir_with_force_overwrites(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="OverW", role="coder") == 0
    # Mutate CLAUDE.md to detect overwrite.
    target = tmp_path / "OverW" / "CLAUDE.md"
    target.write_text("MUTATED", encoding="utf-8")
    assert (
        _call(tmp_path, instance_id="OverW", role="coder", force=True, description="새 설명")
        == 0
    )
    refreshed = target.read_text(encoding="utf-8")
    assert "MUTATED" not in refreshed
    assert "새 설명" in refreshed


def test_spawn_preset_override(tmp_path: Path) -> None:
    rc = _call(tmp_path, instance_id="PCoder", role="coder", preset="reviewer")
    assert rc == 0
    body = (tmp_path / "PCoder" / "CLAUDE.md").read_text(encoding="utf-8")
    # Role stays 'coder' in header, but the persona body is reviewer's.
    assert "PCoder (coder)" in body
    assert "Reviewer 페르소나" in body
    assert "Coder 페르소나" not in body


def test_spawn_orchestrator_no_hook_files(tmp_path: Path) -> None:
    rc = _call(tmp_path, instance_id="Orch1", role="orchestrator")
    assert rc == 0
    worker = tmp_path / "Orch1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    # orchestrator hook=none → no settings.local.json / stop-hook.py.
    assert not (worker / ".claude").exists()

    mcp = json.loads((worker / ".mcp.json").read_text(encoding="utf-8"))
    headers = mcp["mcpServers"]["agentagora"]["headers"]
    assert headers["X-Agora-Wait-Mode"] == "manual"


def test_spawn_renders_valid_mcp_json_both_branches(tmp_path: Path) -> None:
    # defined-role branch
    assert _call(tmp_path, instance_id="ValidA", role="coder") == 0
    mcp_a = json.loads((tmp_path / "ValidA" / ".mcp.json").read_text(encoding="utf-8"))
    assert set(mcp_a["mcpServers"]["agentagora"]["headers"].keys()) == {
        "X-Agora-Instance-Id",
        "X-Agora-Role",
        "X-Agora-Description",
        "X-Agora-Wait-Mode",
        "X-Agora-Wait-Timeout-Ms",
    }
    # undefined-role branch
    assert _call(tmp_path, instance_id="ValidB", role="ghost-role") == 0
    mcp_b = json.loads((tmp_path / "ValidB" / ".mcp.json").read_text(encoding="utf-8"))
    assert set(mcp_b["mcpServers"]["agentagora"]["headers"].keys()) == {
        "X-Agora-Instance-Id",
        "X-Agora-Role",
        "X-Agora-Description",
        "X-Agora-Wait-Timeout-Ms",
    }


def test_spawn_description_with_quotes_and_unicode(tmp_path: Path) -> None:
    desc = 'React "로그인" 폼 + 한글 — backslash \\ included'
    rc = _call(tmp_path, instance_id="Quoted1", role="coder", description=desc)
    assert rc == 0
    raw = (tmp_path / "Quoted1" / ".mcp.json").read_text(encoding="utf-8")
    mcp = json.loads(raw)
    # Description survives JSON encoding round-trip exactly.
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Description"] == desc
