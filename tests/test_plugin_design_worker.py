"""Validates the cc-agora-ops agora-design-worker skill."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = (REPO / "plugin" / "cc-agora-ops" / "skills"
         / "agora-design-worker" / "SKILL.md")


def test_design_worker_skill_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "description:" in text
    assert "disable-model-invocation: true" in text


def test_design_worker_skill_references_spawn_and_run_script():
    text = SKILL.read_text(encoding="utf-8")
    assert "--persona-file" in text
    assert "spawn.py" in text
    assert "agora-run-script" in text
