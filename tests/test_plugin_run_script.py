"""Validates the cc-agora agora-run-script skill."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugin" / "cc-agora" / "skills" / "agora-run-script" / "SKILL.md"


def test_run_script_skill_exists_with_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "description:" in text
    assert "disable-model-invocation: true" in text


def test_run_script_skill_specifies_channel_launcher():
    text = SKILL.read_text(encoding="utf-8")
    assert "--dangerously-load-development-channels server:agora-channel" in text
    assert "run.ps1" in text
    assert "run.sh" in text
