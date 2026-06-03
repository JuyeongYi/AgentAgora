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
