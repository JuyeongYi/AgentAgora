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
