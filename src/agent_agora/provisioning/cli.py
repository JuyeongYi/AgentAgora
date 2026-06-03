"""agora-init — 사람이 직접 실행하는 팀 워커 + 통신 매트릭스 최초 부트스트랩.

인자 없이 실행하면 대화형(프롬프트), --manifest <file>이면 비대화형(그대로 생성).
산출: 각 워커 디렉터리 4파일 + spawn_dir/team.json + .agentagora/comm-matrix.csv
+ run-server.bat (+ 서버 가동 & AGORA_ADMIN_TOKEN 있으면 매트릭스 POST).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import manifest as _manifest
from . import matrix as _matrix
from . import roles as _roles
from . import spawn as _spawn


def _generate(norm: dict, *, stdout=sys.stdout, stderr=sys.stderr) -> int:
    """정규화 manifest로 모든 산출물을 만든다. 0=성공."""
    for w in norm.get("warnings", []):
        print(w, file=stderr)

    spawn_dir = Path(norm["spawn_dir"]).resolve()
    spawn_dir.mkdir(parents=True, exist_ok=True)
    server_url = norm["server_url"]
    marketplace = norm.get("marketplace_path") or _spawn.find_marketplace()
    if not marketplace:
        print("[agora-init] 마켓플레이스(plugin) 경로를 결정할 수 없습니다. "
              "manifest의 marketplace_path를 지정하세요.", file=stderr)
        return 1

    # 1) 워커들
    for e in norm["team"]:
        rc = _spawn.spawn_worker(
            instance_id=e["id"], role=e["role"], description=e["description"],
            parent_dir=spawn_dir, server_url=server_url,
            marketplace_path=marketplace, force=True, stdout=stdout, stderr=stderr)
        if rc != 0:
            return rc

    # 2) team.json 보존(해석된 절대 경로로)
    norm = {**norm, "spawn_dir": spawn_dir.as_posix(), "marketplace_path": marketplace}
    _spawn._write_text(spawn_dir / "team.json", _manifest.dumps(norm))

    # 3) comm-matrix.csv
    csv = _matrix.build_csv(norm["team"])
    _spawn._write_text(spawn_dir / ".agentagora" / "comm-matrix.csv", csv)

    # 4) run-server.bat
    _spawn.write_server_launcher(spawn_dir)

    # 5) 서버 가동 중 & 토큰 있으면 매트릭스 즉시 적용
    token = os.environ.get("AGORA_ADMIN_TOKEN")
    if token:
        try:
            status = _matrix.post_to_server(server_url, csv, token)
            print(f"[agora-init] 매트릭스 POST 적용(status={status}).", file=stdout)
        except Exception as exc:  # noqa: BLE001 — 서버 미가동은 치명적이지 않음
            print(f"[agora-init] 매트릭스 즉시 적용 실패(파일은 생성됨): {exc}", file=stderr)

    print(f"[agora-init] 완료 — {len(norm['team'])}개 워커, 위치: {spawn_dir.as_posix()}",
          file=stdout)
    return 0


def _interactive(stdin=sys.stdin, stdout=sys.stdout) -> dict:
    """프롬프트로 manifest dict(미검증)를 만든다."""
    def ask(prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        print(f"{prompt}{suffix}: ", end="", file=stdout, flush=True)
        line = stdin.readline()
        if line == "":  # EOF
            return default
        line = line.strip()
        return line or default

    spawn_dir = ask("스폰 위치(부모 디렉터리)", Path.cwd().as_posix())
    server_url = ask("서버 URL", _manifest.DEFAULT_SERVER_URL)
    default_mkt = _spawn.find_marketplace() or ""
    marketplace = ask("마켓플레이스(plugin) 경로", default_mkt)
    print(f"  사용 가능 role: {', '.join(sorted(_roles.ROLES))}", file=stdout)

    team = []
    while True:
        iid = ask("워커 id(빈칸이면 종료)")
        if not iid:
            break
        role = ask("  role", "general")
        desc = ask("  description", iid)
        allow_raw = ask("  allow(쉼표구분 id/정규식; 빈칸=없음, *=전체)")
        allow = [t.strip() for t in allow_raw.split(",") if t.strip()]
        team.append({"id": iid, "role": role, "description": desc, "allow": allow})
        if ask("워커 더 추가? (y/n)", "y").lower() != "y":
            break

    return {"version": 1, "spawn_dir": spawn_dir, "server_url": server_url,
            "marketplace_path": marketplace or None, "team": team}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="agora-init",
        description="팀 워커 + 통신 매트릭스 최초 부트스트랩(사용자 직접 실행).")
    p.add_argument("--manifest", help="기존 team.json 경로(주면 비대화형).")
    args = p.parse_args(argv)

    if args.manifest:
        norm, errors = _manifest.load(Path(args.manifest))
    else:
        norm, errors = _manifest.validate(_interactive())

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return _generate(norm)


if __name__ == "__main__":
    sys.exit(main())
