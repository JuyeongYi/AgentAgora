"""/agora-spawn-team implementation (spec §4.8).

Loads a manifest, validates it, then sequentially invokes ``do_spawn`` from
spawn.py for each entry. On the first failure, remaining entries are skipped
and reported (sequential abort, no rollback).

``--launch=auto`` opens a Windows Terminal tab per worker (``wt.exe -w 0
new-tab -d <abs_path> run.bat``). Falls back to manual messaging if wt.exe is
missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from spawn import (
    DEFAULT_SERVER_URL,
    _plugin_root,
    _resolve_target_dir,
    do_spawn,
)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_LAUNCH_MODES = ("off", "manual", "auto")


def _validate_manifest(data: object) -> tuple[list[dict], list[str]]:
    """Return (team_entries, errors). Errors are human-readable Korean lines."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [], ["[cc-agora] manifest 루트는 JSON 객체여야 합니다."]
    version = data.get("version")
    if version != 1:
        errors.append(
            f"[cc-agora] manifest version은 1이어야 합니다 (현재: {version!r})."
        )
    team = data.get("team")
    if not isinstance(team, list) or not team:
        errors.append("[cc-agora] manifest.team은 비어있지 않은 배열이어야 합니다.")
        return [], errors

    seen_ids: set[str] = set()
    cleaned: list[dict] = []
    for idx, entry in enumerate(team):
        if not isinstance(entry, dict):
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: 객체가 아님."
            )
            continue
        missing = [k for k in ("id", "role", "description") if k not in entry]
        if missing:
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: 필수 키 누락 {missing}."
            )
            continue
        instance_id = entry["id"]
        if not isinstance(instance_id, str) or not _ID_RE.match(instance_id):
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: id '{instance_id!r}'는 "
                f"^[A-Za-z0-9_-]{{1,32}}$ 형식을 만족해야 합니다."
            )
            continue
        if instance_id in seen_ids:
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: id '{instance_id}' 중복."
            )
            continue
        role = entry.get("role")
        description = entry.get("description")
        if not isinstance(role, str) or not role:
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: role은 비어있지 않은 문자열."
            )
            continue
        if not isinstance(description, str) or not description:
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: description은 비어있지 않은 문자열."
            )
            continue
        preset = entry.get("preset")
        if preset is not None and (not isinstance(preset, str) or not preset):
            errors.append(
                f"[cc-agora] manifest 항목 {idx} 검증 실패: preset은 문자열이어야 합니다."
            )
            continue
        seen_ids.add(instance_id)
        cleaned.append(
            {
                "id": instance_id,
                "role": role,
                "description": description,
                "preset": preset,
            }
        )
    return cleaned, errors


def _launch_auto(worker_dir: Path, *, stderr=sys.stderr) -> bool:
    """Open a Windows Terminal tab running ``run.bat`` in worker_dir.

    Returns True on success (wt.exe spawn launched), False if wt.exe is absent.
    Spec §4.8 step 5: ``wt.exe -w 0 new-tab -d <abs> run.bat``.
    """
    wt = shutil.which("wt.exe")
    if wt is None:
        return False
    abs_path = worker_dir.resolve().as_posix()
    # WHY -w 0: route to the current Windows Terminal window; spec §4.8 step 5.
    subprocess.Popen([wt, "-w", "0", "new-tab", "-d", abs_path, "run.bat"])
    return True


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agora-spawn-team",
        description="Spawn multiple AgentAgora workers from a manifest (spec §4.8).",
    )
    p.add_argument("manifest", help="Path to manifest JSON file.")
    p.add_argument(
        "--dir",
        dest="dir_override",
        default=None,
        help="Parent directory under which to create each <id>/.",
    )
    p.add_argument(
        "--launch",
        choices=_LAUNCH_MODES,
        default="off",
        help="off=no hint, manual=print start instructions, auto=open wt.exe tab.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Pass --force through to each spawn.",
    )
    p.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"MCP server URL (default: {DEFAULT_SERVER_URL}).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print(
            f"[cc-agora] manifest 파일을 찾을 수 없습니다: {manifest_path.as_posix()}",
            file=sys.stderr,
        )
        return 1
    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"[cc-agora] manifest JSON 파싱 실패: {exc}",
            file=sys.stderr,
        )
        return 1

    team, errors = _validate_manifest(data)
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    plugin_root = _plugin_root()
    target_dir = _resolve_target_dir(
        dir_override=args.dir_override,
        cwd=Path.cwd(),
        env=os.environ.copy(),
    )

    launch_mode = args.launch
    if launch_mode == "auto" and shutil.which("wt.exe") is None:
        print(
            "[cc-agora] wt.exe를 찾을 수 없어 --launch=auto를 manual로 강등합니다.",
            file=sys.stderr,
        )
        launch_mode = "manual"

    succeeded: list[str] = []
    failed_id: str | None = None
    remaining: list[str] = []

    for idx, entry in enumerate(team):
        rc = do_spawn(
            instance_id=entry["id"],
            role=entry["role"],
            description=entry["description"],
            target_dir=target_dir,
            force=args.force,
            server_url=args.server_url,
            plugin_root=plugin_root,
        )
        if rc != 0:
            failed_id = entry["id"]
            remaining = [e["id"] for e in team[idx + 1:]]
            break
        succeeded.append(entry["id"])
        worker_dir = target_dir / entry["id"]
        if launch_mode == "manual":
            print(
                f"[cc-agora] {entry['id']}/에서 run.bat 실행 필요: "
                f"cd {worker_dir.as_posix()} && run.bat",
            )
        elif launch_mode == "auto":
            ok = _launch_auto(worker_dir)
            if not ok:
                # Re-check in case wt.exe vanished mid-loop; degrade for this entry.
                print(
                    f"[cc-agora] {entry['id']}: wt.exe 호출 실패. 수동 실행: "
                    f"cd {worker_dir.as_posix()} && run.bat",
                    file=sys.stderr,
                )

    if failed_id is None:
        print(
            f"[cc-agora] spawn 성공 {len(succeeded)}건. "
            f"시작: 각 디렉토리에서 'run.bat' 또는 --launch=auto."
        )
        return 0

    remaining_str = ", ".join(remaining) if remaining else "(없음)"
    print(
        f"[cc-agora] spawn 성공 {len(succeeded)}건 / 실패 1건. "
        f"실패 항목: {failed_id}. 나머지 미수행: {remaining_str}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
