"""Pure-function unit tests for cc-agora-structure partition.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugin" / "cc-agora-structure" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from partition import partition_tree, slug  # noqa: E402


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


def test_remainder_merges_with_smallest_fitting_sibling():
    tree = {
        "name": "root", "path": "", "files": [
            {"path": "root.py", "weight": 2},  # remainder
        ],
        "subfolders": [
            {"name": "a", "path": "a",
             "files": [{"path": "a/x.py", "weight": 7}], "subfolders": []},
            {"name": "b", "path": "b",
             "files": [{"path": "b/y.py", "weight": 5}], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert warnings == []
    # Total weight = 14. Two subfolders 7,5; remainder 2 should merge with smallest (5 -> 7).
    assert len(parts) == 2
    merged = next(p for p in parts if "root.py" in p.files)
    assert merged.root == "b"
    assert merged.weight == 7
    assert set(merged.files) == {"b/y.py", "root.py"}


def test_remainder_emits_own_partition_when_no_sibling_fits():
    tree = {
        "name": "root", "path": "", "files": [
            {"path": "root.py", "weight": 3},
        ],
        "subfolders": [
            {"name": "a", "path": "a",
             "files": [{"path": "a/x.py", "weight": 9}], "subfolders": []},
            {"name": "b", "path": "b",
             "files": [{"path": "b/y.py", "weight": 9}], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert warnings == []
    # No sibling has room (9+3=12 > 10). Remainder gets own partition.
    assert len(parts) == 3
    own = next(p for p in parts if p.id.endswith("-loose"))
    assert own.weight == 3
    assert own.files == ("root.py",)


def test_oversize_loose_remainder_emits_with_warning():
    tree = {
        "name": "big", "path": "big", "files": [
            {"path": f"big/f{i}.py", "weight": 5} for i in range(10)
        ],
        "subfolders": [
            {"name": "sub", "path": "big/sub",
             "files": [{"path": "big/sub/q.py", "weight": 8}], "subfolders": []},
        ],
    }
    parts, warnings = partition_tree(tree, target_size=20)
    # subfolder: 8 <= 20 -> one partition.
    # loose: 50 > 20 -> own partition + warning.
    assert any("folder's loose files exceed target" in w for w in warnings)
    loose = next(p for p in parts if p.id.endswith("-loose"))
    assert loose.weight == 50


def test_slug_drops_non_ascii_and_normalizes():
    assert slug("src/agent_agora") == "src-agent-agora"
    assert slug("a/한글/b") == "a-b"
    assert slug("") == "root"
    assert slug("foo_bar-baz") == "foo-bar-baz"
    assert slug("/leading/slash") == "leading-slash"


def test_empty_tree_yields_no_partitions():
    tree = {"name": "root", "path": "", "files": [], "subfolders": []}
    parts, warnings = partition_tree(tree, target_size=10)
    assert parts == []
    assert warnings == []


def test_single_file_under_target():
    tree = {
        "name": "root", "path": "",
        "files": [{"path": "only.py", "weight": 4}],
        "subfolders": [],
    }
    parts, warnings = partition_tree(tree, target_size=10)
    assert len(parts) == 1
    assert parts[0].weight == 4
    assert parts[0].files == ("only.py",)


def test_target_size_must_be_positive():
    with pytest.raises(ValueError):
        partition_tree({"name": "root", "path": "", "files": [], "subfolders": []}, target_size=0)
