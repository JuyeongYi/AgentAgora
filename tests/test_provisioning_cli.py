import json
import io
from agent_agora.provisioning import cli
from agent_agora.provisioning import manifest as _manifest
from agent_agora.comm_matrix import CommMatrix


def _manifest_dict(tmp_path):
    return {
        "version": 1,
        "spawn_dir": tmp_path.as_posix(),
        "server_url": "http://127.0.0.1:8420/mcp",
        "marketplace": {"type": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"},
        "team": [
            {"id": "Coder1", "role": "coder", "description": "코딩", "allow": ["Reviewer1"]},
            {"id": "Reviewer1", "role": "reviewer", "description": "리뷰", "allow": ["*"]},
        ],
    }


def test_noninteractive_generates_all_artifacts(tmp_path):
    mpath = tmp_path / "team.json"
    mpath.write_text(json.dumps(_manifest_dict(tmp_path)), encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 0
    assert (tmp_path / "Coder1" / ".mcp.json").is_file()
    assert (tmp_path / "Reviewer1" / "run.bat").is_file()
    assert (tmp_path / "team.json").is_file()
    # agora-init은 에이전트 스폰만 — 서버 기동 스크립트는 만들지 않는다
    assert not (tmp_path / "run-server.bat").exists()
    # settings: github source + agent-agora 별칭 + 페르소나 플러그인(role 매핑)
    settings = json.loads(
        (tmp_path / "Coder1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["extraKnownMarketplaces"]["agent-agora"]["source"] == {
        "source": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
    assert settings["enabledPlugins"]["cc-agora-coder@agent-agora"] is True
    # 매트릭스 CSV — 방향 정합
    csv = (tmp_path / ".agentagora" / "comm-matrix.csv").read_text(encoding="utf-8")
    cm = CommMatrix()
    cm.load_csv(csv)
    assert cm.is_allowed("Coder1", "Reviewer1") is True
    assert cm.is_allowed("Reviewer1", "Coder1") is True
    assert cm.is_allowed("Coder1", "Coder1") is False


def test_noninteractive_persona_none_core_only(tmp_path):
    data = _manifest_dict(tmp_path)
    data["team"][0]["persona"] = "none"
    mpath = tmp_path / "team.json"
    mpath.write_text(json.dumps(data), encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 0
    settings = json.loads(
        (tmp_path / "Coder1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    # 페르소나 플러그인 없이 cc-agora만
    assert settings["enabledPlugins"] == {"cc-agora@agent-agora": True}
    # 다른 워커(persona 미지정)는 role 매핑 유지
    s2 = json.loads(
        (tmp_path / "Reviewer1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert s2["enabledPlugins"]["cc-agora-reviewer@agent-agora"] is True


def test_generate_output_is_cp949_safe(tmp_path):
    """Windows cp949 콘솔에서 진행/완료 print가 인코딩 가능해야 한다(em dash 등 금지)."""
    norm = {
        "version": 1,
        "spawn_dir": tmp_path.as_posix(),
        "server_url": "http://127.0.0.1:8420/mcp",
        "marketplace": {"type": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"},
        "team": [{"id": "Coder1", "role": "coder", "description": "x", "allow": ["Reviewer1"],
                  "persona": None}],
        "warnings": [],
    }
    buf = io.BytesIO()
    out = io.TextIOWrapper(buf, encoding="cp949", newline="")
    rc = cli._generate(norm, stdout=out, stderr=out)
    out.flush()
    assert rc == 0


def test_noninteractive_bad_manifest_returns_1(tmp_path):
    mpath = tmp_path / "bad.json"
    mpath.write_text('{"version": 2, "team": []}', encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 1


def test_interactive_github_source_from_stdin(tmp_path):
    answers = "\n".join([
        tmp_path.as_posix(),                            # 스폰 위치
        "http://127.0.0.1:8420/mcp",                    # 서버 URL
        "github",                                       # 마켓플레이스 소스
        "JuyeongYi/AgentAgora-ClaudePlugins",           # repo
        "Coder1", "coder", "y", "코딩", "Reviewer1", "y",  # 워커1(persona y) + 더 추가? y
        "Reviewer1", "reviewer", "y", "리뷰", "*", "n",    # 워커2(persona y) + 더 추가? n
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert m["marketplace"] == {"type": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
    assert [e["id"] for e in m["team"]] == ["Coder1", "Reviewer1"]
    assert m["team"][1]["allow"] == [".*"]
    assert m["team"][0].get("persona") is None   # y → role 매핑


def test_interactive_directory_source_from_stdin(tmp_path):
    answers = "\n".join([
        tmp_path.as_posix(),
        "http://127.0.0.1:8420/mcp",
        "directory",                                    # 마켓플레이스 소스
        "C:/repo/plugin",                               # 로컬 경로
        "W1", "coder", "y", "x", "", "n",               # 워커1(persona y, allow 없음) + 종료
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert m["marketplace"] == {"type": "directory", "path": "C:/repo/plugin"}


def test_interactive_persona_none_when_n(tmp_path):
    answers = "\n".join([
        tmp_path.as_posix(),
        "http://127.0.0.1:8420/mcp",
        "github",
        "JuyeongYi/AgentAgora-ClaudePlugins",
        "W1", "coder", "n", "x", "", "n",               # persona n → none
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert m["team"][0]["persona"] == "none"
