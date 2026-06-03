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
# 비대화형(--manifest)
# ---------------------------------------------------------------------------

def test_noninteractive_generates_all_artifacts(tmp_path):
    mpath = tmp_path / "team.json"
    mpath.write_text(json.dumps(_manifest_dict(tmp_path)), encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 0
    assert (tmp_path / "Coder1" / ".mcp.json").is_file()
    assert (tmp_path / "Reviewer1" / "run.bat").is_file()
    assert (tmp_path / "team.json").is_file()
    # server_launcher 기본 true → 서버 기동 스크립트 생성(현재 OS)
    assert (tmp_path / "run-server.bat").exists() or (tmp_path / "run-server.sh").exists()
    # run_all 기본 true → 전체 실행 스크립트 생성
    assert (tmp_path / "run-all.ps1").exists() or (tmp_path / "run-all.sh").exists()
    settings = json.loads(
        (tmp_path / "Coder1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-coder@agent-agora"] is True
    csv = (tmp_path / ".agentagora" / "comm-matrix.csv").read_text(encoding="utf-8")
    cm = CommMatrix()
    cm.load_csv(csv)
    assert cm.is_allowed("Coder1", "Reviewer1") is True
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


def test_noninteractive_server_launcher_false_skips(tmp_path):
    data = _manifest_dict(tmp_path)
    data["server_launcher"] = False
    data["run_all"] = False
    mpath = tmp_path / "team.json"
    mpath.write_text(json.dumps(data), encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 0
    assert not (tmp_path / "run-server.bat").exists()
    assert not (tmp_path / "run-server.sh").exists()
    assert not (tmp_path / "run-all.ps1").exists()
    assert not (tmp_path / "run-all.sh").exists()


def test_generate_output_is_cp949_safe(tmp_path):
    norm = {
        "version": 1,
        "spawn_dir": tmp_path.as_posix(),
        "server_url": "http://127.0.0.1:8420/mcp",
        "marketplace": {"type": "github", "repo": "JuyeongYi/AgentAgora-ClaudePlugins"},
        "server_launcher": True,
        "run_all": True,
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
# 대화형 — 페르소나 여부가 분기점
# ---------------------------------------------------------------------------

def test_interactive_single_worker_no_persona(tmp_path):
    answers = "\n".join([
        tmp_path.as_posix(),                            # 스폰 위치
        "http://127.0.0.1:8420/mcp",                    # 서버 URL
        "github",                                       # 마켓플레이스 소스
        "JuyeongYi/AgentAgora-ClaudePlugins",           # repo
        "n",                                            # 페르소나 미사용
        "Solo",                                         # 인스턴스 이름
        "y",                                            # 서버 실행 스크립트
        "n",                                            # 전체 실행 스크립트
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert len(m["team"]) == 1
    assert m["team"][0]["id"] == "Solo"
    assert m["team"][0]["persona"] == "none"
    assert m["server_launcher"] is True
    assert m["run_all"] is False


def test_interactive_multi_role_with_names(tmp_path):
    role_list = list(_roles.ROLES)
    answers = "\n".join([
        tmp_path.as_posix(),
        "http://127.0.0.1:8420/mcp",
        "github",
        "JuyeongYi/AgentAgora-ClaudePlugins",
        "y",                                            # 페르소나 사용
        "1,3",                                          # role 체크박스 → [0],[2]
        "",                                             # role[0] 이름 빈칸 → 역할명
        "Rev",                                          # role[2] 이름
        "1",                                            # 통신: 모두 서로
        "y",                                            # 서버 실행 스크립트
        "y",                                            # 전체 실행 스크립트
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert len(m["team"]) == 2
    # 빈칸 → 역할명 그대로 id, 입력 → 그 이름
    assert m["team"][0]["id"] == role_list[0]
    assert m["team"][0]["role"] == role_list[0]
    assert m["team"][1]["id"] == "Rev"
    assert m["team"][1]["role"] == role_list[2]
    assert m["team"][0]["allow"] == [".*"]
    assert m["team"][0]["persona"] is None
    assert m["run_all"] is True
