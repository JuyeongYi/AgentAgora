"""Pure-function unit tests for cc-agora-structure partition.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugin" / "cc-agora-structure" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from partition import Partition, partition_tree, slug  # noqa: E402


def _leaf(name: str, weight: int) -> dict:
    return {"name": name, "path": name, "files": [{"path": name, "weight": weight}], "subfolders": []}


def test_balanced_split_each_subfolder_under_target():
    tree = {
        "name": "root", "path": "", "files": [],
        "subfolders": [
            {"name": "a", "path": "a", "files": [
                {"path": "a/x.py", "weight": 3},
                {"path": "a/y.py", "weight": 4},
            ], "subfolders": []},
            {"name": "b", "path": "b", "files": [
                {"path": "b/z.py", "weight": 5},
            ], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert len(parts) == 2
    assert warnings == []
    roots = sorted(p.root for p in parts)
    assert roots == ["a", "b"]
    assert all(p.weight <= 10 for p in parts)


def test_oversize_leaf_emits_with_warning():
    tree = {
        "name": "huge", "path": "huge",
        "files": [{"path": f"huge/f{i}.py", "weight": 50} for i in range(5)],
        "subfolders": [],
    }
    parts, warnings = partition_tree(tree, target_size=80)
    assert len(parts) == 1
    p = parts[0]
    assert p.root == "huge"
    assert p.weight == 250
    assert len(warnings) == 1
    assert "leaf folder, cannot split further" in warnings[0]
    assert "huge" in warnings[0]
