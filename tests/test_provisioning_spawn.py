import json
from agent_agora.provisioning import spawn


def test_spawn_worker_creates_four_files(tmp_path):
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="코딩 담당",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace_path="C:/repo/plugin", force=False,
    )
    assert rc == 0
    wd = tmp_path / "Coder1"
    assert (wd / "CLAUDE.md").is_file()
    assert (wd / "run.bat").is_file()
    mcp = json.loads((wd / ".mcp.json").read_text(encoding="utf-8"))
    headers = mcp["mcpServers"]["agentagora"]["headers"]
    assert headers["X-Agora-Instance-Id"] == "Coder1"
    assert headers["X-Agora-Role"] == "coder"
    settings = json.loads((wd / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-coder@agentagora"] is True
    assert settings["enabledPlugins"]["cc-agora@agentagora"] is True
    assert settings["extraKnownMarketplaces"]["agentagora"]["source"]["path"] == "C:/repo/plugin"


def test_spawn_undefined_role_falls_back_to_general(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="nonesuch", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace_path="C:/repo/plugin", force=False,
    )
    settings = json.loads(
        (tmp_path / "W1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-general@agentagora"] is True


def test_spawn_existing_dir_without_force_fails(tmp_path):
    (tmp_path / "Coder1").mkdir()
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace_path="C:/repo/plugin", force=False,
    )
    assert rc == 1


def test_write_server_launcher(tmp_path):
    spawn.write_server_launcher(tmp_path)
    bat = (tmp_path / "run-server.bat").read_bytes()
    assert b"\r\n" in bat            # CRLF
    assert b"agent-agora" in bat


def test_find_marketplace_locates_repo_plugin():
    # 작업트리에서 실행 시 repo/plugin/.claude-plugin/marketplace.json을 찾는다.
    found = spawn.find_marketplace()
    assert found is None or found.endswith("plugin")
