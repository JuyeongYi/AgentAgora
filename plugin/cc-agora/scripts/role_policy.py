"""Role policy loader for cc-agora plugin.

Single source of truth: ``config/roles.json``. Hook policy is stored explicitly;
wait_mode is *derived* from hook policy (spec §4.1 — keeping wait_mode in two
places risks the SessionCloseMiddleware false-fire class of bug).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

WaitMode = Literal["auto", "manual"]

_HOOK_TO_WAIT_MODE: dict[str, WaitMode] = {
    "stop-auto-wait": "auto",
    "none": "manual",
}


def load_roles(path: Path) -> dict[str, dict[str, str]]:
    """Load roles.json and return the raw mapping."""
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"roles.json must be an object at top level, got {type(data).__name__}")
    return data


def is_defined(role: str, roles: dict[str, dict[str, str]]) -> bool:
    return role in roles


def hook_for(role: str, roles: dict[str, dict[str, str]]) -> str | None:
    entry = roles.get(role)
    if entry is None:
        return None
    return entry.get("hook")


def preset_for(role: str, roles: dict[str, dict[str, str]]) -> str | None:
    """Return the preset name declared for ``role``.

    Returns ``None`` for undefined roles — caller decides the fallback (spec §4.1
    says fall back to ``general`` for the CLAUDE.md copy).
    """
    entry = roles.get(role)
    if entry is None:
        return None
    return entry.get("preset")


def wait_mode_for(role: str, roles: dict[str, dict[str, str]]) -> WaitMode | None:
    """Derive wait_mode from hook policy. ``None`` for undefined roles → caller
    should omit the X-Agora-Wait-Mode header so the server records ``unknown``.
    """
    hook = hook_for(role, roles)
    if hook is None:
        return None
    return _HOOK_TO_WAIT_MODE.get(hook)


def undefined_role_warning(role: str) -> str:
    """Return the standard Korean stderr message for an undefined role (spec §4.1).

    Caller is responsible for actually writing to stderr.
    """
    return (
        f"[cc-agora] 경고: role '{role}'는 roles.json에 정의되지 않음. hook 미설치. "
        "roles.json 편집 가이드: config/roles.json에 "
        f'{{"{role}": {{"hook":"stop-auto-wait","preset":"general"}}}} '
        "항목 추가 후 settings.local.json 수동 보강."
    )


def warn_undefined_role(role: str, *, stream=sys.stderr) -> None:
    print(undefined_role_warning(role), file=stream)
