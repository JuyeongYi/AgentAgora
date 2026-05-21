"""Validates the AgentAgora marketplace manifest and persona plugin manifests."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO / "plugin"
ROLES = ("orchestrator", "coder", "reviewer", "tester", "writer", "planner", "general")
MVC_ROLES = ("model", "view", "controller")


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


def test_cc_agora_ops_depends_on_cc_agora():
    pj = _load(REPO / "plugin" / "cc-agora-ops" / ".claude-plugin" / "plugin.json")
    assert pj["dependencies"] == ["cc-agora"]


# --- MVC persona plugin tests (plugin/.claude-plugin/marketplace.json) ---

def _load_plugin_marketplace() -> dict:
    return _load(PLUGIN_DIR / ".claude-plugin" / "marketplace.json")


def test_plugin_marketplace_contains_mvc_plugins():
    mkt = _load_plugin_marketplace()
    names = {p["name"] for p in mkt["plugins"]}
    for role in MVC_ROLES:
        assert f"superpowers-{role}" in names, f"superpowers-{role} missing from plugin marketplace"


def test_plugin_marketplace_mvc_sources_exist():
    mkt = _load_plugin_marketplace()
    for role in MVC_ROLES:
        entry = next((p for p in mkt["plugins"] if p["name"] == f"superpowers-{role}"), None)
        assert entry is not None, f"superpowers-{role} not in plugin marketplace"
        src = (PLUGIN_DIR / entry["source"].lstrip("./")).resolve()
        assert (src / ".claude-plugin" / "plugin.json").is_file(), (
            f"superpowers-{role}: source plugin.json missing at {src}"
        )


def test_mvc_plugin_jsons_valid():
    for role in MVC_ROLES:
        pj = _load(PLUGIN_DIR / "superpowers" / f"superpowers-{role}" / ".claude-plugin" / "plugin.json")
        assert pj["name"] == f"superpowers-{role}"
        assert pj["version"] == "0.1.0"
        assert pj["dependencies"] == ["superpowers-base"]


def test_mvc_persona_skills_exist():
    for role in MVC_ROLES:
        sk = PLUGIN_DIR / "superpowers" / f"superpowers-{role}" / "skills" / "persona" / "SKILL.md"
        assert sk.is_file(), f"superpowers-{role} SKILL.md missing"
        text = sk.read_text(encoding="utf-8")
        assert text.startswith("---"), f"superpowers-{role} SKILL.md missing frontmatter"
        assert "user-invocable: false" in text, f"superpowers-{role} SKILL.md missing user-invocable: false"


def test_plugin_marketplace_total_count():
    mkt = _load_plugin_marketplace()
    # Was 18 before MVC (including cc-agora-structure), now 21.
    assert len(mkt["plugins"]) == 21, (
        f"Expected 21 plugins in plugin marketplace, got {len(mkt['plugins'])}"
    )
