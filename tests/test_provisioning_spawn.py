import json
from agent_agora.provisioning import spawn

GH = {"type": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
DIR = {"type": "directory", "path": "C:/repo/plugin"}


def test_spawn_worker_github_source(tmp_path):
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="코딩 담당",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False,
    )
    assert rc == 0
    wd = tmp_path / "Coder1"
    assert (wd / "CLAUDE.md").is_file()
    assert (wd / "run.bat").is_file()
    mcp = json.loads((wd / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Instance-Id"] == "Coder1"
    settings = json.loads((wd / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    # 별칭 agent-agora(marketplace.json name과 일치) + github source
    assert settings["extraKnownMarketplaces"]["agent-agora"]["source"] == {
        "source": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
    assert settings["enabledPlugins"]["cc-agora-coder@agent-agora"] is True
    assert settings["enabledPlugins"]["cc-agora@agent-agora"] is True


def test_spawn_worker_directory_source(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=DIR, force=False,
    )
    settings = json.loads(
        (tmp_path / "W1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["extraKnownMarketplaces"]["agent-agora"]["source"] == {
        "source": "directory", "path": "C:/repo/plugin"}
    assert settings["enabledPlugins"]["cc-agora-coder@agent-agora"] is True


def test_spawn_undefined_role_falls_back_to_general(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="nonesuch", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False,
    )
    settings = json.loads(
        (tmp_path / "W1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-general@agent-agora"] is True


def test_spawn_existing_dir_without_force_fails(tmp_path):
    (tmp_path / "Coder1").mkdir()
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False,
    )
    assert rc == 1


def test_write_server_launcher(tmp_path):
    spawn.write_server_launcher(tmp_path)
    bat = (tmp_path / "run-server.bat").read_bytes()
    assert b"\r\n" in bat            # CRLF
    assert b"agent-agora" in bat


def test_find_marketplace_locates_repo_plugin():
    found = spawn.find_marketplace()
    assert found is None or found.endswith("plugin")
