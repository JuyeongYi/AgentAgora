# tests/conftest.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make plugin/cc-agora/scripts/ importable for test_plugin_* modules.
# spawn.py / spawn_team.py use ``from role_policy import ...`` (flat layout, not a
# package), so the scripts dir must be on sys.path before they can be imported.
_PLUGIN_SCRIPTS = Path(__file__).resolve().parent.parent / "plugin" / "cc-agora" / "scripts"
if _PLUGIN_SCRIPTS.is_dir() and str(_PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_SCRIPTS))

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


from agent_agora.bot_registry import BotRegistry  # noqa: E402


@pytest.fixture
def bot_registry():
    return BotRegistry()


from agent_agora.comm_matrix import CommMatrix  # noqa: E402


@pytest.fixture
def comm_matrix():
    return CommMatrix()
