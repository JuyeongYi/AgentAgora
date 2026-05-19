"""Validates the cc-agora plugin hooks manifest (hooks/hooks.json)."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS_JSON = REPO / "plugin" / "cc-agora" / "hooks" / "hooks.json"

# Shell metacharacters that break an unquoted inline `echo` on cmd.exe or a
# POSIX shell. The SessionStart(compact) reminder command must avoid all of
# them (see spec section 4.3).
_FORBIDDEN = set("`;|&<>()$\"'!%^")


def _load() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


def _compact_command() -> str:
    """Extract the command string of the SessionStart compact hook."""
    groups = _load()["hooks"]["SessionStart"]
    compact = [
        g for g in groups if re.fullmatch(g.get("matcher", ""), "compact")
    ]
    cmds = [
        h["command"]
        for g in compact
        for h in g["hooks"]
        if h.get("type") == "command"
    ]
    return cmds[0]


def test_sessionstart_compact_command_hook_exists():
    groups = _load()["hooks"]["SessionStart"]
    compact = [
        g for g in groups if re.fullmatch(g.get("matcher", ""), "compact")
    ]
    assert len(compact) == 1, (
        "exactly one SessionStart group whose matcher (as regex) matches 'compact'"
    )
    cmd_hooks = [h for h in compact[0]["hooks"] if h.get("type") == "command"]
    assert len(cmd_hooks) == 1, "exactly one command-type hook in the compact group"
    assert cmd_hooks[0]["command"].strip(), "compact hook command is non-empty"


def test_sessionstart_compact_matcher_also_covers_clear():
    """The SessionStart hook that fires on 'compact' must also fire on 'clear'."""
    groups = _load()["hooks"]["SessionStart"]
    compact_groups = [
        g for g in groups if re.fullmatch(g.get("matcher", ""), "compact")
    ]
    assert len(compact_groups) == 1, (
        "exactly one SessionStart group whose matcher (as regex) matches 'compact'"
    )
    matcher = compact_groups[0].get("matcher", "")
    assert re.fullmatch(matcher, "clear"), (
        f"SessionStart matcher {matcher!r} does not match 'clear' — "
        "/clear coverage is missing"
    )


def test_compact_command_carries_the_recovery_intent():
    cmd = _compact_command()
    assert "agora.flush" in cmd
    assert "channel-mode worker" in cmd


def test_compact_command_is_free_of_shell_metacharacters():
    cmd = _compact_command()
    found = sorted(_FORBIDDEN & set(cmd))
    assert not found, f"forbidden shell metacharacter(s) in hook command: {found}"
