"""/agora-structure-spawn implementation — read a structure manifest and
create per-partition staging dirs that launch channel-mode workers.

Workers create their own worktree+sparse-checkout on first task receipt
(via the superpowers using-git-worktrees skill); this script only writes
config files and launches.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PartitionSpec:
    id: str
    root: str
    weight: int
    files: tuple[str, ...]
    suggested_role: str
    coupling: tuple[dict, ...]


@dataclass(frozen=True)
class Manifest:
    version: int
    repo: str
    target_size: int
    partitions: tuple[PartitionSpec, ...]
    warnings: tuple[str, ...]


def load_manifest(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise ValueError(
            f"manifest version 1 required, got {data.get('version')!r}"
        )
    if not isinstance(data.get("repo"), str) or not data["repo"]:
        raise ValueError("manifest.repo must be a non-empty string")
    if (
        not isinstance(data.get("target_size"), int)
        or isinstance(data["target_size"], bool)
        or data["target_size"] <= 0
    ):
        raise ValueError("manifest.target_size must be a positive integer")
    if not isinstance(data.get("partitions"), list):
        raise ValueError("manifest.partitions must be a list")

    parts: list[PartitionSpec] = []
    for i, p in enumerate(data["partitions"]):
        for key in ("id", "root", "weight", "files", "suggested_role"):
            if key not in p:
                raise ValueError(f"partitions[{i}].{key} missing")
        if not isinstance(p["id"], str) or not p["id"] or not p["id"].isascii():
            raise ValueError(
                f"partitions[{i}].id must be a non-empty ASCII string"
            )
        if not isinstance(p["files"], list):
            raise ValueError(f"partitions[{i}].files must be a list")
        parts.append(PartitionSpec(
            id=p["id"],
            root=p["root"],
            weight=int(p["weight"]),
            files=tuple(p["files"]),
            suggested_role=p["suggested_role"],
            coupling=tuple(p.get("coupling", [])),
        ))

    return Manifest(
        version=int(data["version"]),
        repo=data["repo"],
        target_size=int(data["target_size"]),
        partitions=tuple(parts),
        warnings=tuple(data.get("warnings", [])),
    )
