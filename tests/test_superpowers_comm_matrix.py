"""superpowers routing-bot comm-matrix.csv regression test — revised-workflow edges."""
from pathlib import Path

from agent_agora.comm_matrix import CommMatrix

_CSV = (Path(__file__).resolve().parent.parent
        / "plugin" / "superpowers" / "routing-bot" / "comm-matrix.csv")


def _matrix() -> CommMatrix:
    # CommMatrix uses instance method load_csv(text), not a classmethod.
    cm = CommMatrix()
    cm.load_csv(_CSV.read_text(encoding="utf-8"))
    return cm


# (from_id, to_id) edges that MUST be allowed
_ALLOWED = [
    ("sp-planner-1", "sp-router-1"),
    ("sp-router-1", "sp-implementer-1"),
    ("sp-implementer-1", "sp-tester-1"),
    ("sp-tester-1", "sp-implementer-1"),
    ("sp-tester-1", "sp-debugger-1"),
    ("sp-debugger-1", "sp-tester-1"),
    ("sp-debugger-1", "sp-planner-1"),
    ("sp-implementer-1", "sp-reviewer-1"),
    ("sp-reviewer-1", "sp-implementer-1"),
    ("sp-reviewer-1", "sp-planner-1"),
    ("sp-implementer-1", "sp-improver-1"),
    ("sp-improver-1", "sp-planner-1"),
]

# edges that MUST be forbidden in the revised design
_FORBIDDEN = [
    ("sp-implementer-1", "sp-debugger-1"),
    ("sp-debugger-1", "sp-implementer-1"),
    ("sp-tester-1", "sp-reviewer-1"),
]


def test_revised_workflow_allowed_edges():
    m = _matrix()
    for frm, to in _ALLOWED:
        assert m.is_allowed(frm, to), f"edge must be allowed: {frm} -> {to}"


def test_revised_workflow_forbidden_edges():
    m = _matrix()
    for frm, to in _FORBIDDEN:
        assert not m.is_allowed(frm, to), f"edge must be forbidden: {frm} -> {to}"
