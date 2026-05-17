"""Role policy loader for cc-agora-ops plugin.

Single source of truth: ``config/roles.json``. A role maps to a persona plugin
name. Hook policy / wait_mode were removed when the plugin moved to channel
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


def plugin_for(role: str, roles: dict[str, dict[str, str]]) -> str | None:
    """Return the persona plugin name declared for ``role``. ``None`` for
    undefined roles — caller falls back to the general persona plugin."""
    entry = roles.get(role)
    if entry is None:
        return None
    return entry.get("plugin")


def undefined_role_warning(role: str) -> str:
    """Standard Korean stderr message for an undefined role."""
    return (
        f"[cc-agora] 경고: role '{role}'는 roles.json에 정의되지 않음. "
        f"plugin은 'cc-agora-general'로 대체. config/roles.json에 "
        f'{{"{role}": {{"plugin":"cc-agora-general"}}}} 항목을 추가하면 경고가 사라진다.'
    )


def warn_undefined_role(role: str, *, stream=sys.stderr) -> None:
    print(undefined_role_warning(role), file=stream)
