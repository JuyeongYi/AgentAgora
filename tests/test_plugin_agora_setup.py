"""Validates the cc-agora-ops agora-setup skill."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugin" / "cc-agora-ops" / "skills" / "agora-setup" / "SKILL.md"


def test_agora_setup_skill_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "description:" in text
    assert "disable-model-invocation: true" in text


def test_agora_setup_skill_covers_all_steps():
    text = SKILL.read_text(encoding="utf-8")
    # 5단계 산출물
    assert "run-cc-agora.ps1" in text and "run-cc-agora.sh" in text
    assert "schemas.jsonl" in text
    assert "comm-matrix.csv" in text
    assert "file-policy.json" in text
    # 5단계는 agora-design-worker에 위임
    assert "agora-design-worker" in text


def test_agora_setup_skill_documents_launch_order():
    text = SKILL.read_text(encoding="utf-8")
    # 서버 먼저, 워커 나중 — MCP 등록 순서 보장
    assert "run-cc-agora" in text
    assert "agent_agora" in text
