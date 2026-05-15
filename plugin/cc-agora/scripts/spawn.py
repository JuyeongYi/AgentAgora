"""/agora-spawn implementation (spec §4.2).

Creates a worker directory with CLAUDE.md (preset prepended with description
header), .mcp.json (auto-register headers), and optionally
.claude/settings.local.json (a ``type:"prompt"`` Stop hook — no separate .py
file) when the role's hook policy is ``stop-auto-wait``.

Public surface: ``do_spawn`` (callable from spawn_team.py) and a CLI entry point.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from role_policy import (
    hook_for,
    is_defined,
    load_roles,
    preset_for,
    wait_mode_for,
    warn_undefined_role,
)

DEFAULT_SERVER_URL = "http://127.0.0.1:8420/mcp"
DEFAULT_WAIT_TIMEOUT_MS = 0
_SENTINEL_WAIT_MODE = "{{WAIT_MODE_HEADER_LINE}}"


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
    """Spec §4.2 step 2 — directory decision cascade.

    Returns the *parent* directory under which the worker dir will be created.
    """
    if dir_override:
        return Path(dir_override).resolve()
    agora_home = env.get("AGORA_HOME")
    if agora_home:
        return Path(os.path.expanduser(agora_home)).resolve()
    if (cwd / ".mcp.json").is_file():
        return cwd.parent
    # Fallback: cwd itself; warn so orchestrator notices if not intended.
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
    wait_timeout_ms: int,
    wait_mode: str | None,
) -> str:
    """Render mcp.json. Both the defined-role branch (sentinel replaced with a
    header line) and the undefined-role branch (sentinel + its trailing newline
    dropped entirely) are validated as valid JSON before return.
    """
    text = template
    text = text.replace("{{SERVER_URL}}", server_url)
    text = text.replace("{{INSTANCE_ID}}", instance_id)
    text = text.replace("{{ROLE}}", role)
    # JSON-encode the description body so quotes/backslashes/non-ASCII survive
    # safely; then strip the wrapping quotes the template already supplies.
    text = text.replace("{{DESCRIPTION}}", json.dumps(description, ensure_ascii=False)[1:-1])
    text = text.replace("{{WAIT_TIMEOUT_MS}}", str(wait_timeout_ms))

    if wait_mode is None:
        # Remove the sentinel line entirely (with its newline) so JSON stays valid.
        lines = text.splitlines(keepends=True)
        text = "".join(line for line in lines if _SENTINEL_WAIT_MODE not in line)
    else:
        header_line = f'"X-Agora-Wait-Mode": "{wait_mode}",'
        text = text.replace(_SENTINEL_WAIT_MODE, header_line)

    # Self-check: rendered output must parse. A failure here is a bug in the
    # template or this function, never user input.
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"rendered .mcp.json is not valid JSON (wait_mode={wait_mode!r}): {exc}"
        ) from exc
    return text


def _read_template(plugin_root: Path, *parts: str) -> str:
    path = plugin_root.joinpath(*parts)
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    """Write UTF-8 text without BOM and with LF newlines (forward-slash regime)."""
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
        f"`X-Agora-Description`, `X-Agora-Wait-Mode`)와 서버의 `AutoRegisterMiddleware`가 "
        f"첫 HTTP 요청에서 자동 처리한다. 해제는 idle timeout(디폴트 30분)으로 자동 sweep.\n"
        f"\n"
        f"따라서 다음을 **호출하지 마라**:\n"
        f"\n"
        f"- `agora.register` / `agora.unregister` (서버가 자동 처리)\n"
        f"- `CallToolRequest`, `tools/call`, `tools/list` 등 **MCP protocol-level 이름** "
        f"(이는 도구가 아니라 protocol message type이다 — 도구 호출은 도구 이름으로 직접)\n"
        f"\n"
        f"사용 가능한 도구는 `agora.*`로 시작하는 것들뿐이다: `agora.dispatch`, "
        f"`agora.broadcast`, `agora.wait`, `agora.instances`, `agora.find`, `agora.peek`, "
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
    wait_timeout_ms: int,
    plugin_root: Path,
    stderr=sys.stderr,
    stdout=sys.stdout,
    env: dict[str, str] | None = None,
) -> int:
    """Create a worker directory under ``target_dir/<instance_id>/``.

    Returns 0 on success, 1 on failure. Failure is reported to stderr in Korean.
    """
    _ = env  # currently unused, accepted for future expansion / test parity
    roles_path = plugin_root / "config" / "roles.json"
    roles = load_roles(roles_path)

    defined = is_defined(role, roles)
    hook = hook_for(role, roles) if defined else None
    wait_mode = wait_mode_for(role, roles) if defined else None
    if preset is not None:
        chosen_preset = preset
    elif defined:
        chosen_preset = preset_for(role, roles) or "general"
    else:
        chosen_preset = "general"

    if not defined:
        warn_undefined_role(role, stream=stderr)

    worker_dir = target_dir / instance_id
    if worker_dir.exists():
        if not force:
            print(
                f"[cc-agora] '{instance_id}/' 디렉토리가 이미 존재합니다. "
                f"--force로 덮어쓰기 가능.",
                file=stderr,
            )
            return 1
        # --force: leave the dir itself, overwrite the four files we manage.
    worker_dir.mkdir(parents=True, exist_ok=True)

    # 1. CLAUDE.md (always written).
    preset_path = plugin_root / "templates" / "presets" / f"{chosen_preset}.md"
    if not preset_path.is_file():
        print(
            f"[cc-agora] preset '{chosen_preset}' 파일을 찾을 수 없습니다: "
            f"{preset_path.as_posix()}",
            file=stderr,
        )
        return 1
    preset_body = preset_path.read_text(encoding="utf-8")
    claude_md = _render_claude_md(
        instance_id=instance_id,
        role=role,
        description=description,
        preset_body=preset_body,
    )
    _write_text(worker_dir / "CLAUDE.md", claude_md)

    # 2. .mcp.json (always written).
    mcp_template = _read_template(plugin_root, "templates", "mcp.json.template")
    mcp_rendered = _render_mcp_json(
        template=mcp_template,
        server_url=server_url,
        instance_id=instance_id,
        role=role,
        description=description,
        wait_timeout_ms=wait_timeout_ms,
        wait_mode=wait_mode,
    )
    _write_text(worker_dir / ".mcp.json", mcp_rendered)

    # 3. settings.local.json — only when hook=stop-auto-wait.
    # The Stop hook is type:"prompt" (inline prompt text), so no separate
    # .py file is written.
    if hook == "stop-auto-wait":
        settings_template = _read_template(
            plugin_root, "templates", "settings.local.json.template"
        )
        _write_text(worker_dir / ".claude" / "settings.local.json", settings_template)

    hook_label = hook if hook else "none"
    wait_label = wait_mode if wait_mode else "unknown"
    print(
        f"[cc-agora] '{instance_id}/' 생성 완료 "
        f"(role={role}, preset={chosen_preset}, hook={hook_label}, wait_mode={wait_label}). "
        f"시작: cd {instance_id} && claude",
        file=stdout,
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agora-spawn",
        description="Create an AgentAgora worker directory (spec §4.2).",
    )
    p.add_argument("id", help="Worker instance id (e.g. Coder1).")
    p.add_argument("role", help="Role name; looked up in config/roles.json.")
    p.add_argument("description", help="Worker description (Korean recommended).")
    p.add_argument(
        "--preset",
        default=None,
        help="Override preset name. Defaults to the role's preset; falls back to 'general' for undefined roles.",
    )
    p.add_argument(
        "--dir",
        dest="dir_override",
        default=None,
        help="Parent directory under which to create <id>/. See §4.2 cascade.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the four managed files inside an existing <id>/.",
    )
    p.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"MCP server URL (default: {DEFAULT_SERVER_URL}).",
    )
    p.add_argument(
        "--wait-timeout-ms",
        type=int,
        default=DEFAULT_WAIT_TIMEOUT_MS,
        help="X-Agora-Wait-Timeout-Ms header value (default: 0 = unbounded).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    plugin_root = _plugin_root()
    target_dir = _resolve_target_dir(
        dir_override=args.dir_override,
        cwd=Path.cwd(),
        env=os.environ.copy(),
    )
    return do_spawn(
        instance_id=args.id,
        role=args.role,
        description=args.description,
        preset=args.preset,
        target_dir=target_dir,
        force=args.force,
        server_url=args.server_url,
        wait_timeout_ms=args.wait_timeout_ms,
        plugin_root=plugin_root,
    )


if __name__ == "__main__":
    sys.exit(main())
