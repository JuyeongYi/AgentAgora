import pytest
from agent_agora.errors import AgoraError, ERROR_MESSAGES


def test_comm_matrix_error_codes_present():
    assert {"comm_denied", "comm_matrix_shape_mismatch"} <= set(ERROR_MESSAGES)


def test_comm_denied_message_formats_from_and_to():
    e = AgoraError("comm_denied", from_="Coder1", to="Tester1")
    assert e.code == "comm_denied"
    assert "Coder1" in str(e) and "Tester1" in str(e)


from agent_agora.comm_matrix import CommMatrix, load_comm_matrix

_HUB = "\n".join([
    "Inst1,Coder1,Reviewer1,Tester1",
    "0,1,1,1",
    "1,0,0,0",
    "1,0,0,0",
    "1,0,0,0",
])


def test_fresh_matrix_is_inactive_and_allows_all():
    cm = CommMatrix()
    assert cm.active is False
    assert cm.is_allowed("anyone", "anyone_else") is True


def test_load_csv_activates_and_enforces_hub_and_spoke():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.active is True
    assert cm.is_allowed("Coder1", "Inst1") is True
    assert cm.is_allowed("Inst1", "Inst1") is False
    assert cm.is_allowed("Inst1", "Coder1") is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False
    assert cm.is_allowed("Tester1", "Coder1") is False


def test_unregistered_worker_is_denied():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.is_allowed("Ghost", "Inst1") is False
    assert cm.is_allowed("Inst1", "Ghost") is False


def test_load_csv_rejects_row_count_mismatch():
    cm = CommMatrix()
    bad = "A,B,C\n0,1,1\n1,0,0"
    with pytest.raises(AgoraError) as ei:
        cm.load_csv(bad)
    assert ei.value.code == "comm_matrix_shape_mismatch"


def test_load_csv_rejects_column_count_mismatch():
    cm = CommMatrix()
    bad = "A,B,C\n0,1,1\n1,0\n1,0,0"
    with pytest.raises(AgoraError) as ei:
        cm.load_csv(bad)
    assert ei.value.code == "comm_matrix_shape_mismatch"


def test_load_csv_replaces_prior_matrix_in_place():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    cm.load_csv("A,B\n1,1\n1,1")
    assert cm.is_allowed("A", "B") is True
    assert cm.is_allowed("Coder1", "Inst1") is False


def test_load_comm_matrix_absent_file_returns_inactive(tmp_path):
    cm = load_comm_matrix(tmp_path / "comm-matrix.csv")
    assert cm.active is False
    assert cm.is_allowed("x", "y") is True


def test_load_comm_matrix_present_file_loads(tmp_path):
    p = tmp_path / "comm-matrix.csv"
    p.write_text(_HUB, encoding="utf-8")
    cm = load_comm_matrix(p)
    assert cm.active is True
    assert cm.is_allowed("Reviewer1", "Coder1") is False
