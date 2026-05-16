"""Unit tests for plugin/cc-agora/scripts/spawn.py::do_spawn (채널 모드).

do_spawn을 target_dir=tmp_path로 직접 호출해 생성 파일을 격리 검증한다.
채널 모드 워커는 CLAUDE.md + .mcp.json(2-서버) + run.bat 3파일 — Stop hook
없음.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spawn import DEFAULT_SERVER_URL, do_spawn

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora"


def _call(tmp_path: Path, **overrides) -> int:
    kwargs = dict(
        instance_id="Worker1",
        role="coder",
        description="테스트용 워커.",
        preset=None,
        target_dir=tmp_path,
        force=False,
        server_url=DEFAULT_SERVER_URL,
        plugin_root=PLUGIN_ROOT,
        stderr=sys.stderr,
        stdout=sys.stdout,
    )
    kwargs.update(overrides)
    return do_spawn(**kwargs)


def test_spawn_creates_channel_mode_files(tmp_path: Path) -> None:
    rc = _call(tmp_path, instance_id="Coder1", role="coder")
    assert rc == 0
    worker = tmp_path / "Coder1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    assert (worker / "run.bat").is_file()
    # 채널 모드 워커는 Stop hook이 없다 — .claude/ 미생성.
    assert not (worker / ".claude").exists()

    claude_md = (worker / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Coder1" in claude_md
    assert "테스트용 워커" in claude_md
    assert "Coder 페르소나" in claude_md


def test_spawn_mcp_json_two_servers(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="W2", role="coder") == 0
    mcp = json.loads((tmp_path / "W2" / ".mcp.json").read_text(encoding="utf-8"))
    servers = mcp["mcpServers"]
    assert set(servers) == {"agentagora", "agora-channel"}
    headers = servers["agentagora"]["headers"]
    assert set(headers) == {
        "X-Agora-Instance-Id", "X-Agora-Role", "X-Agora-Description"}
    assert headers["X-Agora-Instance-Id"] == "W2"
    assert headers["X-Agora-Role"] == "coder"
    ch = servers["agora-channel"]
    assert ch["type"] == "stdio"
    assert ch["command"] == "agora-channel"
    assert ch["args"] == [
        "--instance-id", "W2", "--broker", DEFAULT_SERVER_URL]


def test_spawn_run_bat_launches_channel_mode(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="W3", role="coder") == 0
    run_bat = (tmp_path / "W3" / "run.bat").read_text(encoding="utf-8")
    assert "claude" in run_bat
    assert "--dangerously-load-development-channels" in run_bat
    assert "server:agora-channel" in run_bat


def test_spawn_undefined_role_falls_back_to_general(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _call(tmp_path, instance_id="Ghost1", role="phantom")
    assert rc == 0
    worker = tmp_path / "Ghost1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    assert (worker / "run.bat").is_file()
    err = capsys.readouterr().err
    assert "phantom" in err
    assert "roles.json" in err
    claude_md = (worker / "CLAUDE.md").read_text(encoding="utf-8")
    assert "General 페르소나" in claude_md


def test_spawn_existing_dir_without_force_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _call(tmp_path, instance_id="Dup1", role="coder") == 0
    capsys.readouterr()
    rc = _call(tmp_path, instance_id="Dup1", role="coder")
    assert rc == 1
    err = capsys.readouterr().err
    assert "이미 존재" in err
    assert "--force" in err


def test_spawn_existing_dir_with_force_overwrites(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="OverW", role="coder") == 0
    target = tmp_path / "OverW" / "CLAUDE.md"
    target.write_text("MUTATED", encoding="utf-8")
    assert _call(tmp_path, instance_id="OverW", role="coder",
                 force=True, description="새 설명") == 0
    refreshed = target.read_text(encoding="utf-8")
    assert "MUTATED" not in refreshed
    assert "새 설명" in refreshed


def test_spawn_preset_override(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="PCoder", role="coder",
                 preset="reviewer") == 0
    body = (tmp_path / "PCoder" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "PCoder (coder)" in body
    assert "Reviewer 페르소나" in body
    assert "Coder 페르소나" not in body


def test_spawn_description_with_quotes_and_unicode(tmp_path: Path) -> None:
    desc = 'React "로그인" 폼 + 한글 — backslash \\ included'
    assert _call(tmp_path, instance_id="Quoted1", role="coder",
                 description=desc) == 0
    mcp = json.loads((tmp_path / "Quoted1" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Description"] == desc
