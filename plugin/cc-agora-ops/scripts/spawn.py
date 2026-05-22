"""/agora-spawn implementation — 채널 모드 워커 생성.

워커 디렉토리에 thin CLAUDE.md, .mcp.json(HTTP 서버 + agora-channel stdio 어댑터),
run.bat(채널 모드 기동), .claude/settings.local.json(워커별 페르소나 플러그인 활성화)을
만든다. 채널 모드 워커는 Stop hook이 없다.

Public surface: ``do_spawn`` (spawn_team.py가 호출) + CLI 진입점.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from role_policy import is_defined, load_roles, plugin_for, warn_undefined_role

DEFAULT_SERVER_URL = "http://127.0.0.1:8420/mcp"

# 채널 모드 워커 기동 스크립트. agora-channel은 공식 allowlist에 없는 자작
# 채널이라 --dangerously-load-development-channels 플래그가 필요하다.
_RUN_BAT = (
    "@echo off\n"
    "REM 채널 모드 워커 기동. agora-channel은 공식 allowlist에 없는 자작 채널이라\n"
    "REM --dangerously-load-development-channels 플래그가 필요하다.\n"
    "REM autoCompact 임계값을 60%로 낮춰 워커가 컨텍스트 wall 전에 자주 compact하게 한다.\n"
    "set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60\n"
    "REM 워커 이름 = run.bat 위치한 폴더 basename (instance_id와 일치).\n"
    "for %%I in (\"%~dp0.\") do set \"AGORA_NAME=%%~nxI\"\n"
    "claude --name \"%AGORA_NAME%\" --dangerously-load-development-channels server:agora-channel %*\n"
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
    cwd: str,
) -> str:
    """2-서버 채널 템플릿을 렌더링한다. 렌더 결과가 유효 JSON인지 self-check."""
    text = template
    text = text.replace("{{SERVER_URL}}", server_url)
    text = text.replace("{{INSTANCE_ID}}", instance_id)
    text = text.replace("{{ROLE}}", role)
    text = text.replace(
        "{{DESCRIPTION}}", json.dumps(description, ensure_ascii=False)[1:-1])
    text = text.replace("{{CWD}}", json.dumps(cwd, ensure_ascii=False)[1:-1])
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


def _render_thin_claude_md(*, instance_id: str, role: str, description: str) -> str:
    return (
        f"# {instance_id} ({role})\n"
        f"\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n"
        f"\n"
        f"## 페르소나\n"
        f"\n"
        f"본인의 역할 페르소나는 `cc-agora-{role}` 플러그인이 제공하는 `persona` 스킬에 "
        f"있다. 기동 시 그 스킬을 적용해 역할을 수행한다.\n"
        f"\n"
        f"## 통신\n"
        f"\n"
        f"채널 모드 메시징 규칙(`agora-protocol`)은 cc-agora가 배경지식으로 자동 "
        f"적용한다 — 직접 스킬로 호출하지 않는다. 채널 알림으로 깨어나 "
        f"`agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신한다. "
        f"등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/"
        f"`agora.unregister`를 호출하지 않는다.\n"
    )


def _render_custom_claude_md(*, instance_id: str, role: str, description: str) -> str:
    return (
        f"# {instance_id} ({role})\n"
        f"\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n"
        f"\n"
        f"## 페르소나\n"
        f"\n"
        f"역할 페르소나는 `.claude/CLAUDE.md`에 있다 — Claude Code가 프로젝트 "
        f"메모리로 자동 로드한다.\n"
        f"\n"
        f"## 통신\n"
        f"\n"
        f"채널 모드 메시징 규칙(`agora-protocol`)은 cc-agora가 배경지식으로 자동 "
        f"적용한다 — 직접 스킬로 호출하지 않는다. 채널 알림으로 깨어나 "
        f"`agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신한다. "
        f"등록·해제는 `.mcp.json` 헤더로 자동 처리되므로 `agora.register`/"
        f"`agora.unregister`를 호출하지 않는다.\n"
    )


def _render_settings_local(*, persona_plugin: str, marketplace_path: str) -> str:
    settings = {
        "extraKnownMarketplaces": {
            "agentagora": {"source": "directory", "path": marketplace_path}
        },
        "enabledPlugins": {
            f"{persona_plugin}@agentagora": True,
            # 모든 채널 워커는 cc-agora의 agora-protocol(운용 규칙)을 공유한다.
            # superpowers 트랙 페르소나는 cc-agora에 의존하지 않으므로 명시적으로 켠다.
            # persona_plugin == "cc-agora"이면 키가 합쳐져 중복되지 않는다.
            "cc-agora@agentagora": True,
        },
    }
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"


def do_spawn(
    *,
    instance_id: str,
    role: str,
    description: str,
    target_dir: Path,
    force: bool,
    server_url: str,
    plugin_root: Path,
    persona_body: str | None = None,
    stderr=sys.stderr,
    stdout=sys.stdout,
    env: dict[str, str] | None = None,
) -> int:
    """채널 모드 워커 디렉토리를 ``target_dir/<instance_id>/``에 만든다.

    ``persona_body``가 주어지면 커스텀 모드 — roles.json 조회를 건너뛰고
    페르소나를 ``.claude/CLAUDE.md``에 쓰며 ``cc-agora``만 활성화한다. 실행
    스크립트는 쓰지 않는다(agora-run-script 담당).

    0=성공, 1=실패. 실패는 한국어로 stderr에 보고한다.
    """
    _ = env  # 향후 확장·테스트 패리티용
    custom = persona_body is not None

    if custom:
        persona_plugin = "cc-agora"
    else:
        roles = load_roles(plugin_root / "config" / "roles.json")
        defined = is_defined(role, roles)
        persona_plugin = plugin_for(role, roles) if defined else None
        if persona_plugin is None:
            persona_plugin = "cc-agora-general"
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

    # 1. CLAUDE.md (루트 thin)
    if custom:
        _write_text(
            worker_dir / "CLAUDE.md",
            _render_custom_claude_md(
                instance_id=instance_id, role=role, description=description),
        )
        # 1b. .claude/CLAUDE.md — 커스텀 페르소나 (Claude Code가 자동 로드)
        _write_text(worker_dir / ".claude" / "CLAUDE.md", persona_body)
    else:
        _write_text(
            worker_dir / "CLAUDE.md",
            _render_thin_claude_md(
                instance_id=instance_id, role=role, description=description),
        )

    # 2. .mcp.json — HTTP 서버 + agora-channel stdio 어댑터 (불변)
    mcp_template = _read_template(plugin_root, "templates", "mcp.json.template")
    _write_text(
        worker_dir / ".mcp.json",
        _render_mcp_json(
            template=mcp_template, server_url=server_url,
            instance_id=instance_id, role=role, description=description,
            cwd=worker_dir.resolve().as_posix()),
    )

    # 3. run.bat — 비커스텀 모드만. 커스텀 모드 실행 스크립트는 agora-run-script.
    if not custom:
        _write_text(worker_dir / "run.bat", _RUN_BAT)

    # 4. .claude/settings.local.json — 페르소나 플러그인(커스텀이면 cc-agora) 활성화
    marketplace_path = plugin_root.parent.parent.as_posix()
    _write_text(
        worker_dir / ".claude" / "settings.local.json",
        _render_settings_local(
            persona_plugin=persona_plugin, marketplace_path=marketplace_path),
    )

    if custom:
        print(
            f"[cc-agora] '{instance_id}/' 생성 완료 "
            f"(role={role}, 커스텀 페르소나, 채널 모드). "
            f"실행 스크립트는 agora-run-script로 생성하라.",
            file=stdout,
        )
    else:
        print(
            f"[cc-agora] '{instance_id}/' 생성 완료 "
            f"(role={role}, persona={persona_plugin}, 채널 모드). "
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
    p.add_argument(
        "--persona-file",
        dest="persona_file",
        default=None,
        help="Path to a file holding the custom persona body. When given, "
             "spawn runs in custom mode: writes .claude/CLAUDE.md, enables "
             "cc-agora, and writes no run script.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    persona_body = None
    if args.persona_file is not None:
        persona_body = Path(args.persona_file).read_text(encoding="utf-8")
    return do_spawn(
        instance_id=args.id,
        role=args.role,
        description=args.description,
        target_dir=_resolve_target_dir(
            dir_override=args.dir_override,
            cwd=Path.cwd(),
            env=os.environ.copy(),
        ),
        force=args.force,
        server_url=args.server_url,
        plugin_root=_plugin_root(),
        persona_body=persona_body,
    )


if __name__ == "__main__":
    sys.exit(main())
