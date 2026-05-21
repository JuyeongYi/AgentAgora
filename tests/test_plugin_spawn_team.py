"""Unit tests for plugin/cc-agora-ops/scripts/spawn_team.py (spec §8.8.2/3).

Two layers:

* ``_validate_manifest`` — pure JSON validation. No side effects.
* ``main`` end-to-end — JSON file → ``do_spawn`` loop with sequential abort.
  We use ``monkeypatch`` to make the second entry fail deterministically without
  network or wt.exe.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import spawn_team
from spawn_team import _validate_manifest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora-ops"
MVC_TEMPLATE = PLUGIN_ROOT / "templates" / "team-mvc.json.example"


def _good_entry(**overrides) -> dict:
    e = {"id": "Coder1", "role": "coder", "description": "코딩 담당."}
    e.update(overrides)
    return e


def test_validate_manifest_valid() -> None:
    data = {
        "version": 1,
        "team": [
            _good_entry(id="Coder1"),
            _good_entry(id="Reviewer1", role="reviewer", description="리뷰 담당."),
            _good_entry(id="Tester1", role="tester", description="테스트 담당."),
        ],
    }
    cleaned, errors = _validate_manifest(data)
    assert errors == []
    assert len(cleaned) == 3
    assert [e["id"] for e in cleaned] == ["Coder1", "Reviewer1", "Tester1"]


def test_validate_manifest_wrong_version() -> None:
    data = {"version": 2, "team": [_good_entry()]}
    _, errors = _validate_manifest(data)
    assert errors
    assert any("version" in e for e in errors)


def test_validate_manifest_empty_team() -> None:
    data = {"version": 1, "team": []}
    cleaned, errors = _validate_manifest(data)
    assert cleaned == []
    assert errors
    assert any("team" in e for e in errors)


def test_validate_manifest_missing_required_keys() -> None:
    data = {
        "version": 1,
        "team": [
            _good_entry(),
            {"role": "reviewer", "description": "id 없음"},  # missing id
        ],
    }
    cleaned, errors = _validate_manifest(data)
    assert any("항목 1" in e and "필수 키" in e for e in errors)
    assert len(cleaned) == 1


def test_validate_manifest_bad_id_format() -> None:
    data = {"version": 1, "team": [_good_entry(id="bad id!")]}
    _, errors = _validate_manifest(data)
    assert any("id" in e for e in errors)


def test_validate_manifest_duplicate_id() -> None:
    data = {
        "version": 1,
        "team": [_good_entry(id="Coder1"), _good_entry(id="Coder1", description="중복")],
    }
    _, errors = _validate_manifest(data)
    assert any("중복" in e for e in errors)


def test_validate_manifest_invalid_root() -> None:
    cleaned, errors = _validate_manifest([1, 2, 3])
    assert cleaned == []
    assert errors
    assert any("객체" in e for e in errors)


def test_team_mvc_example_is_parseable() -> None:
    """team-mvc.json.example must be valid JSON and parse as a valid 3-entry manifest."""
    data = json.loads(MVC_TEMPLATE.read_text(encoding="utf-8"))
    cleaned, errors = _validate_manifest(data)
    assert errors == [], f"team-mvc.json.example validation errors: {errors}"
    assert len(cleaned) == 3


def test_team_mvc_example_has_expected_roles() -> None:
    data = json.loads(MVC_TEMPLATE.read_text(encoding="utf-8"))
    cleaned, _ = _validate_manifest(data)
    roles = [e["role"] for e in cleaned]
    assert roles == ["sp-model", "sp-view", "sp-controller"]


def test_team_mvc_example_has_expected_ids() -> None:
    data = json.loads(MVC_TEMPLATE.read_text(encoding="utf-8"))
    cleaned, _ = _validate_manifest(data)
    ids = [e["id"] for e in cleaned]
    assert ids == ["Model1", "View1", "Controller1"]


def test_validate_manifest_bad_entry_types() -> None:
    # role/description empty strings are rejected too.
    data = {
        "version": 1,
        "team": [_good_entry(role=""), _good_entry(id="X2", description="")],
    }
    _, errors = _validate_manifest(data)
    assert any("role" in e for e in errors)
    assert any("description" in e for e in errors)


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "team.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_spawn_team_all_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent = tmp_path / "team"
    parent.mkdir()
    manifest = _write_manifest(
        tmp_path,
        {
            "version": 1,
            "team": [
                _good_entry(id="Coder1"),
                _good_entry(id="Reviewer1", role="reviewer", description="리뷰."),
            ],
        },
    )
    # Pin target_dir to our tmp path so the cascade doesn't fall back to cwd.
    monkeypatch.setattr(spawn_team, "_resolve_target_dir", lambda **kw: parent)

    rc = spawn_team.main([str(manifest), "--launch=off"])
    assert rc == 0
    assert (parent / "Coder1" / ".mcp.json").is_file()
    assert (parent / "Reviewer1" / ".mcp.json").is_file()


def test_spawn_team_sequential_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent = tmp_path / "team"
    parent.mkdir()
    manifest = _write_manifest(
        tmp_path,
        {
            "version": 1,
            "team": [
                _good_entry(id="Ok1"),
                _good_entry(id="Bad1", role="coder", description="실패 유도용."),
                _good_entry(id="Skip1", role="coder", description="안 실행되어야 함."),
            ],
        },
    )
    monkeypatch.setattr(spawn_team, "_resolve_target_dir", lambda **kw: parent)

    # Patch do_spawn used by spawn_team so the second call deterministically
    # fails (rc=1) without touching disk for that entry, while letting other
    # entries fall through to the real implementation.
    real = spawn_team.do_spawn

    def fake_do_spawn(**kwargs):
        if kwargs["instance_id"] == "Bad1":
            print("[cc-agora] 강제 실패 (테스트).", file=__import__("sys").stderr)
            return 1
        return real(**kwargs)

    monkeypatch.setattr(spawn_team, "do_spawn", fake_do_spawn)

    rc = spawn_team.main([str(manifest), "--launch=off"])
    assert rc == 1
    # First entry created its dir; failing entry left no dir; third was skipped.
    assert (parent / "Ok1" / ".mcp.json").is_file()
    assert not (parent / "Bad1").exists()
    assert not (parent / "Skip1").exists()

    err = capsys.readouterr().err
    assert "실패 1건" in err or "실패" in err
    assert "Bad1" in err
    assert "Skip1" in err


def test_spawn_team_validation_aborts_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "team"
    parent.mkdir()
    manifest = _write_manifest(
        tmp_path,
        {
            "version": 1,
            "team": [_good_entry(id="Coder1"), _good_entry(id="Coder1")],
        },
    )
    monkeypatch.setattr(spawn_team, "_resolve_target_dir", lambda **kw: parent)

    rc = spawn_team.main([str(manifest), "--launch=off"])
    assert rc == 1
    # No directories created — validation aborts upfront.
    assert list(parent.iterdir()) == []
