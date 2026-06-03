import json
import io
from agent_agora.provisioning import cli
from agent_agora.provisioning import manifest as _manifest
from agent_agora.provisioning import roles as _roles
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


# ---------------------------------------------------------------------------
# 비대화형(--manifest) — manifest 직접
# ---------------------------------------------------------------------------

def test_noninteractive_generates_all_artifacts(tmp_path):
    mpath = tmp_path / "team.json"
    mpath.write_text(json.dumps(_manifest_dict(tmp_path)), encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 0
    assert (tmp_path / "Coder1" / ".mcp.json").is_file()
    assert (tmp_path / "Reviewer1" / "run.bat").is_file()
    assert (tmp_path / "team.json").is_file()
    assert not (tmp_path / "run-server.bat").exists()
    settings = json.loads(
        (tmp_path / "Coder1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["extraKnownMarketplaces"]["agent-agora"]["source"] == {
        "source": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"}
    assert settings["enabledPlugins"]["cc-agora-coder@agent-agora"] is True
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
    assert settings["enabledPlugins"] == {"cc-agora@agent-agora": True}


def test_generate_output_is_cp949_safe(tmp_path):
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


# ---------------------------------------------------------------------------
# 대화형 — role 다중 선택(체크박스, 비-tty면 번호 폴백) → 워커 일괄
# ---------------------------------------------------------------------------

def test_role_to_id_pascal_case():
    assert cli._role_to_id("coder") == "Coder"
    assert cli._role_to_id("sp-planner") == "SpPlanner"
    assert cli._role_to_id("orchestrator") == "Orchestrator"


def test_interactive_multi_role_checkbox_fallback(tmp_path):
    role_list = list(_roles.ROLES)
    answers = "\n".join([
        tmp_path.as_posix(),                            # 스폰 위치
        "http://127.0.0.1:8420/mcp",                    # 서버 URL
        "github",                                       # 마켓플레이스 소스
        "JuyeongYi/AgentAgora-ClaudePlugins",           # repo
        "1,3",                                          # role 체크박스(번호 폴백) → [0],[2]
        "y",                                            # 페르소나 사용
        "1",                                            # 통신: 모두 서로
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert len(m["team"]) == 2
    assert m["team"][0]["role"] == role_list[0]
    assert m["team"][1]["role"] == role_list[2]
    assert m["team"][0]["allow"] == [".*"]              # * → .*
    assert m["team"][0]["persona"] is None              # y → role 매핑
    # id는 role의 PascalCase
    assert m["team"][0]["id"] == cli._role_to_id(role_list[0])


def test_interactive_persona_none_and_no_comm(tmp_path):
    answers = "\n".join([
        tmp_path.as_posix(),
        "http://127.0.0.1:8420/mcp",
        "github",
        "JuyeongYi/AgentAgora-ClaudePlugins",
        "2",                                            # role 1개
        "n",                                            # 페르소나 none
        "2",                                            # 통신: 없음
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert m["team"][0]["persona"] == "none"
    assert m["team"][0]["allow"] == []
