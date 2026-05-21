"""Tests for cc-agora-structure structure_spawn.py — manifest loading + validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugin" / "cc-agora-structure" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from structure_spawn import Manifest, PartitionSpec, load_manifest, render_staging, spawn, main  # noqa: E402


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_manifest_data(repo_str: str) -> dict:
    return {
        "version": 1,
        "repo": repo_str,
        "target_size": 80,
        "partitions": [
            {
                "id": "src-foo",
                "root": "src/foo",
                "weight": 50,
                "files": ["src/foo/a.py", "src/foo/b.py"],
                "suggested_role": "implementer",
                "coupling": [],
            }
        ],
        "warnings": [],
    }


def test_load_valid_manifest(tmp_path):
    path = _write_manifest(tmp_path, _valid_manifest_data("C:/repo"))
    m = load_manifest(path)
    assert isinstance(m, Manifest)
    assert m.version == 1
    assert m.repo == "C:/repo"
    assert m.target_size == 80
    assert len(m.partitions) == 1
    p = m.partitions[0]
    assert isinstance(p, PartitionSpec)
    assert p.id == "src-foo"
    assert p.root == "src/foo"
    assert p.files == ("src/foo/a.py", "src/foo/b.py")
    assert p.suggested_role == "implementer"


def test_reject_wrong_version(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["version"] = 2
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="version 1"):
        load_manifest(path)


def test_reject_missing_partition_field(tmp_path):
    data = _valid_manifest_data("C:/repo")
    del data["partitions"][0]["root"]
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="root"):
        load_manifest(path)


def test_reject_non_ascii_partition_id(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["partitions"][0]["id"] = "한글-id"
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="ASCII"):
        load_manifest(path)


def test_reject_empty_repo(tmp_path):
    data = _valid_manifest_data("")
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="repo"):
        load_manifest(path)


def test_reject_non_positive_target_size(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["target_size"] = 0
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="target_size"):
        load_manifest(path)


def test_reject_bool_version(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["version"] = True
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="version 1"):
        load_manifest(path)


def test_reject_empty_partition_id(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["partitions"][0]["id"] = ""
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="ASCII"):
        load_manifest(path)


def test_reject_non_list_files(tmp_path):
    data = _valid_manifest_data("C:/repo")
    data["partitions"][0]["files"] = "src/foo/a.py"
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ValueError, match="files"):
        load_manifest(path)


@pytest.fixture
def templates_dir():
    return REPO_ROOT / "plugin" / "cc-agora-structure" / "templates"


@pytest.fixture
def sample_partition():
    return PartitionSpec(
        id="src-foo",
        root="src/foo",
        weight=50,
        files=("src/foo/a.py", "src/foo/b.py"),
        suggested_role="implementer",
        coupling=(),
    )


def test_render_creates_expected_files(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    assert (staging / "CLAUDE.md").is_file()
    assert (staging / ".mcp.json").is_file()
    assert (staging / ".claude" / "settings.local.json").is_file()
    assert (staging / "run.bat").is_file()


def test_render_claude_md_contains_partition_details(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    body = (staging / "CLAUDE.md").read_text(encoding="utf-8")
    assert "src-foo" in body
    assert "src/foo" in body
    assert "src/foo/a.py" in body
    assert "src/foo/b.py" in body
    assert "using-git-worktrees" in body
    assert "code-review-graph" in body
    assert "sparse-checkout" in body
    assert worktree.as_posix() in body


def test_render_mcp_json_has_three_servers_and_ascii_headers(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    data = json.loads((staging / ".mcp.json").read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert set(servers.keys()) == {"agentagora", "agora-channel", "code-review-graph"}
    headers = servers["agentagora"]["headers"]
    assert headers["X-Agora-Cwd"] == staging.resolve().as_posix()
    assert headers["X-Agora-Role"] == "implementer"
    # ASCII check
    for k, v in headers.items():
        v.encode("latin-1")


def test_render_settings_whitelist_includes_both_paths(tmp_path, templates_dir, sample_partition):
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    settings = json.loads((staging / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    staging_glob = staging.resolve().as_posix() + "/**"
    worktree_glob = worktree.as_posix() + "/**"
    assert f"Edit({staging_glob})" in allow
    assert f"Write({staging_glob})" in allow
    assert f"Edit({worktree_glob})" in allow
    assert f"Write({worktree_glob})" in allow


def test_render_rejects_non_ascii_description(tmp_path, templates_dir):
    p = PartitionSpec(
        id="src-foo",
        root="src/한글",  # non-ASCII root → description would contain it
        weight=50,
        files=("src/한글/a.py",),
        suggested_role="implementer",
        coupling=(),
    )
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="ASCII"):
        render_staging(
            partition=p,
            staging_dir=staging,
            worktree_path=worktree,
            repo_path=repo,
            server_url="http://127.0.0.1:8420/mcp",
            marketplace_path=str(REPO_ROOT / "plugin"),
            templates_dir=templates_dir,
        )


def test_spawn_creates_all_staging_dirs(tmp_path, templates_dir):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # mark as git
    manifest = Manifest(
        version=1, repo=repo.as_posix(), target_size=80,
        partitions=(
            PartitionSpec(id="a", root="a", weight=10, files=("a/x.py",),
                          suggested_role="implementer", coupling=()),
            PartitionSpec(id="b", root="b", weight=10, files=("b/y.py",),
                          suggested_role="tester", coupling=()),
        ),
        warnings=(),
    )
    out = tmp_path / "workers"
    wt_base = tmp_path / "worktrees"
    dirs = spawn(
        manifest=manifest,
        out=out,
        worktree_base=wt_base,
        server_url="http://127.0.0.1:8420/mcp",
        launch="off",
        templates_dir=templates_dir,
        marketplace_path=str(REPO_ROOT / "plugin"),
        force=False,
    )
    assert len(dirs) == 2
    assert (out / "a" / "CLAUDE.md").is_file()
    assert (out / "b" / "CLAUDE.md").is_file()


def test_spawn_skips_empty_partition(tmp_path, templates_dir, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    manifest = Manifest(
        version=1, repo=repo.as_posix(), target_size=80,
        partitions=(
            PartitionSpec(id="empty", root="empty", weight=0, files=(),
                          suggested_role="implementer", coupling=()),
            PartitionSpec(id="good", root="good", weight=5, files=("good/x.py",),
                          suggested_role="implementer", coupling=()),
        ),
        warnings=(),
    )
    out = tmp_path / "workers"
    wt_base = tmp_path / "worktrees"
    dirs = spawn(
        manifest=manifest,
        out=out, worktree_base=wt_base,
        server_url="http://127.0.0.1:8420/mcp",
        launch="off", templates_dir=templates_dir,
        marketplace_path=str(REPO_ROOT / "plugin"),
        force=False,
    )
    assert len(dirs) == 1
    assert dirs[0].name == "good"
    captured = capsys.readouterr()
    assert "empty" in captured.err
    assert "skip" in captured.err.lower()


def test_spawn_rejects_existing_staging_without_force(tmp_path, templates_dir):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    out = tmp_path / "workers"
    (out / "a").mkdir(parents=True)
    (out / "a" / "marker").write_text("x")

    manifest = Manifest(
        version=1, repo=repo.as_posix(), target_size=80,
        partitions=(
            PartitionSpec(id="a", root="a", weight=5, files=("a/x.py",),
                          suggested_role="implementer", coupling=()),
        ),
        warnings=(),
    )
    with pytest.raises(FileExistsError):
        spawn(
            manifest=manifest, out=out,
            worktree_base=tmp_path / "worktrees",
            server_url="http://127.0.0.1:8420/mcp",
            launch="off", templates_dir=templates_dir,
            marketplace_path=str(REPO_ROOT / "plugin"),
            force=False,
        )


def test_main_rejects_non_git_repo(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()  # no .git

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "version": 1, "repo": repo.as_posix(), "target_size": 80,
        "partitions": [
            {"id": "a", "root": "a", "weight": 5,
             "files": ["a/x.py"], "suggested_role": "implementer", "coupling": []}
        ],
        "warnings": [],
    }))
    rc = main(["--manifest", str(manifest_path), "--launch", "off",
               "--out", str(tmp_path / "workers"),
               "--worktree-base", str(tmp_path / "worktrees")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "not a git repo" in captured.err


def test_main_returns_1_on_bad_manifest(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "version": 2,  # wrong version
        "repo": "C:/x", "target_size": 80,
        "partitions": [], "warnings": [],
    }))
    rc = main(["--manifest", str(manifest_path), "--launch", "off"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "bad manifest" in captured.err


def test_render_run_bat_lowers_autocompact_threshold(tmp_path, templates_dir, sample_partition):
    """The rendered run.bat must set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60 so the
    worker compacts well before the context wall (worker cannot self-trigger /compact)."""
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    run_bat = (staging / "run.bat").read_text(encoding="utf-8")
    assert "set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60" in run_bat


def test_render_run_bat_passes_name_from_cwd(tmp_path, templates_dir, sample_partition):
    """The rendered run.bat must derive --name from the script's own folder
    basename so Claude Code session is labeled per partition."""
    staging = tmp_path / "workers" / "src-foo"
    worktree = tmp_path / "worktrees" / "src-foo"
    repo = tmp_path / "repo"
    repo.mkdir()
    render_staging(
        partition=sample_partition,
        staging_dir=staging,
        worktree_path=worktree,
        repo_path=repo,
        server_url="http://127.0.0.1:8420/mcp",
        marketplace_path=str(REPO_ROOT / "plugin"),
        templates_dir=templates_dir,
    )
    run_bat = (staging / "run.bat").read_text(encoding="utf-8")
    assert 'for %%I in ("%~dp0.") do set "AGORA_NAME=%%~nxI"' in run_bat
    assert '--name "%AGORA_NAME%"' in run_bat
