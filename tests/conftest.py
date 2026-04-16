# tests/conftest.py
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def agora_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".agentagora"
    d.mkdir()
    return d


@pytest.fixture
def sample_schemas() -> dict:
    return {
        "finding": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "line": {"type": "integer"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["file", "line", "severity"],
        },
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "complete"],
        },
    }


@pytest.fixture
def agora_dir_with_schemas(agora_dir: Path, sample_schemas: dict) -> Path:
    (agora_dir / "schemas.json").write_text(json.dumps(sample_schemas))
    return agora_dir
