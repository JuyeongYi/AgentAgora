"""워커 디렉터리 파일 생성 + 서버 기동 스크립트 + 마켓플레이스 탐색.

plugin/cc-agora-ops/scripts/spawn.py를 참고해 재작성. 채널 모드 4파일(CLAUDE.md,
.mcp.json, run.bat, .claude/settings.local.json)을 만든다. 템플릿은 패키지 동봉
(provisioning/templates/). 커스텀 페르소나/슬래시 경로는 비목표라 제외.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

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


def _render_claude_md(*, instance_id: str, role: str, description: str,
                      persona_plugin: str | None) -> str:
    if persona_plugin:
        persona = (f"역할 페르소나는 `{persona_plugin}` 플러그인의 `persona` 스킬에 있다. "
                   f"기동 시 적용한다.")
    else:
        persona = ("별도 페르소나 플러그인 없이 `cc-agora` 통신 코어만 사용한다. "
                   "위 역할·책임에 따라 직접 수행한다.")
    return (
        f"# {instance_id} ({role})\n\n"
        f"이 인스턴스는 **{instance_id}** 워커이다. 역할: **{role}**. 책임: {description}.\n\n"
        f"## 페르소나\n\n{persona}\n\n"
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


def _render_settings_local(*, persona_plugin: str | None, marketplace: dict) -> str:
    enabled: dict[str, bool] = {}
    if persona_plugin:
        enabled[f"{persona_plugin}@{MARKETPLACE_ALIAS}"] = True
    enabled[f"cc-agora@{MARKETPLACE_ALIAS}"] = True
    settings = {
        "extraKnownMarketplaces": {
            MARKETPLACE_ALIAS: {"source": _marketplace_source(marketplace)}
        },
        "enabledPlugins": enabled,
    }
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"


def spawn_worker(*, instance_id: str, role: str, description: str, parent_dir: Path,
                 server_url: str, marketplace: dict, force: bool,
                 persona: str | None = None, platform: str | None = None,
                 stderr=sys.stderr, stdout=sys.stdout) -> int:
    """parent_dir/<instance_id>/에 채널 모드 워커 파일 생성. 0=성공, 1=실패.

    실행 스크립트는 platform(기본 sys.platform)에 따라 win32면 run.bat(ASCII+CRLF),
    그 외(리눅스/맥)면 run.sh(LF + 실행권한)를 만든다. 서버 기동 스크립트는 만들지
    않는다 — agora-init은 에이전트 스폰 전용이고 서버는 `agent-agora`로 따로 띄운다.

    persona="none"이면 역할 페르소나 플러그인 없이 cc-agora(통신 코어)만 활성화한다."""
    if persona == "none":
        persona_plugin = None
    else:
        persona_plugin = _roles.plugin_for(role) or _roles.FALLBACK_PLUGIN
        if not _roles.is_defined(role):
            print(_roles.undefined_role_warning(role), file=stderr)

    wd = Path(parent_dir) / instance_id
    if wd.exists() and not force:
        print(f"[agora-init] '{instance_id}/' 이미 존재. --force로 덮어쓰기.", file=stderr)
        return 1
    wd.mkdir(parents=True, exist_ok=True)

    _write_text(wd / "CLAUDE.md",
                _render_claude_md(instance_id=instance_id, role=role, description=description,
                                  persona_plugin=persona_plugin))
    _write_text(wd / ".mcp.json",
                _render_mcp_json(server_url=server_url, instance_id=instance_id, role=role,
                                 description=description, cwd=wd.resolve().as_posix()))
    plat = platform or sys.platform
    if plat == "win32":
        _write_bat(wd / "run.bat", (_TPL_DIR / "run.bat").read_text(encoding="ascii"))
    else:
        sh = wd / "run.sh"
        _write_text(sh, (_TPL_DIR / "run.sh").read_text(encoding="utf-8"))
        try:
            sh.chmod(0o755)
        except OSError:
            pass
    _write_text(wd / ".claude" / "settings.local.json",
                _render_settings_local(persona_plugin=persona_plugin,
                                        marketplace=marketplace))
    print(f"[agora-init] '{instance_id}/' 생성 (role={role}, persona={persona_plugin}).",
          file=stdout)
    return 0


def _server_url_parts(server_url: str) -> tuple[str, str]:
    """server_url → (port, bind_opt). 호스트가 로컬(127.0.0.1/localhost)이 아니면
    bind_opt='--bind-host 0.0.0.0'(전 인터페이스, 분산 셋업), 로컬이면 ''(기본 127.0.0.1)."""
    u = urlparse(server_url)
    port = str(u.port or 8420)
    host = u.hostname or "127.0.0.1"
    bind_opt = "" if host in ("127.0.0.1", "localhost") else "--bind-host 0.0.0.0"
    return port, bind_opt


def _render_launcher(template_name: str, server_url: str) -> str:
    """런처 템플릿의 {{PORT}}·{{BIND_OPT}}를 server_url 기준으로 치환."""
    port, bind_opt = _server_url_parts(server_url)
    enc = "ascii" if template_name.endswith((".bat", ".ps1")) else "utf-8"
    text = (_TPL_DIR / template_name).read_text(encoding=enc)
    return text.replace("{{PORT}}", port).replace("{{BIND_OPT}}", bind_opt)


def write_server_launcher(parent_dir: Path,
                          server_url: str = "http://127.0.0.1:8420/mcp",
                          platform: str | None = None) -> None:
    """parent_dir에 서버 기동 스크립트 생성. agora-init은 서버를 직접 띄우지 않고 이
    스크립트만 만든다. server_url의 호스트가 비-로컬이면 --bind-host 0.0.0.0을, 포트도
    server_url에서 가져온다(분산 셋업). win32→run-server.bat(CRLF), POSIX→run-server.sh."""
    plat = platform or sys.platform
    if plat == "win32":
        _write_bat(Path(parent_dir) / "run-server.bat",
                   _render_launcher("run-server.bat", server_url))
    else:
        sh = Path(parent_dir) / "run-server.sh"
        _write_text(sh, _render_launcher("run-server.sh", server_url))
        try:
            sh.chmod(0o755)
        except OSError:
            pass


def write_run_all(parent_dir: Path,
                  server_url: str = "http://127.0.0.1:8420/mcp",
                  platform: str | None = None) -> None:
    """parent_dir에 전체 실행 스크립트 생성. 서버 기동 → 포트 대기 → `.mcp.json`이 있는
    하위 워커 순차 기동. Windows는 run-all.ps1(wt.exe 탭/새 창), POSIX는 run-all.sh
    (zellij 전용 — zellij 세션 안에서 각 워커를 새 탭으로). 비-로컬 server_url이면 서버에
    --bind-host 0.0.0.0."""
    plat = platform or sys.platform
    if plat == "win32":
        _write_bat(Path(parent_dir) / "run-all.ps1",
                   _render_launcher("run-all.ps1", server_url))
    else:
        sh = Path(parent_dir) / "run-all.sh"
        _write_text(sh, _render_launcher("run-all.sh", server_url))
        try:
            sh.chmod(0o755)
        except OSError:
            pass
