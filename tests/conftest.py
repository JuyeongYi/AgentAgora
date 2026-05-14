# tests/conftest.py
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def agora_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".agentagora"
    d.mkdir()
    return d
