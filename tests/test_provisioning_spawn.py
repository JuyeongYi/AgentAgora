import json
import pytest
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


def test_write_run_all_win_zellij_only(tmp_path):
    spawn.write_run_all(tmp_path, server_url="http://192.168.0.2:8420/mcp", platform="win32")
    ps = tmp_path / "run-all.ps1"
    assert ps.is_file()
    text = ps.read_text(encoding="ascii")  # ASCII 전용(비-ASCII 있으면 디코드 실패)
    assert "zellij" in text               # zellij 전용 (Windows도 OS 무관 통일)
    assert "wt.exe" not in text           # wt.exe 폴백 제거
    assert "Start-Process" not in text
    assert "new-tab" in text              # zellij 탭 생성
    assert ".mcp.json" in text            # 워커 디렉터리 판정
    assert "--bind-host 0.0.0.0" in text
    assert "env:ZELLIJ" in text           # 세션 안/밖 분기
    assert "--layout" in text             # 세션 밖이면 layout으로 새 세션 시작 후 재실행
    assert b"\r\n" in ps.read_bytes()     # CRLF (_write_bat 경유 — Windows 스크립트)
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
    assert "ZELLIJ" in text               # 세션 안/밖 분기
    assert "--layout" in text             # 세션 밖이면 layout으로 새 세션 시작 후 재실행
    assert "\r\n" not in text             # LF
    assert not (tmp_path / "run-all.ps1").exists()


@pytest.mark.parametrize("platform,name,worker", [
    ("linux", "run-all.sh", "run.sh"),
    ("win32", "run-all.ps1", "run.bat"),
])
def test_write_run_all_without_server(tmp_path, platform, name, worker):
    # server_launcher=False(include_server=False) → run-all은 서버를 띄우지 않고 워커만 기동.
    spawn.write_run_all(tmp_path, server_url="http://192.168.0.2:8420/mcp",
                        include_server=False, platform=platform)
    text = (tmp_path / name).read_text(encoding="utf-8")
    assert "new-tab --name server" not in text  # 서버 탭 안 만듦
    assert ".mcp.json" in text                   # 워커 판정/기동은 유지
    assert worker in text


@pytest.mark.parametrize("platform,name", [
    ("linux", "run-all.sh"), ("win32", "run-all.ps1")])
def test_write_run_all_with_server(tmp_path, platform, name):
    spawn.write_run_all(tmp_path, server_url="http://192.168.0.2:8420/mcp",
                        include_server=True, platform=platform)
    text = (tmp_path / name).read_text(encoding="utf-8")
    assert "new-tab --name server" in text       # zellij 서버 탭 생성 (OS 무관)
    assert "agent-agora" in text


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
