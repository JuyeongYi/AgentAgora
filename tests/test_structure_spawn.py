"""Tests for cc-agora-structure structure_spawn.py — manifest loading + validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugin" / "cc-agora-structure" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from structure_spawn import Manifest, PartitionSpec, load_manifest  # noqa: E402


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
