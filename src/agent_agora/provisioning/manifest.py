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
        bad_allow = False
        for tok in raw_allow:
            if not isinstance(tok, str) or not tok:
                errors.append(f"[agora-init] team[{idx}]: allow 원소는 비어있지 않은 문자열.")
                bad_allow = True
                continue
            allow.append(".*" if tok == "*" else tok)
        if bad_allow:
            continue
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
                    f"[agora-init] 경고: {e['id']}.allow의 '{tok}'는 팀에 없는 id입니다"
                    f"(무시되지 않음, 정규식이면 정상).")

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
            {"id": e["id"], "role": e["role"], "description": e["description"],
             "allow": e["allow"]}
            for e in norm["team"]
        ],
    }
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


def load(path: Path) -> tuple[dict, list[str]]:
    """파일에서 manifest를 읽어 validate한다. 파싱 실패는 errors로."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"[agora-init] manifest 로드 실패: {exc}"]
    return validate(data)
