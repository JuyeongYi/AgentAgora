import io
from agent_agora.provisioning import tui


def test_toggle_step_navigation_wraps():
    # down: 0 -> 1
    c, ch, done = tui._toggle_step(3, 0, set(), "down")
    assert c == 1 and ch == set() and done is False
    # up at 0 wraps to last
    c, ch, done = tui._toggle_step(3, 0, set(), "up")
    assert c == 2 and done is False


def test_toggle_step_space_toggles_and_enter_done():
    c, ch, done = tui._toggle_step(3, 1, set(), "space")
    assert ch == {1} and done is False
    # space again un-checks
    c, ch, done = tui._toggle_step(3, 1, {1}, "space")
    assert ch == set()
    # enter -> done
    c, ch, done = tui._toggle_step(3, 2, {1}, "enter")
    assert done is True


def test_checkbox_select_numbered_fallback_for_non_tty():
    # io.StringIO is not a tty -> numbered fallback
    stdin = io.StringIO("1,3\n")
    stdout = io.StringIO()
    picked = tui.checkbox_select(["coder", "reviewer", "tester"],
                                 stdin=stdin, stdout=stdout, prompt="role")
    assert picked == ["coder", "tester"]


def test_checkbox_select_fallback_empty_returns_empty():
    picked = tui.checkbox_select(["a", "b"], stdin=io.StringIO("\n"), stdout=io.StringIO())
    assert picked == []


def test_checkbox_select_fallback_ignores_out_of_range():
    picked = tui.checkbox_select(["a", "b"], stdin=io.StringIO("2,9,x\n"), stdout=io.StringIO())
    assert picked == ["b"]
