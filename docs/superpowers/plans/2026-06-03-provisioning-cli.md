# agora-init 최초 세팅 CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI를 거치지 않고 사용자가 직접 실행해 팀 워커 + 통신 매트릭스를 최초 1회 부트스트랩하는 결정론적 CLI `agora-init`를 `src/agent_agora/provisioning/`에 정식 편입한다.

**Architecture:** 새 서브패키지 `agent_agora.provisioning`. `cli.py`가 대화형(인자 없음) 또는 비대화형(`--manifest`) 진입점이며, `manifest.py`(스키마·검증)·`spawn.py`(워커 파일 생성)·`matrix.py`(allow→CSV)·`roles.py`(role→플러그인 매핑)를 오케스트레이션한다. `templates/`에 `.mcp.json`·`run.bat`·`run-server.bat` 템플릿을 동봉한다. 순수 stdlib(argparse/json/csv/re/urllib); 매트릭스 POST만 네트워크.

**Tech Stack:** Python 3.13, stdlib only, pytest. 기존 `plugin/cc-agora-ops/scripts/{spawn,spawn_team,comm_matrix,role_policy}.py`를 *참고*해 재작성(직접 import 안 함 — plugin은 3.11 독립 구조).

**Branch:** `feat/provisioning-cli` (이미 생성됨, spec 커밋 `73142a7`).

---

## File Structure

| 파일 | 책임 |
|------|------|
| `src/agent_agora/provisioning/__init__.py` | 패키지 마커 + 공개 표면 re-export |
| `src/agent_agora/provisioning/roles.py` | `ROLES` dict + `plugin_for`/`is_defined`/`undefined_role_warning` |
| `src/agent_agora/provisioning/manifest.py` | 확장 manifest 스키마·검증·직렬화 |
| `src/agent_agora/provisioning/matrix.py` | `allow`→CSV(행=to/열=from, 정사각) + 선택적 POST |
| `src/agent_agora/provisioning/spawn.py` | 워커 디렉터리 4파일 생성 + run-server.bat + 마켓플레이스 탐색 |
| `src/agent_agora/provisioning/cli.py` | argparse + 대화형/비대화형 `main()` 오케스트레이션 |
| `src/agent_agora/provisioning/templates/mcp.json.template` | 2-서버 .mcp.json 템플릿 |
| `src/agent_agora/provisioning/templates/run.bat` | 채널 모드 워커 기동 .bat |
| `src/agent_agora/provisioning/templates/run-server.bat` | 서버 기동 .bat |
| `tests/test_provisioning_roles.py` | roles 매핑 테스트 |
| `tests/test_provisioning_manifest.py` | manifest 검증 테스트 |
| `tests/test_provisioning_matrix.py` | allow→CSV + round-trip 테스트 |
| `tests/test_provisioning_spawn.py` | 워커 파일 생성 테스트 |
| `tests/test_provisioning_cli.py` | 비대화형/대화형 end-to-end 테스트 |
| `pyproject.toml` | `[project.scripts]` + `package-data` 수정 |

---

### Task 1: 서브패키지 스캐폴드 + roles

**Files:**
- Create: `src/agent_agora/provisioning/__init__.py`
- Create: `src/agent_agora/provisioning/roles.py`
- Test: `tests/test_provisioning_roles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provisioning_roles.py
from agent_agora.provisioning import roles


def test_defined_role_maps_to_plugin():
    assert roles.plugin_for("coder") == "cc-agora-coder"
    assert roles.plugin_for("sp-implementer") == "superpowers-implementer"


def test_undefined_role_returns_none():
    assert roles.plugin_for("nonesuch") is None
    assert roles.is_defined("coder") is True
    assert roles.is_defined("nonesuch") is False


def test_undefined_role_warning_is_korean():
    msg = roles.undefined_role_warning("nonesuch")
    assert "nonesuch" in msg
    assert "cc-agora-general" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_roles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_agora.provisioning'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_agora/provisioning/__init__.py
"""최초 세팅 CLI (agora-init) — 사람이 직접 실행하는 팀+매트릭스 부트스트랩."""
```

```python
# src/agent_agora/provisioning/roles.py
"""role → 페르소나 플러그인 매핑.

plugin/cc-agora-ops/config/roles.json의 동등 사본(plugin은 agent_agora를
import하지 않는 3.11 독립 구조라 공유 불가). 새 role을 늘릴 때 양쪽을 함께 갱신한다.
"""
from __future__ import annotations

ROLES: dict[str, str] = {
    "orchestrator": "cc-agora-orchestrator",
    "coder": "cc-agora-coder",
    "reviewer": "cc-agora-reviewer",
    "tester": "cc-agora-tester",
    "writer": "cc-agora-writer",
    "planner": "cc-agora-planner",
    "general": "cc-agora-general",
    "sp-planner": "superpowers-planner",
    "sp-implementer": "superpowers-implementer",
    "sp-debugger": "superpowers-debugger",
    "sp-reviewer": "superpowers-reviewer",
    "sp-router": "superpowers-router",
    "sp-improver": "superpowers-improver",
    "sp-tester": "superpowers-tester",
    "sp-base": "superpowers-base",
    "sp-model": "superpowers-model",
    "sp-view": "superpowers-view",
    "sp-controller": "superpowers-controller",
}

FALLBACK_PLUGIN = "cc-agora-general"


def is_defined(role: str) -> bool:
    return role in ROLES


def plugin_for(role: str) -> str | None:
    """role의 페르소나 플러그인. 미정의면 None(호출자가 FALLBACK_PLUGIN으로 대체)."""
    return ROLES.get(role)


def undefined_role_warning(role: str) -> str:
    return (
        f"[agora-init] 경고: role '{role}'는 정의되지 않음. "
        f"plugin은 '{FALLBACK_PLUGIN}'로 대체. roles.py에 항목을 추가하면 경고가 사라진다."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_roles.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/provisioning/__init__.py src/agent_agora/provisioning/roles.py tests/test_provisioning_roles.py
git commit -m "feat(provisioning): roles 매핑 + 서브패키지 스캐폴드"
```

---

### Task 2: manifest 스키마·검증

**Files:**
- Create: `src/agent_agora/provisioning/manifest.py`
- Test: `tests/test_provisioning_manifest.py`

확장 manifest:
```json
{ "version":1, "spawn_dir":"C:/work/team", "server_url":"http://127.0.0.1:8420/mcp",
  "marketplace_path":"C:/.../plugin",
  "team":[ {"id":"Coder1","role":"coder","description":"...","allow":["Reviewer1",".*"]} ] }
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provisioning_manifest.py
import pytest
from agent_agora.provisioning import manifest


def _ok():
    return {
        "version": 1,
        "spawn_dir": "C:/work/team",
        "server_url": "http://127.0.0.1:8420/mcp",
        "team": [
            {"id": "Coder1", "role": "coder", "description": "코딩", "allow": ["Reviewer1"]},
            {"id": "Reviewer1", "role": "reviewer", "description": "리뷰", "allow": ["*"]},
        ],
    }


def test_valid_manifest_passes_and_normalizes_star():
    m, errors = manifest.validate(_ok())
    assert errors == []
    # "*"는 ".*"로 정규화된다.
    assert m["team"][1]["allow"] == [".*"]
    # allow 기본값은 빈 리스트.
    assert m["team"][0]["allow"] == ["Reviewer1"]


def test_wrong_version_errors():
    data = _ok(); data["version"] = 2
    _, errors = manifest.validate(data)
    assert any("version" in e for e in errors)


def test_duplicate_id_errors():
    data = _ok(); data["team"][1]["id"] = "Coder1"
    _, errors = manifest.validate(data)
    assert any("중복" in e for e in errors)


def test_bad_id_format_errors():
    data = _ok(); data["team"][0]["id"] = "bad id!"
    _, errors = manifest.validate(data)
    assert any("형식" in e for e in errors)


def test_missing_required_key_errors():
    data = _ok(); del data["team"][0]["role"]
    _, errors = manifest.validate(data)
    assert any("필수 키" in e for e in errors)


def test_allow_to_unknown_literal_id_warns_not_errors():
    data = _ok(); data["team"][0]["allow"] = ["GhostWorker"]
    m, errors = manifest.validate(data)
    assert errors == []
    assert any("GhostWorker" in w for w in m["warnings"])


def test_allow_regex_pattern_passes_without_warning():
    data = _ok(); data["team"][0]["allow"] = ["sp-.*"]
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["warnings"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module ... has no attribute 'validate'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_agora/provisioning/manifest.py
"""확장 manifest 스키마·검증·직렬화.

plugin/cc-agora-ops/scripts/spawn_team.py:_validate_manifest를 참고해 재작성하고,
spawn_dir/server_url/marketplace_path/allow 필드를 추가한다. validate()는
(정규화된 manifest, 오류 리스트)를 돌려준다 — 오류가 비어야 진행 가능. 치명적이지
않은 문제(미지 role, allow의 미지 리터럴 id)는 manifest["warnings"]에 누적한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import roles as _roles

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
DEFAULT_SERVER_URL = "http://127.0.0.1:8420/mcp"


def _looks_like_id(token: str) -> bool:
    """allow 토큰이 '워커 id 리터럴'처럼 보이는가(정규식 메타문자 없음)."""
    return bool(_ID_RE.match(token))


def validate(data: object) -> tuple[dict, list[str]]:
    """Return (normalized_manifest, errors). errors는 한국어 줄. 비어야 진행 가능.

    normalized_manifest는 version/spawn_dir/server_url/marketplace_path/team/warnings
    키를 갖는다. team 각 항목은 id/role/description/allow(정규화) 보존."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return {}, ["[agora-init] manifest 루트는 JSON 객체여야 합니다."]

    if data.get("version") != 1:
        errors.append(
            f"[agora-init] manifest version은 1이어야 합니다 (현재: {data.get('version')!r}).")

    team = data.get("team")
    if not isinstance(team, list) or not team:
        errors.append("[agora-init] manifest.team은 비어있지 않은 배열이어야 합니다.")
        return {}, errors

    seen: set[str] = set()
    cleaned: list[dict] = []
    for idx, entry in enumerate(team):
        if not isinstance(entry, dict):
            errors.append(f"[agora-init] team[{idx}]: 객체가 아님.")
            continue
        missing = [k for k in ("id", "role", "description") if k not in entry]
        if missing:
            errors.append(f"[agora-init] team[{idx}]: 필수 키 누락 {missing}.")
            continue
        iid = entry["id"]
        if not isinstance(iid, str) or not _ID_RE.match(iid):
            errors.append(
                f"[agora-init] team[{idx}]: id {iid!r}는 ^[A-Za-z0-9_-]{{1,32}}$ 형식이어야 합니다.")
            continue
        if iid in seen:
            errors.append(f"[agora-init] team[{idx}]: id '{iid}' 중복.")
            continue
        role = entry.get("role")
        desc = entry.get("description")
        if not isinstance(role, str) or not role:
            errors.append(f"[agora-init] team[{idx}]: role은 비어있지 않은 문자열.")
            continue
        if not isinstance(desc, str) or not desc:
            errors.append(f"[agora-init] team[{idx}]: description은 비어있지 않은 문자열.")
            continue
        raw_allow = entry.get("allow", [])
        if not isinstance(raw_allow, list):
            errors.append(f"[agora-init] team[{idx}]: allow는 배열이어야 합니다.")
            continue
        allow: list[str] = []
        for tok in raw_allow:
            if not isinstance(tok, str) or not tok:
                errors.append(f"[agora-init] team[{idx}]: allow 원소는 비어있지 않은 문자열.")
                continue
            allow.append(".*" if tok == "*" else tok)
        if not _roles.is_defined(role):
            warnings.append(_roles.undefined_role_warning(role))
        seen.add(iid)
        cleaned.append({"id": iid, "role": role, "description": desc, "allow": allow})

    if errors:
        return {}, errors

    # allow의 미지 리터럴 id 경고(정규식 토큰은 통과).
    ids = {e["id"] for e in cleaned}
    for e in cleaned:
        for tok in e["allow"]:
            if _looks_like_id(tok) and tok not in ids:
                warnings.append(
                    f"[agora-init] 경고: {e['id']}.allow의 '{tok}'는 팀에 없는 id입니다(무시되지 않음, 정규식이면 정상).")

    norm = {
        "version": 1,
        "spawn_dir": data.get("spawn_dir"),
        "server_url": data.get("server_url") or DEFAULT_SERVER_URL,
        "marketplace_path": data.get("marketplace_path"),
        "team": cleaned,
        "warnings": warnings,
    }
    return norm, []


def dumps(norm: dict) -> str:
    """정규화 manifest를 team.json 텍스트로 직렬화(warnings 제외)."""
    out = {
        "version": 1,
        "spawn_dir": norm.get("spawn_dir"),
        "server_url": norm.get("server_url"),
        "marketplace_path": norm.get("marketplace_path"),
        "team": [
            {"id": e["id"], "role": e["role"], "description": e["description"], "allow": e["allow"]}
            for e in norm["team"]
        ],
    }
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


def load(path: Path) -> tuple[dict, list[str]]:
    """파일에서 manifest를 읽어 validate한다. 파싱 실패는 errors로."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"[agora-init] manifest 로드 실패: {exc}"]
    return validate(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_manifest.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/provisioning/manifest.py tests/test_provisioning_manifest.py
git commit -m "feat(provisioning): 확장 manifest 검증·정규화·직렬화"
```

---

### Task 3: allow → comm-matrix.csv 변환

**Files:**
- Create: `src/agent_agora/provisioning/matrix.py`
- Test: `tests/test_provisioning_matrix.py`

방향 규약(`src/agent_agora/comm_matrix.py:11-18,132-145` 확인): `_weights[to_pat][from_pat]`, CSV는 코너셀 없는 정사각 NxN — **데이터 행 i = to(노드[i]), 열 j = from(노드[j])**, `cell[i][j]` = from→to weight. 노드 = 워커 id들(입력 순) + allow에 등장한 비-id 정규식(등장 순).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provisioning_matrix.py
from agent_agora.provisioning import matrix
from agent_agora.comm_matrix import CommMatrix


TEAM = [
    {"id": "Coder1", "allow": ["Reviewer1"]},
    {"id": "Reviewer1", "allow": [".*"]},
    {"id": "Tester1", "allow": []},
]


def test_csv_header_is_square_node_list():
    csv = matrix.build_csv(TEAM)
    lines = csv.strip().splitlines()
    header = lines[0].split(",")
    # 노드 = 워커 3 + 비-id 정규식 ".*" 1 = 4
    assert header == ["Coder1", "Reviewer1", "Tester1", ".*"]
    # 정사각: 데이터 행 수 == 헤더 길이
    assert len(lines) - 1 == len(header)


def test_csv_roundtrips_through_commmatrix_with_correct_direction():
    csv = matrix.build_csv(TEAM)
    cm = CommMatrix()
    cm.load_csv(csv)
    # Coder1 → Reviewer1 허용, 역방향 불가
    assert cm.is_allowed("Coder1", "Reviewer1") is True
    assert cm.is_allowed("Reviewer1", "Coder1") is True   # Reviewer1.allow=[".*"]
    assert cm.is_allowed("Coder1", "Tester1") is False
    # Reviewer1은 .*라 임의 워커에게 가능
    assert cm.is_allowed("Reviewer1", "Tester1") is True
    # Tester1은 allow 없음 → 아무에게도 불가
    assert cm.is_allowed("Tester1", "Coder1") is False
    # self는 미명시면 불가
    assert cm.is_allowed("Coder1", "Coder1") is False


def test_empty_allow_everywhere_blocks_all():
    team = [{"id": "A", "allow": []}, {"id": "B", "allow": []}]
    cm = CommMatrix()
    cm.load_csv(matrix.build_csv(team))
    assert cm.is_allowed("A", "B") is False
    assert cm.is_allowed("B", "A") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_matrix.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: ... 'build_csv'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_agora/provisioning/matrix.py
"""allow 목록 → comm-matrix.csv(행=to, 열=from, 정사각 NxN). 선택적 서버 POST.

방향은 comm_matrix.CommMatrix._weights[to_pat][from_pat] 규약을 따른다. 노드 집합은
워커 id들 + allow에 등장한 비-id 정규식. operator는 매트릭스 무시(항상 allow)라 노드에
넣지 않는다.
"""
from __future__ import annotations

import re
import urllib.request

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _nodes(team: list[dict]) -> list[str]:
    ids = [m["id"] for m in team]
    extra: list[str] = []
    for m in team:
        for tok in m.get("allow", []):
            if tok not in ids and tok not in extra:
                extra.append(tok)
    return ids + extra


def _allows(from_id: str, to_node: str, allow: list[str]) -> bool:
    """from_id의 allow가 to_node를 허용하는가. 리터럴 동일 또는 정규식 fullmatch."""
    for pat in allow:
        if pat == to_node:
            return True
        try:
            if re.fullmatch(pat, to_node):
                return True
        except re.error:
            continue
    return False


def build_csv(team: list[dict]) -> str:
    """team(각 {id, allow}) → comm-matrix.csv 문자열. 행=to, 열=from."""
    nodes = _nodes(team)
    allow_by_id = {m["id"]: list(m.get("allow", [])) for m in team}
    lines = [",".join(nodes)]
    for to in nodes:                       # 행 = 수신자(to)
        row = []
        for frm in nodes:                  # 열 = 발신자(from)
            w = 0
            if frm in allow_by_id and _allows(frm, to, allow_by_id[frm]):
                w = 1
            row.append(str(w))
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def post_to_server(server_url: str, csv_text: str, token: str, *, timeout: float = 5.0) -> int:
    """서버 /admin/comm-matrix에 CSV를 POST. HTTP 상태코드 반환. 서버 URL은 .../mcp
    형태이므로 베이스로 환원해 /admin/comm-matrix를 붙인다."""
    base = server_url.rsplit("/mcp", 1)[0].rstrip("/")
    req = urllib.request.Request(
        f"{base}/admin/comm-matrix",
        data=csv_text.encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_matrix.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/provisioning/matrix.py tests/test_provisioning_matrix.py
git commit -m "feat(provisioning): allow→comm-matrix.csv 변환(행=to/열=from) + 서버 POST"
```

---

### Task 4: 템플릿 + 워커 파일 생성

**Files:**
- Create: `src/agent_agora/provisioning/templates/mcp.json.template`
- Create: `src/agent_agora/provisioning/templates/run.bat`
- Create: `src/agent_agora/provisioning/templates/run-server.bat`
- Create: `src/agent_agora/provisioning/spawn.py`
- Test: `tests/test_provisioning_spawn.py`

- [ ] **Step 1: Create the three template files (정적, 코드 아님)**

`src/agent_agora/provisioning/templates/mcp.json.template` (LF):
```
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "{{SERVER_URL}}",
      "headers": {
        "X-Agora-Instance-Id": "{{INSTANCE_ID}}",
        "X-Agora-Role": "{{ROLE}}",
        "X-Agora-Description": "{{DESCRIPTION}}",
        "X-Agora-Cwd": "{{CWD}}"
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

`src/agent_agora/provisioning/templates/run.bat` (ASCII, **CRLF**):
```
@echo off
REM Channel-mode worker launcher. agora-channel is a self-made channel not on
REM the official allowlist, so --dangerously-load-development-channels is needed.
REM Lower autoCompact threshold to 60 percent so the worker compacts early.
set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60
REM Worker name = basename of this folder (matches the instance_id).
for %%I in ("%~dp0.") do set "AGORA_NAME=%%~nxI"
claude --name "%AGORA_NAME%" --dangerously-skip-permissions %* --dangerously-load-development-channels server:agora-channel
```

`src/agent_agora/provisioning/templates/run-server.bat` (ASCII, **CRLF**):
```
@echo off
REM AgentAgora server launcher. Run by double-clicking or: run-server.bat
REM Stop with Ctrl+C in the spawned window.
setlocal
cd /d "%~dp0"
where agent-agora >nul 2>nul
if %ERRORLEVEL%==0 (
    agent-agora --dir "%~dp0." --port 8420 --no-tls
) else (
    py -3.13 -m agent_agora --dir "%~dp0." --port 8420 --no-tls
)
echo.
echo Server stopped. Press any key to close.
pause >nul
endlocal
```

> 주의: `run.bat`/`run-server.bat`는 ASCII+CRLF. 저장 시 줄바꿈을 `\r\n`으로 쓴다(Task 4 Step 3의 `_write_bat` 사용 — 템플릿 파일 자체는 에디터로 CRLF 저장하되, 런타임은 항상 `_write_bat`로 다시 정규화하므로 안전).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_provisioning_spawn.py
import json
from pathlib import Path
from agent_agora.provisioning import spawn


def test_spawn_worker_creates_four_files(tmp_path):
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="코딩 담당",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace_path="C:/repo/plugin", force=False,
    )
    assert rc == 0
    wd = tmp_path / "Coder1"
    assert (wd / "CLAUDE.md").is_file()
    assert (wd / "run.bat").is_file()
    mcp = json.loads((wd / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Instance-Id"] == "Coder1"
    assert mcp["mcpServers"]["agentagora"]["headers"]["X-Agora-Role"] == "coder"
    settings = json.loads((wd / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-coder@agentagora"] is True
    assert settings["enabledPlugins"]["cc-agora@agentagora"] is True
    assert settings["extraKnownMarketplaces"]["agentagora"]["source"]["path"] == "C:/repo/plugin"


def test_spawn_undefined_role_falls_back_to_general(tmp_path):
    spawn.spawn_worker(
        instance_id="W1", role="nonesuch", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace_path="C:/repo/plugin", force=False,
    )
    settings = json.loads((tmp_path / "W1" / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["cc-agora-general@agentagora"] is True


def test_spawn_existing_dir_without_force_fails(tmp_path):
    (tmp_path / "Coder1").mkdir()
    rc = spawn.spawn_worker(
        instance_id="Coder1", role="coder", description="x",
        parent_dir=tmp_path, server_url="http://127.0.0.1:8420/mcp",
        marketplace_path="C:/repo/plugin", force=False,
    )
    assert rc == 1


def test_write_server_launcher(tmp_path):
    spawn.write_server_launcher(tmp_path)
    bat = (tmp_path / "run-server.bat").read_bytes()
    assert b"\r\n" in bat            # CRLF
    assert b"agent-agora" in bat


def test_find_marketplace_locates_repo_plugin():
    # 작업트리에서 실행 시 repo/plugin/.claude-plugin/marketplace.json을 찾는다.
    found = spawn.find_marketplace()
    assert found is None or found.endswith("plugin")
```

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_agora/provisioning/spawn.py
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


def _render_settings_local(*, persona_plugin: str, marketplace_path: str) -> str:
    settings = {
        "extraKnownMarketplaces": {
            "agentagora": {"source": {"source": "directory", "path": marketplace_path}}
        },
        "enabledPlugins": {
            f"{persona_plugin}@agentagora": True,
            "cc-agora@agentagora": True,
        },
    }
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"


def spawn_worker(*, instance_id: str, role: str, description: str, parent_dir: Path,
                 server_url: str, marketplace_path: str, force: bool,
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
                                        marketplace_path=marketplace_path))
    print(f"[agora-init] '{instance_id}/' 생성 (role={role}, persona={persona_plugin}).", file=stdout)
    return 0


def write_server_launcher(parent_dir: Path) -> None:
    """parent_dir/run-server.bat 생성(ASCII+CRLF)."""
    _write_bat(Path(parent_dir) / "run-server.bat",
               (_TPL_DIR / "run-server.bat").read_text(encoding="ascii"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_spawn.py -v`
Expected: PASS (5 passed). `test_find_marketplace_locates_repo_plugin`은 작업트리에서 repo/plugin을 찾아 통과.

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/provisioning/templates/mcp.json.template src/agent_agora/provisioning/templates/run.bat src/agent_agora/provisioning/templates/run-server.bat src/agent_agora/provisioning/spawn.py tests/test_provisioning_spawn.py
git commit -m "feat(provisioning): 워커 파일 생성 + 템플릿 + 마켓플레이스 탐색"
```

---

### Task 5: CLI — 비대화형(`--manifest`) 오케스트레이션

**Files:**
- Create: `src/agent_agora/provisioning/cli.py`
- Test: `tests/test_provisioning_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provisioning_cli.py
import json
from pathlib import Path
from agent_agora.provisioning import cli
from agent_agora.comm_matrix import CommMatrix


def _manifest(tmp_path):
    return {
        "version": 1,
        "spawn_dir": tmp_path.as_posix(),
        "server_url": "http://127.0.0.1:8420/mcp",
        "marketplace_path": "C:/repo/plugin",
        "team": [
            {"id": "Coder1", "role": "coder", "description": "코딩", "allow": ["Reviewer1"]},
            {"id": "Reviewer1", "role": "reviewer", "description": "리뷰", "allow": ["*"]},
        ],
    }


def test_noninteractive_generates_all_artifacts(tmp_path):
    mpath = tmp_path / "team.json"
    mpath.write_text(json.dumps(_manifest(tmp_path)), encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 0
    # 워커 디렉터리
    assert (tmp_path / "Coder1" / ".mcp.json").is_file()
    assert (tmp_path / "Reviewer1" / "run.bat").is_file()
    # team.json 보존(spawn_dir에)
    assert (tmp_path / "team.json").is_file()
    # 매트릭스 CSV
    csv = (tmp_path / ".agentagora" / "comm-matrix.csv").read_text(encoding="utf-8")
    cm = CommMatrix(); cm.load_csv(csv)
    assert cm.is_allowed("Coder1", "Reviewer1") is True
    assert cm.is_allowed("Coder1", "Reviewer1") and not cm.is_allowed("Reviewer1", "Coder1") is False
    # 서버 기동 스크립트
    assert (tmp_path / "run-server.bat").is_file()


def test_noninteractive_bad_manifest_returns_1(tmp_path, capsys):
    mpath = tmp_path / "bad.json"
    mpath.write_text('{"version": 2, "team": []}', encoding="utf-8")
    rc = cli.main(["--manifest", str(mpath)])
    assert rc == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_cli.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: ... 'main'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_agora/provisioning/cli.py
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

    # 2) team.json 보존
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

    print(f"[agora-init] 완료 — {len(norm['team'])}개 워커, 위치: {spawn_dir.as_posix()}", file=stdout)
    return 0


def _interactive(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr) -> dict:
    """프롬프트로 manifest dict(미검증)를 만든다."""
    def ask(prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        print(f"{prompt}{suffix}: ", end="", file=stdout, flush=True)
        line = stdin.readline().strip()
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
```

> 검토 메모: `test_noninteractive_generates_all_artifacts`의 `not cm.is_allowed(...) is False` 줄은 가독성이 낮다 — 실제 작성 시 두 단언으로 분리(`assert cm.is_allowed("Coder1","Reviewer1")` / `assert cm.is_allowed("Reviewer1","Coder1")`. Reviewer1.allow=["*"]→".*"라 역방향도 True). Step 1 테스트를 이 형태로 교정해 넣을 것.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent_agora/provisioning/cli.py tests/test_provisioning_cli.py
git commit -m "feat(provisioning): CLI 비대화형(--manifest) 오케스트레이션"
```

---

### Task 6: CLI — 대화형 경로 테스트 (stdin mock)

**Files:**
- Modify: `tests/test_provisioning_cli.py` (대화형 테스트 추가)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provisioning_cli.py 에 추가
import io
from agent_agora.provisioning import cli as _cli


def test_interactive_builds_manifest_from_stdin(tmp_path, monkeypatch):
    # 프롬프트 순서: spawn_dir, server_url, marketplace, [워커1] id/role/desc/allow/추가?, [종료] id
    answers = "\n".join([
        tmp_path.as_posix(),                       # 스폰 위치
        "http://127.0.0.1:8420/mcp",               # 서버 URL
        "C:/repo/plugin",                          # 마켓플레이스
        "Coder1", "coder", "코딩", "Reviewer1", "y",  # 워커1 + 더 추가? y
        "Reviewer1", "reviewer", "리뷰", "*", "n",     # 워커2 + 더 추가? n
    ]) + "\n"
    norm = _cli._interactive(stdin=io.StringIO(answers), stdout=io.StringIO())
    m, errors = __import__("agent_agora.provisioning.manifest", fromlist=["validate"]).validate(norm)
    assert errors == []
    assert [e["id"] for e in m["team"]] == ["Coder1", "Reviewer1"]
    assert m["team"][1]["allow"] == [".*"]
```

- [ ] **Step 2: Run test to verify it fails (or passes if _interactive already correct)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_cli.py::test_interactive_builds_manifest_from_stdin -v`
Expected: 만약 FAIL이면 `_interactive`의 프롬프트 순서/readline 처리를 테스트에 맞춰 교정. (Task 5에서 이미 구현했으므로 PASS 가능 — 그러면 "기존 동작 검증"이 아닌지 점검: 프롬프트 수가 정확히 일치해야 하므로 유효한 RED가 되도록, Task 5 구현 전에 이 테스트를 먼저 작성하는 순서가 이상적. 실행 순서상 여기서 추가한다면, `_interactive`가 "워커 더 추가? (y/n)" 기본값 'y' 처리로 첫 워커 뒤 'y'를 소비하는지 확인.)

- [ ] **Step 3: Adjust implementation if needed**

`_interactive`가 테스트 입력 순서와 어긋나면 프롬프트 순서를 맞춘다(코드는 Task 5 그대로가 목표). 변경 없으면 스킵.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provisioning_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_provisioning_cli.py
git commit -m "test(provisioning): 대화형 manifest 빌드(stdin mock)"
```

---

### Task 7: 콘솔 엔트리 + package-data + 전체 스위트

**Files:**
- Modify: `pyproject.toml:20-29`

- [ ] **Step 1: pyproject 수정**

`[project.scripts]`에 추가:
```toml
[project.scripts]
agent-agora = "agent_agora.__main__:main"
agora-channel = "agent_agora.channel_adapter:cli"
agora-init = "agent_agora.provisioning.cli:main"
```

`[tool.setuptools.package-data]`에 추가:
```toml
[tool.setuptools.package-data]
"agent_agora.storage" = ["default_schemas.jsonl"]
"agent_agora.dashboard" = ["*.html", "dashboard_static/**/*"]
"agent_agora.provisioning" = ["templates/*"]
```

- [ ] **Step 2: editable 재설치로 엔트리포인트 등록**

Run: `.venv/Scripts/python.exe -m pip install -e . -q`
Expected: 성공. `agora-init` 콘솔 스크립트 등록.

- [ ] **Step 3: 콘솔 엔트리 스모크(비대화형)**

Run (PowerShell):
```
$env:TMPTEAM = "$env:TEMP\agora_init_smoke"
.venv/Scripts/python.exe -c "import json,os; d=os.environ['TMPTEAM']; os.makedirs(d,exist_ok=True); json.dump({'version':1,'spawn_dir':d.replace('\\','/'),'server_url':'http://127.0.0.1:8420/mcp','marketplace_path':'C:/repo/plugin','team':[{'id':'Coder1','role':'coder','description':'x','allow':['Reviewer1']},{'id':'Reviewer1','role':'reviewer','description':'y','allow':['*']}]}, open(d+'/team.json','w'))"
.venv/Scripts/agora-init.exe --manifest "$env:TMPTEAM\team.json"
```
Expected: `[agora-init] 완료 — 2개 워커 ...`. `$env:TMPTEAM\Coder1\.mcp.json`, `.agentagora\comm-matrix.csv`, `run-server.bat` 생성.

- [ ] **Step 4: 전체 테스트 스위트**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 전부 PASS (기존 719 + 신규 provisioning 테스트). 회귀 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "feat(provisioning): agora-init 콘솔 엔트리 + 템플릿 package-data"
```

---

### Task 8: 문서화 + spec 상태 갱신

**Files:**
- Modify: `docs/plugins.md` 또는 `docs/usage-guide.md` (agora-init 사용법 섹션 추가)
- Modify: `docs/superpowers/specs/2026-06-03-provisioning-cli-design.md` (상태: 구현 완료)
- Modify: `docs/backlog.md` (관련 항목 있으면 정리)

- [ ] **Step 1: usage-guide에 agora-init 섹션 추가**

`docs/usage-guide.md`에 "최초 세팅: agora-init" 절을 추가한다. 내용:
- 설치 후 `agora-init` 실행(대화형) 또는 `agora-init --manifest team.json`(비대화형).
- 생성물: 워커 디렉터리들, `team.json`, `.agentagora/comm-matrix.csv`, `run-server.bat`.
- 다음 단계: `run-server.bat`로 서버 기동 → 각 워커 `run.bat` 실행 → 자동 등록.
- `AGORA_ADMIN_TOKEN` 설정 시 매트릭스 즉시 적용.

(실제 문장은 기존 가이드 문체에 맞춰 작성. 한국어.)

- [ ] **Step 2: spec 상태 갱신**

`docs/superpowers/specs/2026-06-03-provisioning-cli-design.md`의 상태 줄을 `구현 완료 (커밋 …)`로 바꾸고, "미해결" 섹션의 해소된 항목(CSV 방향=행 to/열 from 확정, 마켓플레이스=탐색+프롬프트+manifest 필드)을 반영.

- [ ] **Step 3: 전체 스위트 재확인 + 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 전부 PASS.

```bash
git add docs/usage-guide.md docs/superpowers/specs/2026-06-03-provisioning-cli-design.md
git commit -m "docs(provisioning): agora-init 사용법 + spec 상태 갱신"
```

- [ ] **Step 4: 푸시 (사용자 지시: 끝나면 모두 커밋 푸시)**

```bash
git push -u origin feat/provisioning-cli
```
이후 머지 여부는 사용자 확인.

---

## Self-Review

**Spec coverage:**
- 위치/형태(src 서브패키지 + 콘솔 엔트리) → Task 1·7 ✅
- 대화형 흐름 → Task 5(`_interactive`)·6 ✅
- 확장 manifest 스키마 → Task 2 ✅
- 산출물(4파일·team.json·CSV·run-server.bat·선택 POST) → Task 4·5 ✅
- allow→CSV(방향 확정) → Task 3 ✅
- 비대화형 재실행 → Task 5 ✅
- 검증/에러 → Task 2 ✅
- 테스트 → Task 2·3·4·5·6·7 ✅
- roles 매핑 → Task 1 ✅
- 마켓플레이스 경로(미해결 해소) → Task 4(`find_marketplace`)·5(프롬프트/manifest) ✅

**Placeholder scan:** Task 8 Step 1·2는 문서 산문이라 "기존 문체에 맞춰"로 위임 — 코드 스텝이 아니므로 허용. 그 외 코드 스텝은 완전 코드.

**Type consistency:** `spawn_worker`/`write_server_launcher`/`find_marketplace`/`build_csv`/`post_to_server`/`validate`/`dumps`/`load`/`plugin_for`/`is_defined`/`undefined_role_warning` — 정의(Task 1–4)와 호출(Task 5 `_generate`/`_interactive`)이 일치. `_spawn._write_text`를 cli에서 재사용(공개 헬퍼로 취급).

**교정 사항:** Task 5 Step 1 테스트의 `not cm.is_allowed(...) is False` 줄은 두 개의 명확한 단언으로 분리해 작성(검토 메모 참조).
