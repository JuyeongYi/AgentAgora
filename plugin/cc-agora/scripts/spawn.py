"""/agora-spawn implementation — 채널 모드 워커 생성.

워커 디렉토리에 CLAUDE.md(preset에 description 헤더를 prepend), .mcp.json
(HTTP 서버 + agora-channel stdio 어댑터), run.bat(채널 모드 기동)을 만든다.
채널 모드 워커는 Stop hook이 없다.

Public surface: ``do_spawn`` (spawn_team.py가 호출) + CLI 진입점.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from role_policy import is_defined, load_roles, preset_for, warn_undefined_role

DEFAULT_SERVER_URL = "http://127.0.0.1:8420/mcp"

# 채널 모드 워커 기동 스크립트. agora-channel은 공식 allowlist에 없는 자작
# 채널이라 --dangerously-load-development-channels 플래그가 필요하다.
_RUN_BAT = (
    "@echo off\n"
    "REM 채널 모드 워커 기동. agora-channel은 공식 allowlist에 없는 자작 채널이라\n"
    "REM --dangerously-load-development-channels 플래그가 필요하다.\n"
    "claude --dangerously-load-development-channels server:agora-channel %*\n"
)


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_target_dir(
    *,
    dir_override: str | None,
    cwd: Path,
    env: dict[str, str],
    stderr=sys.stderr,
    stdout=sys.stdout,
) -> Path:
    """디렉토리 결정 캐스케이드 — 워커 디렉토리를 만들 *부모* 경로를 반환."""
    if dir_override:
        return Path(dir_override).resolve()
    agora_home = env.get("AGORA_HOME")
    if agora_home:
        return Path(os.path.expanduser(agora_home)).resolve()
    if (cwd / ".mcp.json").is_file():
        return cwd.parent
    resolved = cwd.resolve()
    print(
        f"[cc-agora] 경고: --dir 미지정 + AGORA_HOME 미설정 + 워커 디렉토리 아님. "
        f"cwd를 사용합니다: {resolved.as_posix()}",
        file=stderr,
    )
    print(f"[cc-agora] 생성 위치: {resolved.as_posix()}", file=stdout)
    return resolved


def _render_mcp_json(
    *,
    template: str,
    server_url: str,
    instance_id: str,
    role: str,
    description: str,
) -> str:
    """2-서버 채널 템플릿을 렌더링한다. 렌더 결과가 유효 JSON인지 self-check."""
    text = template
    text = text.replace("{{SERVER_URL}}", server_url)
    text = text.replace("{{INSTANCE_ID}}", instance_id)
    text = text.replace("{{ROLE}}", role)
    text = text.replace(
        "{{DESCRIPTION}}", json.dumps(description, ensure_ascii=False)[1:-1])
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"rendered .mcp.json is not valid JSON: {exc}") from exc
    return text


def _read_template(plugin_root: Path, *parts: str) -> str:
    return plugin_root.joinpath(*parts).read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    """UTF-8 (BOM 없음) + LF 줄바꿈으로 쓴다 (forward-slash 규약)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def _render_claude_md(
    *, instance_id: str, role: str, description: str, preset_body: str
) -> str:
    header = (
        f"# {instance_id} ({role})\n"
        f"\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n"
        f"\n"
        f"## 등록·해제 자동성 (호출 금지)\n"
        f"\n"
        f"본 워커의 등록은 `.mcp.json` 헤더(`X-Agora-Instance-Id`, `X-Agora-Role`, "
        f"`X-Agora-Description`)와 서버의 `AutoRegisterMiddleware`가 첫 HTTP 요청에서 "
        f"자동 처리한다. 해제는 idle timeout(디폴트 30분)으로 자동 sweep.\n"
        f"\n"
        f"본 워커는 **채널 모드**다 — `<channel source=\"agora-channel\">` 알림이 "
        f"도착하면 턴이 깨어난다. 그때 `agora.flush`로 메시지를 수신해 처리하고, "
        f"답신은 `agora.dispatch`로 보낸다.\n"
        f"\n"
        f"다음을 **호출하지 마라**:\n"
        f"\n"
        f"- `agora.register` / `agora.unregister` (서버가 자동 처리)\n"
        f"- `CallToolRequest`, `tools/call`, `tools/list` 등 **MCP protocol-level 이름** "
        f"(이는 도구가 아니라 protocol message type이다 — 도구 호출은 도구 이름으로 직접)\n"
        f"\n"
        f"사용 가능한 도구는 `agora.*`로 시작하는 것들뿐이다: `agora.dispatch`, "
        f"`agora.broadcast`, `agora.flush`, `agora.instances`, `agora.find`, `agora.peek`, "
        f"`agora.conversation_status`, `agora.conversations_list`, `agora.close_thread`, "
        f"`agora.info`.\n"
        f"\n"
        f"상세 페르소나는 아래 단락을 따른다.\n"
        f"\n"
        f"---\n"
        f"\n"
    )
    body = preset_body if preset_body.endswith("\n") else preset_body + "\n"
    return header + body


def do_spawn(
    *,
    instance_id: str,
    role: str,
    description: str,
    preset: str | None,
    target_dir: Path,
    force: bool,
    server_url: str,
    plugin_root: Path,
    stderr=sys.stderr,
    stdout=sys.stdout,
    env: dict[str, str] | None = None,
) -> int:
    """채널 모드 워커 디렉토리를 ``target_dir/<instance_id>/``에 만든다.

    0=성공, 1=실패. 실패는 한국어로 stderr에 보고한다.
    """
    _ = env  # 향후 확장·테스트 패리티용
    roles = load_roles(plugin_root / "config" / "roles.json")

    defined = is_defined(role, roles)
    if preset is not None:
        chosen_preset = preset
    elif defined:
        chosen_preset = preset_for(role, roles) or "general"
    else:
        chosen_preset = "general"

    if not defined:
        warn_undefined_role(role, stream=stderr)

    worker_dir = target_dir / instance_id
    if worker_dir.exists() and not force:
        print(
            f"[cc-agora] '{instance_id}/' 디렉토리가 이미 존재합니다. "
            f"--force로 덮어쓰기 가능.",
            file=stderr,
        )
        return 1
    worker_dir.mkdir(parents=True, exist_ok=True)

    # 1. CLAUDE.md
    preset_path = plugin_root / "templates" / "presets" / f"{chosen_preset}.md"
    if not preset_path.is_file():
        print(
            f"[cc-agora] preset '{chosen_preset}' 파일을 찾을 수 없습니다: "
            f"{preset_path.as_posix()}",
            file=stderr,
        )
        return 1
    preset_body = preset_path.read_text(encoding="utf-8")
    _write_text(
        worker_dir / "CLAUDE.md",
        _render_claude_md(
            instance_id=instance_id, role=role,
            description=description, preset_body=preset_body),
    )

    # 2. .mcp.json — HTTP 서버 + agora-channel stdio 어댑터
    mcp_template = _read_template(plugin_root, "templates", "mcp.json.template")
    _write_text(
        worker_dir / ".mcp.json",
        _render_mcp_json(
            template=mcp_template, server_url=server_url,
            instance_id=instance_id, role=role, description=description),
    )

    # 3. run.bat — 채널 모드 기동
    _write_text(worker_dir / "run.bat", _RUN_BAT)

    print(
        f"[cc-agora] '{instance_id}/' 생성 완료 "
        f"(role={role}, preset={chosen_preset}, 채널 모드). "
        f"시작: cd {instance_id} && run.bat",
        file=stdout,
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agora-spawn",
        description="Create a channel-mode AgentAgora worker directory.",
    )
    p.add_argument("id", help="Worker instance id (e.g. Coder1).")
    p.add_argument("role", help="Role name; looked up in config/roles.json.")
    p.add_argument("description", help="Worker description (Korean recommended).")
    p.add_argument(
        "--preset",
        default=None,
        help="Override preset name. Defaults to the role's preset; "
             "falls back to 'general' for undefined roles.",
    )
    p.add_argument(
        "--dir",
        dest="dir_override",
        default=None,
        help="Parent directory under which to create <id>/.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the managed files inside an existing <id>/.",
    )
    p.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"MCP server URL (default: {DEFAULT_SERVER_URL}).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    return do_spawn(
        instance_id=args.id,
        role=args.role,
        description=args.description,
        preset=args.preset,
        target_dir=_resolve_target_dir(
            dir_override=args.dir_override,
            cwd=Path.cwd(),
            env=os.environ.copy(),
        ),
        force=args.force,
        server_url=args.server_url,
        plugin_root=_plugin_root(),
    )


if __name__ == "__main__":
    sys.exit(main())
