# tests/conftest.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make plugin script dirs importable for test_plugin_* modules.
# payload.py lives in cc-agora; spawn.py / spawn_team.py / role_policy.py / comm_matrix.py
# live in cc-agora-ops. Both dirs use a flat layout (no package), so each must be on
# sys.path before its modules can be imported.
for _rel in ("cc-agora/scripts", "cc-agora-ops/scripts"):
    _d = Path(__file__).resolve().parent.parent / "plugin" / _rel
    if _d.is_dir() and str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


@pytest.fixture
def agora_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".agentagora"
    d.mkdir()
    return d


from _helpers import make_schema_registry  # noqa: E402


@pytest.fixture
def schema_registry():
    return make_schema_registry()


from agent_agora.registry import BotRegistry  # noqa: E402


@pytest.fixture
def bot_registry():
    return BotRegistry()


from agent_agora.comm_matrix import CommMatrix  # noqa: E402


@pytest.fixture
def comm_matrix():
    return CommMatrix()
