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

# ---------------------------------------------------------------------------
# Role -> persona plugin mapping mirrors cc-agora-ops/scripts/role_policy.py.
# Kept inline here to avoid cross-plugin imports; if missing, fall back to general.
# ---------------------------------------------------------------------------
_DEFAULT_PERSONA_PLUGINS = {
    "implementer": "cc-agora-implementer",
    "planner": "cc-agora-planner",
    "router": "cc-agora-router",
    "reviewer": "cc-agora-reviewer",
    "tester": "cc-agora-tester",
    "debugger": "cc-agora-debugger",
    "improver": "cc-agora-improver",
    "general": "cc-agora-general",
    "coder": "cc-agora-coder",
    "writer": "cc-agora-writer",
    "orchestrator": "cc-agora-orchestrator",
}


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


# ---------------------------------------------------------------------------
# Staging directory rendering
# ---------------------------------------------------------------------------


def _ascii_only(s: str) -> bool:
    return s.isascii()


def _persona_plugin_for(role: str) -> str:
    return _DEFAULT_PERSONA_PLUGINS.get(role, "cc-agora-general")


def _render_template(template_path: Path, mapping: dict[str, str]) -> str:
    text = template_path.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _files_markdown_list(files: tuple[str, ...]) -> str:
    return "\n".join(f"- `{f}`" for f in files)


def render_staging(
    *,
    partition: PartitionSpec,
    staging_dir: Path,
    worktree_path: Path,
    repo_path: Path,
    server_url: str,
    marketplace_path: str,
    templates_dir: Path,
) -> None:
    """Render one partition's staging directory.

    Writes CLAUDE.md, .mcp.json (3 servers), .claude/settings.local.json
    (permission whitelist), and run.bat (channel mode). Does NOT create
    the worktree — the worker does that on first task receipt.
    """
    description = f"Partition {partition.id} at {partition.root}"
    if not _ascii_only(description):
        raise ValueError(
            f"X-Agora-Description must be ASCII; got {description!r}"
        )

    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / ".claude").mkdir(exist_ok=True)

    instance_id = partition.id
    role = partition.suggested_role
    persona_plugin = _persona_plugin_for(role)

    common = {
        "INSTANCE_ID": instance_id,
        "ROLE": role,
        "DESCRIPTION": description,
        "PARTITION_ID": partition.id,
        "PARTITION_ROOT": partition.root,
        "PARTITION_FILES": _files_markdown_list(partition.files),
        "WORKTREE_PATH": worktree_path.as_posix(),
        "REPO_PATH": repo_path.as_posix(),
        "SERVER_URL": server_url,
        "CWD": staging_dir.resolve().as_posix(),
        "MARKETPLACE_PATH": marketplace_path.replace("\\", "/"),
        "PERSONA_PLUGIN": persona_plugin,
        "STAGING_GLOB": staging_dir.resolve().as_posix() + "/**",
        "WORKTREE_GLOB": worktree_path.as_posix() + "/**",
    }

    # CLAUDE.md
    claude_md = _render_template(templates_dir / "worker-claude.md.template", common)
    (staging_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8", newline="\n")

    # .mcp.json
    mcp_content = _render_template(templates_dir / "worker-mcp.json.template", common)
    json.loads(mcp_content)  # self-check
    (staging_dir / ".mcp.json").write_text(mcp_content, encoding="utf-8", newline="\n")

    # settings.local.json
    settings_content = _render_template(
        templates_dir / "worker-settings.local.json.template", common
    )
    json.loads(settings_content)  # self-check
    (staging_dir / ".claude" / "settings.local.json").write_text(
        settings_content, encoding="utf-8", newline="\n"
    )

    # run.bat — channel mode (matches cc-agora-ops convention)
    run_bat = (
        "@echo off\r\n"
        "REM Channel-mode worker. agora-channel needs the development-channels flag.\r\n"
        "claude --dangerously-load-development-channels server:agora-channel %*\r\n"
    )
    (staging_dir / "run.bat").write_text(run_bat, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# Orchestration: spawn() iterates partitions and optionally launches
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL = "http://127.0.0.1:8420/mcp"


def spawn(
    *,
    manifest: Manifest,
    out: Path,
    worktree_base: Path,
    server_url: str,
    launch: str,
    templates_dir: Path,
    marketplace_path: str,
    force: bool,
) -> list[Path]:
    """Create staging dirs for all non-empty partitions and optionally launch.

    Returns the list of created staging dirs (in manifest order, skipped
    partitions excluded).
    """
    staging_dirs: list[Path] = []
    repo = Path(manifest.repo)

    for partition in manifest.partitions:
        if not partition.files:
            print(
                f"[cc-agora-structure] partition {partition.id!r} has no files — skipping",
                file=sys.stderr,
            )
            continue

        staging_dir = out / partition.id
        worktree_path = worktree_base / partition.id

        if staging_dir.exists() and not force:
            raise FileExistsError(
                f"staging dir already exists: {staging_dir} (use --force to overwrite)"
            )
        if worktree_path.exists() and not force:
            print(
                f"[cc-agora-structure] warning: worktree reserved path "
                f"{worktree_path} already exists — worker may fail to create worktree",
                file=sys.stderr,
            )

        render_staging(
            partition=partition,
            staging_dir=staging_dir,
            worktree_path=worktree_path,
            repo_path=repo,
            server_url=server_url,
            marketplace_path=marketplace_path,
            templates_dir=templates_dir,
        )
        staging_dirs.append(staging_dir)

    if launch == "manual":
        print("# Launch commands:")
        for d in staging_dirs:
            print(f'wt.exe -d "{d}" cmd /k run.bat')
    elif launch == "auto":
        _launch_auto(staging_dirs)
    # launch == "off" — silent

    return staging_dirs


def _launch_auto(staging_dirs: list[Path]) -> None:
    """Open wt.exe tabs for each staging dir."""
    import subprocess
    if not staging_dirs:
        return
    args = ["wt.exe"]
    for i, d in enumerate(staging_dirs):
        if i > 0:
            args.append(";")
            args.append("new-tab")
        args += ["-d", str(d), "cmd", "/k", "run.bat"]
    subprocess.Popen(args)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agora-structure-spawn",
        description="Spawn channel-mode workers per structure-manifest partition.",
    )
    p.add_argument("--manifest", required=True, type=Path,
                   help="Path to structure-manifest.json")
    p.add_argument("--out", type=Path, default=None,
                   help="Staging-dir parent (default: <repo>/.agora-structure/workers)")
    p.add_argument("--worktree-base", type=Path, default=None,
                   help="Reserved worktree base (default: <repo-parent>/<repo>.structure-worktrees)")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL,
                   help=f"MCP server URL (default: {DEFAULT_SERVER_URL})")
    p.add_argument("--launch", choices=["off", "manual", "auto"], default="manual",
                   help="Launch mode: 'off' (no launch), 'manual' (print wt.exe commands), 'auto' (Popen wt.exe). Default: manual.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing staging dirs")
    return p


def main(argv: list[str] | None = None) -> int:
    # Exit codes:
    #   0 — success
    #   1 — bad manifest or staging-dir collision (use --force to overwrite)
    #   2 — repo is not a git repo
    args = _build_arg_parser().parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[cc-agora-structure] error: bad manifest: {e}", file=sys.stderr)
        return 1
    repo = Path(manifest.repo)

    if not (repo / ".git").exists():
        print(
            f"[cc-agora-structure] error: {repo} is not a git repo — "
            "workers cannot create worktrees",
            file=sys.stderr,
        )
        return 2

    out = args.out or (repo / ".agora-structure" / "workers")
    worktree_base = args.worktree_base or (
        repo.parent / f"{repo.name}.structure-worktrees"
    )

    if manifest.warnings:
        print("# Manifest warnings:", file=sys.stderr)
        for w in manifest.warnings:
            print(f"  - {w}", file=sys.stderr)

    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    marketplace_path = Path(__file__).resolve().parent.parent.parent.as_posix()

    try:
        staging_dirs = spawn(
            manifest=manifest,
            out=out,
            worktree_base=worktree_base,
            server_url=args.server_url,
            launch=args.launch,
            templates_dir=templates_dir,
            marketplace_path=marketplace_path,
            force=args.force,
        )
    except FileExistsError as e:
        print(f"[cc-agora-structure] error: {e}", file=sys.stderr)
        return 1

    print(f"[cc-agora-structure] created {len(staging_dirs)} staging dirs under {out.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
