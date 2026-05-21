"""Pure-Python target-size folder tree partitioner.

Input: a folder tree with per-file weights. Output: a flat list of
partitions, each = one folder subtree (or a folder's loose-file remainder
or an oversize leaf), with weight <= target_size where possible.

No code-review-graph or filesystem dependency -- operates purely on the
tree JSON passed by the analyze slash command.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Partition:
    id: str
    root: str
    weight: int
    files: tuple[str, ...]


def slug(path: str) -> str:
    """Convert a forward-slash path to an ASCII id slug.

    "src/agent_agora" -> "src-agent-agora"
    "" -> "root"
    "a/hangul/b" -> "a-b"  (non-ASCII dropped, consecutive dashes collapsed)
    Underscores and slashes both normalize to dashes; non-ASCII characters
    are dropped (X-Agora-Description header is latin-1).
    """
    s = path.replace("/", "-").replace("\\", "-").replace("_", "-")
    out = "".join(
        c if (c.isascii() and (c.isalnum() or c == "-")) else "" for c in s
    )
    out = re.sub(r"-+", "-", out)
    return out.strip("-") or "root"


def _node_weight(node: dict) -> int:
    return (
        sum(f["weight"] for f in node["files"])
        + sum(_node_weight(s) for s in node["subfolders"])
    )


def _all_files(node: dict) -> list[str]:
    files = [f["path"] for f in node["files"]]
    for sub in node["subfolders"]:
        files.extend(_all_files(sub))
    return files


def partition_tree(tree: dict, target_size: int) -> tuple[list[Partition], list[str]]:
    """Partition the tree into a flat list, with per-partition weight <= target_size.

    Returns (partitions, warnings). Warnings are emitted for oversize leaves
    and oversize loose remainders.
    """
    if target_size <= 0:
        raise ValueError(f"target_size must be positive, got {target_size}")
    partitions: list[Partition] = []
    warnings: list[str] = []
    _partition_recurse(tree, target_size, partitions, warnings)
    return partitions, warnings


def _partition_recurse(
    node: dict,
    T: int,
    partitions: list[Partition],
    warnings: list[str],
) -> None:
    w = _node_weight(node)
    path = node["path"]

    if w == 0:
        return

    if w <= T:
        partitions.append(Partition(
            id=slug(path or "root"),
            root=path,
            weight=w,
            files=tuple(_all_files(node)),
        ))
        return

    # w > T
    if not node["subfolders"]:
        warnings.append(
            f"partition '{slug(path or 'root')}' weight {w} > target {T} "
            f"— leaf folder, cannot split further"
        )
        partitions.append(Partition(
            id=slug(path or "root"),
            root=path,
            weight=w,
            files=tuple(_all_files(node)),
        ))
        return

    # Has subfolders -- recurse first
    sub_start = len(partitions)
    for sub in node["subfolders"]:
        _partition_recurse(sub, T, partitions, warnings)

    # Handle this node's loose files (direct, not in subfolders)
    loose_files = [f["path"] for f in node["files"]]
    L = sum(f["weight"] for f in node["files"])
    if L == 0:
        return

    if L > T:
        warnings.append(
            f"partition '{slug(path or 'root')}-loose' weight {L} > target {T} "
            f"— folder's loose files exceed target"
        )
        partitions.append(Partition(
            id=slug(path or "root") + "-loose",
            root=path,
            weight=L,
            files=tuple(loose_files),
        ))
        return

    # L <= T -- try merging with smallest fitting sibling partition
    sub_partitions = partitions[sub_start:]
    fits = [(i, p) for i, p in enumerate(sub_partitions) if p.weight + L <= T]
    if fits:
        idx, smallest = min(fits, key=lambda x: x[1].weight)
        merged = Partition(
            id=smallest.id,
            root=smallest.root,
            weight=smallest.weight + L,
            files=smallest.files + tuple(loose_files),
        )
        partitions[sub_start + idx] = merged
    else:
        partitions.append(Partition(
            id=slug(path or "root") + "-loose",
            root=path,
            weight=L,
            files=tuple(loose_files),
        ))


def main() -> int:
    payload = json.load(sys.stdin)
    parts, warnings = partition_tree(payload["tree"], payload["target_size"])
    out = {
        "partitions": [asdict(p) for p in parts],
        "warnings": warnings,
    }
    json.dump(out, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
