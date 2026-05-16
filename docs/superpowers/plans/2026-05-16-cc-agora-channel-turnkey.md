# cc-agora 채널 모드 turnkey 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cc-agora 플러그인을 채널 전용으로 전환한다 — `/cc-agora:agora-spawn`이 채널 모드 워커의 완전한 묶음(`.mcp.json` 2-서버, `run.bat`, Stop hook 없음)을 찍어내고, 폴링 셋업 plumbing(Stop hook 템플릿·역할별 hook·`agora-wait`/`unwait`/`rewait` 스킬)은 제거한다.

**Architecture:** `roles.json`은 역할→preset만 유지(hook/wait_mode 제거). `mcp.json.template`은 HTTP 서버 + `agora-channel` stdio 어댑터 2개로. `spawn.py`/`spawn_team.py`는 채널 모드 묶음을 생성하고 `run.bat`(`--dangerously-load-development-channels` 기동)을 찍는다. 모든 워커가 instance ID만 다른 균일 구성.

**Tech Stack:** Python 3.13, pytest. spec: `docs/superpowers/specs/2026-05-16-cc-agora-channel-turnkey-design.md`.

**전제:**
- 선행 plan `2026-05-16-agora-channel-script.md`가 먼저 머지돼야 한다 — `.mcp.json` 템플릿이 `command: "agora-channel"` 콘솔 스크립트를 참조한다.
- 큰 변경이므로 별도 브랜치/worktree에서 실행.
- 테스트 인터프리터는 저장소 `.venv`(Python 3.13). 기본 `python`은 3.12라 `agent_agora`가 없다. 플러그인 테스트는 `tests/conftest.py`가 `plugin/cc-agora/scripts/`를 `sys.path`에 올려 `spawn`/`role_policy`를 임포트 가능하게 한다.

---

### Task 1: `roles.json` + `role_policy.py` — hook/wait_mode 제거

**Files:**
- Modify: `plugin/cc-agora/config/roles.json`
- Modify: `plugin/cc-agora/scripts/role_policy.py`
- Modify: `tests/test_plugin_role_policy.py`

- [ ] **Step 1: 테스트를 채널 모드로 교체**

`tests/test_plugin_role_policy.py` 전체를 다음으로 교체:

```python
"""Unit tests for plugin/cc-agora/scripts/role_policy.py."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from role_policy import (
    is_defined,
    load_roles,
    preset_for,
    undefined_role_warning,
    warn_undefined_role,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora"
ROLES_PATH = PLUGIN_ROOT / "config" / "roles.json"


@pytest.fixture(scope="module")
def roles() -> dict:
    return load_roles(ROLES_PATH)


def test_preset_for(roles: dict) -> None:
    assert preset_for("coder", roles) == "coder"
    assert preset_for("orchestrator", roles) == "orchestrator"
    assert preset_for("reviewer", roles) == "reviewer"
    assert preset_for("phantom", roles) is None


def test_is_defined(roles: dict) -> None:
    assert is_defined("coder", roles) is True
    assert is_defined("phantom", roles) is False


def test_undefined_role_warning_contains_name_and_guide() -> None:
    msg = undefined_role_warning("phantom")
    assert "phantom" in msg
    assert "roles.json" in msg
    assert "preset" in msg


def test_warn_undefined_role_writes_to_stream() -> None:
    buf = io.StringIO()
    warn_undefined_role("phantom", stream=buf)
    out = buf.getvalue()
    assert "phantom" in out
    assert out.endswith("\n")


def test_load_roles_invalid_root(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError, match="object at top level"):
        load_roles(bad)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_role_policy.py -v`
Expected: collection 단계 또는 실행에서 FAIL — `role_policy`가 아직 `hook_for`/`wait_mode_for`를 export하므로 옛 테스트는 사라졌지만, 새 테스트의 동작(`undefined_role_warning`에 "preset" 포함)이 옛 구현과 불일치 → `test_undefined_role_warning_contains_name_and_guide` FAIL.

- [ ] **Step 3: `roles.json`에서 hook 필드 제거**

`plugin/cc-agora/config/roles.json` 전체를 다음으로 교체:

```json
{
  "orchestrator": { "preset": "orchestrator" },
  "coder":        { "preset": "coder" },
  "reviewer":     { "preset": "reviewer" },
  "tester":       { "preset": "tester" },
  "writer":       { "preset": "writer" },
  "planner":      { "preset": "planner" },
  "general":      { "preset": "general" }
}
```

- [ ] **Step 4: `role_policy.py`에서 hook/wait_mode 제거**

`plugin/cc-agora/scripts/role_policy.py` 전체를 다음으로 교체:

```python
"""Role policy loader for cc-agora plugin.

Single source of truth: ``config/roles.json``. A role maps to a CLAUDE.md
preset. Hook policy / wait_mode were removed when the plugin moved to channel
mode — channel-mode workers have no Stop hook.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_roles(path: Path) -> dict[str, dict[str, str]]:
    """Load roles.json and return the raw mapping."""
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"roles.json must be an object at top level, got {type(data).__name__}")
    return data


def is_defined(role: str, roles: dict[str, dict[str, str]]) -> bool:
    return role in roles


def preset_for(role: str, roles: dict[str, dict[str, str]]) -> str | None:
    """Return the preset name declared for ``role``. ``None`` for undefined
    roles — caller falls back to ``general``."""
    entry = roles.get(role)
    if entry is None:
        return None
    return entry.get("preset")


def undefined_role_warning(role: str) -> str:
    """Standard Korean stderr message for an undefined role."""
    return (
        f"[cc-agora] 경고: role '{role}'는 roles.json에 정의되지 않음. "
        f"preset은 'general'로 대체. config/roles.json에 "
        f'{{"{role}": {{"preset":"general"}}}} 항목을 추가하면 경고가 사라진다.'
    )


def warn_undefined_role(role: str, *, stream=sys.stderr) -> None:
    print(undefined_role_warning(role), file=stream)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_role_policy.py -v`
Expected: 5건 PASS

(주의 — 이 시점에 `spawn.py`가 아직 `role_policy`에서 `hook_for`/`wait_mode_for`를 임포트하므로 `tests/test_plugin_spawn.py`는 깨진다. Task 3에서 함께 고친다. 본 Task는 `tests/test_plugin_role_policy.py`만 통과시킨다.)

- [ ] **Step 6: 커밋**

```bash
git add plugin/cc-agora/config/roles.json plugin/cc-agora/scripts/role_policy.py tests/test_plugin_role_policy.py
git commit -m "refactor: roles.json/role_policy에서 hook·wait_mode 제거 (채널 모드)"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 2: `mcp.json.template` — MCP 서버 2개

**Files:**
- Modify: `plugin/cc-agora/templates/mcp.json.template`

- [ ] **Step 1: 템플릿 교체**

`plugin/cc-agora/templates/mcp.json.template` 전체를 다음으로 교체:

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "{{SERVER_URL}}",
      "headers": {
        "X-Agora-Instance-Id": "{{INSTANCE_ID}}",
        "X-Agora-Role": "{{ROLE}}",
        "X-Agora-Description": "{{DESCRIPTION}}"
      }
    },
    "agora-channel": {
      "type": "stdio",
      "command": "agora-channel",
      "args": ["--instance-id", "{{INSTANCE_ID}}", "--broker", "{{SERVER_URL}}"]
    }
  }
}
```

- [ ] **Step 2: 검증**

Run: `.venv\Scripts\python.exe -c "import json; t=open('plugin/cc-agora/templates/mcp.json.template',encoding='utf-8').read(); s=t.replace('{{SERVER_URL}}','http://x/mcp').replace('{{INSTANCE_ID}}','W1').replace('{{ROLE}}','coder').replace('{{DESCRIPTION}}','d'); d=json.loads(s); print(sorted(d['mcpServers']))"`
Expected: `['agentagora', 'agora-channel']` — 치환 후 유효 JSON.

- [ ] **Step 3: 커밋**

```bash
git add plugin/cc-agora/templates/mcp.json.template
git commit -m "feat: mcp.json.template — agora-channel stdio 서버 추가"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 3: `spawn.py`/`spawn_team.py` — 채널 모드 묶음 생성

**Files:**
- Modify: `plugin/cc-agora/scripts/spawn.py`
- Modify: `plugin/cc-agora/scripts/spawn_team.py`
- Modify: `tests/test_plugin_spawn.py` (전체 교체)

- [ ] **Step 1: `tests/test_plugin_spawn.py` 전체 교체 (실패하는 테스트)**

`tests/test_plugin_spawn.py` 전체를 다음으로 교체:

```python
"""Unit tests for plugin/cc-agora/scripts/spawn.py::do_spawn (채널 모드).

do_spawn을 target_dir=tmp_path로 직접 호출해 생성 파일을 격리 검증한다.
채널 모드 워커는 CLAUDE.md + .mcp.json(2-서버) + run.bat 3파일 — Stop hook
없음.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spawn import DEFAULT_SERVER_URL, do_spawn

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora"


def _call(tmp_path: Path, **overrides) -> int:
    kwargs = dict(
        instance_id="Worker1",
        role="coder",
        description="테스트용 워커.",
        preset=None,
        target_dir=tmp_path,
        force=False,
        server_url=DEFAULT_SERVER_URL,
        plugin_root=PLUGIN_ROOT,
        stderr=sys.stderr,
        stdout=sys.stdout,
    )
    kwargs.update(overrides)
    return do_spawn(**kwargs)


def test_spawn_creates_channel_mode_files(tmp_path: Path) -> None:
    rc = _call(tmp_path, instance_id="Coder1", role="coder")
    assert rc == 0
    worker = tmp_path / "Coder1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    assert (worker / "run.bat").is_file()
    # 채널 모드 워커는 Stop hook이 없다 — .claude/ 미생성.
    assert not (worker / ".claude").exists()

    claude_md = (worker / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Coder1" in claude_md
    assert "테스트용 워커" in claude_md
    assert "Coder 페르소나" in claude_md


def test_spawn_mcp_json_two_servers(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="W2", role="coder") == 0
    mcp = json.loads((tmp_path / "W2" / ".mcp.json").read_text(encoding="utf-8"))
    servers = mcp["mcpServers"]
    assert set(servers) == {"agentagora", "agora-channel"}
    # HTTP 서버 — 헤더 3개 (wait-mode/timeout 없음)
    headers = servers["agentagora"]["headers"]
    assert set(headers) == {
        "X-Agora-Instance-Id", "X-Agora-Role", "X-Agora-Description"}
    assert headers["X-Agora-Instance-Id"] == "W2"
    assert headers["X-Agora-Role"] == "coder"
    # 채널 어댑터 — instance-id·broker 인자
    ch = servers["agora-channel"]
    assert ch["type"] == "stdio"
    assert ch["command"] == "agora-channel"
    assert ch["args"] == [
        "--instance-id", "W2", "--broker", DEFAULT_SERVER_URL]


def test_spawn_run_bat_launches_channel_mode(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="W3", role="coder") == 0
    run_bat = (tmp_path / "W3" / "run.bat").read_text(encoding="utf-8")
    assert "claude" in run_bat
    assert "--dangerously-load-development-channels" in run_bat
    assert "server:agora-channel" in run_bat


def test_spawn_undefined_role_falls_back_to_general(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _call(tmp_path, instance_id="Ghost1", role="phantom")
    assert rc == 0
    worker = tmp_path / "Ghost1"
    assert (worker / "CLAUDE.md").is_file()
    assert (worker / ".mcp.json").is_file()
    assert (worker / "run.bat").is_file()
    err = capsys.readouterr().err
    assert "phantom" in err
    assert "roles.json" in err
    claude_md = (worker / "CLAUDE.md").read_text(encoding="utf-8")
    assert "General 페르소나" in claude_md


def test_spawn_existing_dir_without_force_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _call(tmp_path, instance_id="Dup1", role="coder") == 0
    capsys.readouterr()
    rc = _call(tmp_path, instance_id="Dup1", role="coder")
    assert rc == 1
    err = capsys.readouterr().err
    assert "이미 존재" in err
    assert "--force" in err


def test_spawn_existing_dir_with_force_overwrites(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="OverW", role="coder") == 0
    target = tmp_path / "OverW" / "CLAUDE.md"
    target.write_text("MUTATED", encoding="utf-8")
    assert _call(tmp_path, instance_id="OverW", role="coder",
                 force=True, description="새 설명") == 0
    refreshed = target.read_text(encoding="utf-8")
    assert "MUTATED" not in refreshed
    assert "새 설명" in refreshed


def test_spawn_preset_override(tmp_path: Path) -> None:
    assert _call(tmp_path, instance_id="PCoder", role="coder",
                 preset="reviewer") == 0
    body = (tmp_path / "PCoder" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "PCoder (coder)" in body
    assert "Reviewer 페르소나" in body
    assert "Coder 페르소나" not in body


def test_spawn_description_with_quotes_and_unicode(tmp_path: Path) -> None:
    desc = 'React "로그인" 폼 + 한글 — backslash \\ included'
    assert _call(tmp_path, instance_id="Quoted1", role="coder",
                 description=desc) == 0
    mcp = json.loads((tmp_path / "Quoted1" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Description"] == desc
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py -v`
Expected: FAIL — `do_spawn`가 아직 `wait_timeout_ms`를 요구하고(키워드 인자 불일치) 채널 모드 파일을 안 만든다.

- [ ] **Step 3: `spawn.py` 교체**

`plugin/cc-agora/scripts/spawn.py` 전체를 다음으로 교체:

```python
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
    # description은 JSON-encode 후 감싸는 따옴표를 떼어 본문만 치환 —
    # 따옴표·백슬래시·비ASCII가 안전하게 살아남는다.
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
        f"도착하면 턴이 깨어난다. 그때 `agora.wait`로 메시지를 수신해 처리하고, "
        f"답신은 `agora.dispatch`로 보낸다.\n"
        f"\n"
        f"다음을 **호출하지 마라**:\n"
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
```

- [ ] **Step 4: `spawn_team.py` 수정**

`plugin/cc-agora/scripts/spawn_team.py`에서 3곳을 고친다:

(a) `spawn` import에서 `DEFAULT_WAIT_TIMEOUT_MS` 제거:
```python
# 변경 전
from spawn import (
    DEFAULT_SERVER_URL,
    DEFAULT_WAIT_TIMEOUT_MS,
    _plugin_root,
    _resolve_target_dir,
    do_spawn,
)
# 변경 후
from spawn import (
    DEFAULT_SERVER_URL,
    _plugin_root,
    _resolve_target_dir,
    do_spawn,
)
```

(b) `_build_arg_parser`에서 `--wait-timeout-ms` 인자 블록을 통째로 삭제:
```python
    p.add_argument(
        "--wait-timeout-ms",
        type=int,
        default=DEFAULT_WAIT_TIMEOUT_MS,
        help="X-Agora-Wait-Timeout-Ms header value (default: 0).",
    )
```
(이 5줄 삭제. `--server-url` 인자는 그대로 둔다.)

(c) `main`의 `do_spawn(...)` 호출에서 `wait_timeout_ms=args.wait_timeout_ms,` 줄 삭제:
```python
        rc = do_spawn(
            instance_id=entry["id"],
            role=entry["role"],
            description=entry["description"],
            preset=entry["preset"],
            target_dir=target_dir,
            force=args.force,
            server_url=args.server_url,
            plugin_root=plugin_root,
        )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_plugin_spawn.py tests/test_plugin_spawn_team.py -v`
Expected: 전체 PASS. `test_plugin_spawn.py`는 신규 8건. `test_plugin_spawn_team.py`는 무수정 — `_validate_manifest` 테스트는 영향 없고, end-to-end 테스트는 `.mcp.json` 존재만 확인하므로 채널 모드에서도 통과한다.

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS (다른 `test_plugin_*` 회귀 없음).

- [ ] **Step 6: 커밋**

```bash
git add plugin/cc-agora/scripts/spawn.py plugin/cc-agora/scripts/spawn_team.py tests/test_plugin_spawn.py
git commit -m "feat: spawn — 채널 모드 워커 묶음 생성 (.mcp.json 2-서버 + run.bat)"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 4: 폴링 plumbing 삭제

**Files:**
- Delete: `plugin/cc-agora/templates/settings.local.json.template`
- Delete: `plugin/cc-agora/skills/agora-wait/`, `agora-unwait/`, `agora-rewait/`

- [ ] **Step 1: 파일·디렉토리 삭제**

```bash
git rm plugin/cc-agora/templates/settings.local.json.template
git rm -r plugin/cc-agora/skills/agora-wait plugin/cc-agora/skills/agora-unwait plugin/cc-agora/skills/agora-rewait
```

- [ ] **Step 2: 잔존 참조 확인**

Run (bash): `grep -rn "agora-wait\|agora-unwait\|agora-rewait\|settings.local.json.template\|stop-auto-wait" plugin/cc-agora/scripts plugin/cc-agora/config plugin/cc-agora/templates/mcp.json.template || echo "(no residual refs)"`
Expected: `(no residual refs)` — 스크립트·config·mcp 템플릿에 폴링 plumbing 참조가 없어야 한다. (남으면 그 파일을 고친다. 단 README·SKILL.md 문서 참조는 Task 5에서 처리.)

- [ ] **Step 3: 전체 테스트 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전체 PASS (삭제가 테스트를 깨지 않음 — 폴링 스킬은 코드가 아니라 슬래시 본문 마크다운이고, `settings.local.json.template`은 Task 3 이후 아무도 안 읽는다).

- [ ] **Step 4: 커밋**

```bash
git commit -m "refactor: 폴링 plumbing 삭제 (settings 템플릿 + agora-wait/unwait/rewait 스킬)"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

### Task 5: 문서 갱신

**Files:**
- Modify: `plugin/cc-agora/skills/agora-spawn/SKILL.md`
- Modify: `plugin/cc-agora/README.md`
- Modify: `plugin/cc-agora/templates/presets/*.md` (폴링 언급 있는 것만)
- Modify: `docs/channel-mode.md`
- Modify: `README.md`

- [ ] **Step 1: `agora-spawn/SKILL.md` 갱신**

`plugin/cc-agora/skills/agora-spawn/SKILL.md`의 `## 동작` 절을 채널 모드에 맞게 고친다:
- description 첫 줄의 "role-derived Stop hook" 표현 제거 → "채널 모드 묶음(.mcp.json 2-서버, run.bat)".
- 4번 항목 "4개 파일(... settings.local.json, stop-hook.py)" → "3개 파일: `CLAUDE.md`, `.mcp.json`(HTTP + agora-channel stdio), `run.bat`".
- hook policy / `none` role 관련 문장 제거.
- 5번 "워커가 `claude` 실행" → "워커가 `run.bat` 실행(`--dangerously-load-development-channels`로 채널 모드 기동)".

- [ ] **Step 2: `plugin/cc-agora/README.md` 갱신**

폴링/Stop hook/`agora-wait`·`agora-unwait`·`agora-rewait` 슬래시 언급을 제거하고, 채널 모드(워커가 `run.bat`으로 기동, `claude/channel` push 수신)로 대체한다. 슬래시 목록에서 삭제된 3개를 뺀다.

- [ ] **Step 3: 프리셋의 폴링 언급 제거**

Run (bash): `grep -rln "Stop hook\|agora.wait\|agora-wait\|폴링\|wait 루프" plugin/cc-agora/templates/presets/ || echo "(none)"`
매칭된 프리셋 파일에서, 폴링/Stop hook/wait 루프 관련 페르소나 문구를 제거하거나 채널 모드 표현으로 바꾼다(워커는 `<channel>` 알림으로 깨어나 `agora.wait`로 수신). `agora.wait`를 "도구"로 언급한 부분은 — 채널 모드에서도 깨어난 뒤 드레인에 쓰므로 — 남겨도 된다. "Stop hook"·"폴링"·"wait 루프"만 제거 대상.

- [ ] **Step 4: `docs/channel-mode.md` 갱신**

수동 `.mcp.json`/`settings.local.json` 작성 절을 축소하고, 권장 경로를 "`/cc-agora:agora-spawn`으로 채널 모드 워커를 찍어내고 `run.bat`으로 기동"으로 바꾼다. 수동 절차는 플러그인 없이 쓰는 경우의 참고로만 남긴다.

- [ ] **Step 5: 루트 `README.md` 갱신**

cc-agora 플러그인 관련 서술에 "플러그인이 채널 모드 워커를 spawn한다"는 점을 반영한다. "운영 패턴"·플러그인 링크 부근 한 줄.

- [ ] **Step 6: 확인 + 커밋**

Run (bash): `grep -rln "agora-wait\|agora-unwait\|agora-rewait" plugin/cc-agora/README.md plugin/cc-agora/skills/agora-spawn/SKILL.md || echo "(clean)"`
Expected: `(clean)` — 갱신한 문서에 삭제된 스킬 참조가 없다.

```bash
git add plugin/cc-agora/skills/agora-spawn/SKILL.md plugin/cc-agora/README.md plugin/cc-agora/templates/presets docs/channel-mode.md README.md
git commit -m "docs: 채널 모드 전환 반영 — agora-spawn·플러그인 README·channel-mode 가이드"
```
커밋 메시지 끝에 추가: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Self-Review

- **Spec 커버리지** — spec §3.2(`mcp.json.template` 2-서버)는 Task 2, §3.3(spawn 완전한 묶음·`run.bat`)은 Task 3, §3.4(폴링 plumbing 제거 — `roles.json`/`role_policy.py`는 Task 1, 스킬·settings 템플릿은 Task 4), §3.5(문서)는 Task 5가 구현한다. §3.1(콘솔 스크립트)은 선행 plan `2026-05-16-agora-channel-script.md`.
- **Placeholder** — Task 1~4의 코드·테스트는 완전체. Task 5의 문서 편집은 산문 수정이라 변경 지점과 방향을 구체적으로 지정했다(정확한 산문은 실행자가 파일을 읽고 작성).
- **타입 일관성** — `do_spawn`는 Task 3에서 `wait_timeout_ms` 매개변수를 제거했고, `spawn_team.py`(Step 4)와 `test_plugin_spawn.py`(Step 1)의 호출이 모두 새 시그니처와 일치. `role_policy`의 공개 표면은 Task 1에서 `load_roles`/`is_defined`/`preset_for`/`undefined_role_warning`/`warn_undefined_role`로 축소됐고, `spawn.py`의 import(Task 3)가 그와 일치(`hook_for`/`wait_mode_for` 미임포트). `mcp.json.template`의 치환 변수(`{{SERVER_URL}}`·`{{INSTANCE_ID}}`·`{{ROLE}}`·`{{DESCRIPTION}}`)는 `_render_mcp_json`이 치환하는 것과 정확히 일치 — 옛 `{{WAIT_TIMEOUT_MS}}`·`{{WAIT_MODE_HEADER_LINE}}`는 양쪽 모두에서 제거됐다.
- **task 의존** — Task 1이 `role_policy`를 바꾸면 Task 3 전까지 `test_plugin_spawn.py`가 깨진다(Step 5 주의에 명시). Task 3이 `spawn.py`를 새 `role_policy`에 맞춰 고치면 해소된다. subagent-driven 실행 시 Task 1·2·3은 순서대로 진행.
