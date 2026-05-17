"""Validates the AgentAgora marketplace manifest and persona plugin manifests."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROLES = ("orchestrator", "coder", "reviewer", "tester", "writer", "planner", "general")


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_marketplace_lists_all_nine_plugins():
    mkt = _load(REPO / ".claude-plugin" / "marketplace.json")
    names = {p["name"] for p in mkt["plugins"]}
    expected = {"cc-agora", "cc-agora-ops"} | {f"cc-agora-{r}" for r in ROLES}
    assert names == expected


def test_marketplace_sources_exist():
    mkt = _load(REPO / ".claude-plugin" / "marketplace.json")
    for entry in mkt["plugins"]:
        src = (REPO / entry["source"]).resolve()
        assert (src / ".claude-plugin" / "plugin.json").is_file(), entry["name"]


def test_persona_plugins_depend_on_cc_agora():
    for role in ROLES:
        pj = _load(REPO / "plugin" / "personas" / role / ".claude-plugin" / "plugin.json")
        assert pj["name"] == f"cc-agora-{role}"
        assert pj["dependencies"] == ["cc-agora"]


def test_persona_plugins_have_persona_skill():
    for role in ROLES:
        sk = REPO / "plugin" / "personas" / role / "skills" / "persona" / "SKILL.md"
        text = sk.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "user-invocable: false" in text
