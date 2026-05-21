"""Plugin metadata + marketplace + bundled .mcp.json validation for cc-agora-structure."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugin" / "cc-agora-structure"


def test_plugin_json_valid():
    data = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "cc-agora-structure"
    assert isinstance(data["version"], str)
    assert data["dependencies"] == ["cc-agora"]


def test_bundled_mcp_declares_code_review_graph():
    data = json.loads((PLUGIN_DIR / ".mcp.json").read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert "code-review-graph" in servers
    crg = servers["code-review-graph"]
    assert crg["command"] == "code-review-graph"
    assert crg["args"] == ["serve"]


def test_marketplace_contains_structure_plugin():
    marketplace = json.loads(
        (REPO_ROOT / "plugin" / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    names = [p["name"] for p in marketplace["plugins"]]
    assert "cc-agora-structure" in names
    entry = next(p for p in marketplace["plugins"] if p["name"] == "cc-agora-structure")
    assert entry["source"] == "./cc-agora-structure"


def test_readme_exists():
    assert (PLUGIN_DIR / "README.md").is_file()


def test_slash_commands_exist():
    cmd_dir = PLUGIN_DIR / "commands"
    for name in ("agora-structure-analyze.md", "agora-structure-spawn.md"):
        assert (cmd_dir / name).is_file(), f"missing slash command: {cmd_dir / name}"


def test_scripts_exist():
    sc = PLUGIN_DIR / "scripts"
    for name in ("partition.py", "structure_spawn.py"):
        assert (sc / name).is_file(), f"missing script: {sc / name}"


def test_templates_exist():
    t = PLUGIN_DIR / "templates"
    for name in (
        "worker-claude.md.template",
        "worker-mcp.json.template",
        "worker-settings.local.json.template",
        "structure-manifest.json.example",
    ):
        assert (t / name).is_file(), f"missing template: {name}"


def test_manifest_example_is_valid_json_and_loads_via_load_manifest(tmp_path):
    import sys
    SCRIPTS = PLUGIN_DIR / "scripts"
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from structure_spawn import load_manifest  # type: ignore
    example = PLUGIN_DIR / "templates" / "structure-manifest.json.example"
    data = json.loads(example.read_text(encoding="utf-8"))
    # The example uses a placeholder repo path — patch it for load_manifest.
    data["repo"] = "C:/x"
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    m = load_manifest(p)
    assert m.version == 1
    assert len(m.partitions) >= 1
