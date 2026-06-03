"""워커 디렉터리 파일 생성 + 서버 기동 스크립트 + 마켓플레이스 탐색.

plugin/cc-agora-ops/scripts/spawn.py를 참고해 재작성. 채널 모드 4파일(CLAUDE.md,
.mcp.json, run.bat, .claude/settings.local.json)을 만든다. 템플릿은 패키지 동봉
(provisioning/templates/). 커스텀 페르소나/슬래시 경로는 비목표라 제외.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import roles as _roles

_TPL_DIR = Path(__file__).with_name("templates")

# 마켓플레이스 식별자(별칭). marketplace.json의 "name"과 일치시켜 `/plugin marketplace
# add`로 수동 등록한 경우(식별자=name)와 충돌하지 않게 한다. enabledPlugins의
# `<plugin>@<별칭>` 접미사가 이 키를 가리킨다.
MARKETPLACE_ALIAS = "agent-agora"


def _write_text(path: Path, content: str) -> None:
    """UTF-8(BOM 없음) + LF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def _write_bat(path: Path, content: str) -> None:
    """ASCII + CRLF(cmd.exe). content의 LF는 CRLF로 변환된다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\r\n") as fh:
        fh.write(content)


def find_marketplace() -> str | None:
    """이 패키지에서 위로 올라가며 plugin/.claude-plugin/marketplace.json을 찾는다.
    작업트리(소스 체크아웃)면 repo/plugin을 반환, 설치본이면 None(호출자가 입력 요구)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "plugin" / ".claude-plugin" / "marketplace.json"
        if cand.is_file():
            return (parent / "plugin").as_posix()
    return None


def _render_mcp_json(*, server_url: str, instance_id: str, role: str,
                     description: str, cwd: str) -> str:
    tpl = (_TPL_DIR / "mcp.json.template").read_text(encoding="utf-8")
    tpl = tpl.replace("{{SERVER_URL}}", server_url)
    tpl = tpl.replace("{{INSTANCE_ID}}", instance_id)
    tpl = tpl.replace("{{ROLE}}", role)
    tpl = tpl.replace("{{DESCRIPTION}}", json.dumps(description, ensure_ascii=False)[1:-1])
    tpl = tpl.replace("{{CWD}}", json.dumps(cwd, ensure_ascii=False)[1:-1])
    json.loads(tpl)  # self-check: 유효 JSON
    return tpl


def _render_claude_md(*, instance_id: str, role: str, description: str) -> str:
    return (
        f"# {instance_id} ({role})\n\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n\n"
        f"## 페르소나\n\n"
        f"역할 페르소나는 `cc-agora-{role}` 플러그인의 `persona` 스킬에 있다. 기동 시 적용한다.\n\n"
        f"## 통신\n\n"
        f"채널 모드 메시징 규칙(`agora-protocol`)은 cc-agora가 배경지식으로 자동 적용한다. "
        f"채널 알림으로 깨어나 `agora.flush`로 인박스를 드레인하고 `agora.dispatch`로 답신한다. "
        f"등록·해제는 `.mcp.json` 헤더로 자동 처리된다.\n"
    )


def _marketplace_source(marketplace: dict) -> dict:
    """marketplace({type:github,repo} 또는 {type:directory,path})를 Claude Code의
    extraKnownMarketplaces source 객체로 변환한다."""
    if marketplace["type"] == "github":
        return {"source": "github", "repo": marketplace["repo"]}
    return {"source": "directory", "path": marketplace["path"]}


def _render_settings_local(*, persona_plugin: str, marketplace: dict) -> str:
    settings = {
        "extraKnownMarketplaces": {
            MARKETPLACE_ALIAS: {"source": _marketplace_source(marketplace)}
        },
        "enabledPlugins": {
            f"{persona_plugin}@{MARKETPLACE_ALIAS}": True,
            f"cc-agora@{MARKETPLACE_ALIAS}": True,
        },
    }
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"


def spawn_worker(*, instance_id: str, role: str, description: str, parent_dir: Path,
                 server_url: str, marketplace: dict, force: bool,
                 stderr=sys.stderr, stdout=sys.stdout) -> int:
    """parent_dir/<instance_id>/에 채널 모드 워커 4파일 생성. 0=성공, 1=실패."""
    persona_plugin = _roles.plugin_for(role) or _roles.FALLBACK_PLUGIN
    if not _roles.is_defined(role):
        print(_roles.undefined_role_warning(role), file=stderr)

    wd = Path(parent_dir) / instance_id
    if wd.exists() and not force:
        print(f"[agora-init] '{instance_id}/' 이미 존재. --force로 덮어쓰기.", file=stderr)
        return 1
    wd.mkdir(parents=True, exist_ok=True)

    _write_text(wd / "CLAUDE.md",
                _render_claude_md(instance_id=instance_id, role=role, description=description))
    _write_text(wd / ".mcp.json",
                _render_mcp_json(server_url=server_url, instance_id=instance_id, role=role,
                                 description=description, cwd=wd.resolve().as_posix()))
    _write_bat(wd / "run.bat", (_TPL_DIR / "run.bat").read_text(encoding="ascii"))
    _write_text(wd / ".claude" / "settings.local.json",
                _render_settings_local(persona_plugin=persona_plugin,
                                        marketplace=marketplace))
    print(f"[agora-init] '{instance_id}/' 생성 (role={role}, persona={persona_plugin}).",
          file=stdout)
    return 0


def write_server_launcher(parent_dir: Path) -> None:
    """parent_dir/run-server.bat 생성(ASCII+CRLF)."""
    _write_bat(Path(parent_dir) / "run-server.bat",
               (_TPL_DIR / "run-server.bat").read_text(encoding="ascii"))
