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


def test_spawn_worker_does_not_create_server_launcher(tmp_path):
    # spawn_worker는 워커 파일만 — 서버 런처는 write_server_launcher가 별도로 만든다.
    spawn.spawn_worker(
        instance_id="W1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, platform="win32",
    )
    assert not (tmp_path / "W1" / "run-server.bat").exists()
    assert not (tmp_path / "run-server.bat").exists()


def test_write_server_launcher_win_lan_bind(tmp_path):
    spawn.write_server_launcher(tmp_path, server_url="http://192.168.0.2:8420/mcp", platform="win32")
    bat = (tmp_path / "run-server.bat").read_text(encoding="utf-8")
    assert "agent-agora" in bat
    assert "8420" in bat
    assert "--bind-host 0.0.0.0" in bat   # 비-로컬 호스트 → 전 인터페이스 바인딩
    assert (tmp_path / "run-server.bat").read_bytes().count(b"\r\n") > 0  # CRLF
    assert not (tmp_path / "run-server.sh").exists()


def test_write_server_launcher_local_no_bind(tmp_path):
    spawn.write_server_launcher(tmp_path, server_url="http://127.0.0.1:8420/mcp", platform="win32")
    bat = (tmp_path / "run-server.bat").read_text(encoding="utf-8")
    assert "--bind-host" not in bat       # 로컬 호스트 → 기본(127.0.0.1)


def test_write_server_launcher_posix(tmp_path):
    spawn.write_server_launcher(tmp_path, server_url="http://192.168.0.2:9000/mcp", platform="linux")
    sh = tmp_path / "run-server.sh"
    assert sh.is_file()
    text = sh.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "agent-agora" in text
    assert "9000" in text                 # server_url의 포트
    assert "--bind-host 0.0.0.0" in text
    assert "\r\n" not in text             # LF
    assert not (tmp_path / "run-server.bat").exists()


def test_write_run_all_win(tmp_path):
    spawn.write_run_all(tmp_path, server_url="http://192.168.0.2:8420/mcp", platform="win32")
    ps = (tmp_path / "run-all.ps1").read_text(encoding="utf-8")
    assert ".mcp.json" in ps              # 워커 디렉터리 판정
    assert "wt.exe" in ps or "Start-Process" in ps
    assert "--bind-host 0.0.0.0" in ps
    assert not (tmp_path / "run-all.sh").exists()


def test_write_run_all_posix_zellij_only(tmp_path):
    spawn.write_run_all(tmp_path, server_url="http://192.168.0.2:8420/mcp", platform="linux")
    sh = tmp_path / "run-all.sh"
    assert sh.is_file()
    text = sh.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "zellij" in text               # zellij 전용
    assert "tmux" not in text             # zellij 세션 안 tmux 중첩 방지
    assert ".mcp.json" in text
    assert "--bind-host 0.0.0.0" in text
    assert "\r\n" not in text             # LF
    assert not (tmp_path / "run-all.ps1").exists()


def test_spawn_worker_no_persona_core_only(tmp_path):
    # persona="none" → 페르소나 플러그인 없이 cc-agora만 활성화.
    spawn.spawn_worker(
        instance_id="W1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace=GH, force=False, persona="none", platform="win32",
    )
    wd = tmp_path / "W1"
    settings = json.loads((wd / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"] == {"cc-agora@agent-agora": True}
    # CLAUDE.md에 역할 페르소나 플러그인 언급이 없어야 한다
    claude = (wd / "CLAUDE.md").read_text(encoding="utf-8")
    assert "cc-agora-coder" not in claude


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
