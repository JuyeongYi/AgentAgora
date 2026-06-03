import json
from agent_agora.provisioning import spawn

GH = {"type": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
DIR = {"type": "directory", "path": "C:/repo/plugin"}


def test_spawn_worker_github_source(tmp_path):
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="코딩 담당",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, platform="win32",
    )
    assert rc == 0
    wd = tmp_path / "Coder1"
    assert (wd / "CLAUDE.md").is_file()
    assert (wd / "run.bat").is_file()
    mcp = json.loads((wd / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Instance-Id"] == "Coder1"
    settings = json.loads((wd / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["extraKnownMarketplaces"]["agent-agora"]["source"] == {
        "source": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
    assert settings["enabledPlugins"]["cc-agora-coder@agent-agora"] is True
    assert settings["enabledPlugins"]["cc-agora@agent-agora"] is True


def test_spawn_worker_directory_source(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=DIR, force=False, platform="win32",
    )
    settings = json.loads(
        (tmp_path / "W1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["extraKnownMarketplaces"]["agent-agora"]["source"] == {
        "source": "directory", "path": "C:/repo/plugin"}


def test_spawn_worker_linux_creates_run_sh(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, platform="linux",
    )
    wd = tmp_path / "W1"
    sh = wd / "run.sh"
    assert sh.is_file()
    assert not (wd / "run.bat").exists()
    text = sh.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "\r\n" not in text  # LF (CRLF 아님)


def test_spawn_is_agent_only_no_server_launcher(tmp_path):
    # agora-init은 에이전트 스폰만 — 서버 기동 스크립트는 만들지 않는다.
    spawn.spawn_worker(
        instance_id="W1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, platform="win32",
    )
    assert not (tmp_path / "run-server.bat").exists()
    assert not (tmp_path / "W1" / "run-server.bat").exists()
    assert not (tmp_path / "run-server.sh").exists()
    assert not hasattr(spawn, "write_server_launcher")


def test_spawn_undefined_role_falls_back_to_general(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="nonesuch", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, platform="win32",
    )
    settings = json.loads(
        (tmp_path / "W1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-general@agent-agora"] is True


def test_spawn_existing_dir_without_force_fails(tmp_path):
    (tmp_path / "Coder1").mkdir()
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, platform="win32",
    )
    assert rc == 1


def test_find_marketplace_locates_repo_plugin():
    found = spawn.find_marketplace()
    assert found is None or found.endswith("plugin")
