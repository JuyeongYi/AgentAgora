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
        "marketplace_path": "C:/repo/plugin",
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
    # 워커 디렉터리
    assert (tmp_path / "Coder1" / ".mcp.json").is_file()
    assert (tmp_path / "Reviewer1" / "run.bat").is_file()
    # team.json 보존(spawn_dir에)
    assert (tmp_path / "team.json").is_file()
    # 서버 기동 스크립트
    assert (tmp_path / "run-server.bat").is_file()
    # 매트릭스 CSV — 방향 정합
    csv = (tmp_path / ".agentagora" / "comm-matrix.csv").read_text(encoding="utf-8")
    cm = CommMatrix()
    cm.load_csv(csv)
    assert cm.is_allowed("Coder1", "Reviewer1") is True   # Coder1.allow=[Reviewer1]
    assert cm.is_allowed("Reviewer1", "Coder1") is True   # Reviewer1.allow=[".*"]
    assert cm.is_allowed("Coder1", "Coder1") is False     # self 미명시


def test_noninteractive_bad_manifest_returns_1(tmp_path):
    mpath = tmp_path / "bad.json"
    mpath.write_text('{"version": 2, "team": []}', encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 1


def test_interactive_builds_manifest_from_stdin(tmp_path):
    answers = "\n".join([
        tmp_path.as_posix(),                          # 스폰 위치
        "http://127.0.0.1:8420/mcp",                  # 서버 URL
        "C:/repo/plugin",                             # 마켓플레이스
        "Coder1", "coder", "코딩", "Reviewer1", "y",   # 워커1 + 더 추가? y
        "Reviewer1", "reviewer", "리뷰", "*", "n",      # 워커2 + 더 추가? n
    ]) + "\n"
    norm = cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = _manifest.validate(norm)
    assert errors == []
    assert [e["id"] for e in m["team"]] == ["Coder1", "Reviewer1"]
    assert m["team"][1]["allow"] == [".*"]
