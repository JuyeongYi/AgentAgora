"""CommMatrix unit tests."""
from agent_agora.comm_matrix import CommMatrix


# CSV: header[i] = both the to-destination for row i AND the from-source for column i
# Row 0 (to=Worker1): Worker1->Worker1=0, Worker2->Worker1=0
# Row 1 (to=Worker2): Worker1->Worker2=1, Worker2->Worker2=0
_SIMPLE = "Worker1,Worker2\n0,0\n1,0"


def test_inactive_matrix_allows_all():
    """비활성 매트릭스 — 모든 페어 allow."""
    matrix = CommMatrix()
    assert matrix.active is False
    assert matrix.is_allowed(from_="Worker1", to="Worker2") is True
    assert matrix.is_allowed(from_="anyone", to="anyone_else") is True


def test_active_matrix_whitelist():
    """활성 매트릭스 — weight > 0 만 allow."""
    matrix = CommMatrix()
    matrix.load_csv(_SIMPLE)
    assert matrix.active is True

    assert matrix.is_allowed(from_="Worker1", to="Worker2") is True
    assert matrix.is_allowed(from_="Worker2", to="Worker1") is False
    assert matrix.is_allowed(from_="Worker2", to="Worker2") is False


def test_operator_bypasses_active_matrix():
    """operator:<x>는 매트릭스 활성 여부와 무관하게 dispatch 양방향 allow."""
    matrix = CommMatrix()
    # 워커끼리 일부만 허용되는 매트릭스 로드
    matrix.load_csv(_SIMPLE)
    assert matrix.active

    # 워커→워커: 매트릭스 따름
    assert matrix.is_allowed(from_="Worker1", to="Worker2") is True
    assert matrix.is_allowed(from_="Worker2", to="Worker1") is False

    # 운영자 → 어떤 워커든 allow
    assert matrix.is_allowed(from_="operator:alice", to="Worker2") is True
    assert matrix.is_allowed(from_="operator:bob", to="Worker1") is True

    # 어떤 워커든 → 운영자 allow (답신 경로)
    assert matrix.is_allowed(from_="Worker2", to="operator:alice") is True
    assert matrix.is_allowed(from_="Worker1", to="operator:bob") is True


def test_operator_to_operator_allowed():
    """Two operators can dispatch to each other (sender operator short-circuits)."""
    matrix = CommMatrix()
    matrix.load_csv("Worker1\n0\n")  # active but tiny (1x1 deny-self)
    assert matrix.active
    assert matrix.is_allowed(from_="operator:alice", to="operator:bob") is True
    assert matrix.is_allowed(from_="operator:bob", to="operator:alice") is True


# --- cycles() 진단 (Plan A2) ---
# CSV: cell[i][j] = weight(header[j] -> header[i]). header[i]=행(to), header[j]=열(from).

def test_cycles_acyclic_returns_empty():
    cm = CommMatrix()
    # impl->reviewer->improver 선형 (acyclic)
    # row(to=impl): 0,0,0  row(to=reviewer): impl->reviewer=1  row(to=improver): reviewer->improver=1
    cm.load_csv("impl,reviewer,improver\n0,0,0\n1,0,0\n0,1,0")
    assert cm.cycles() == []


def test_cycles_detects_two_node_cycle():
    cm = CommMatrix()
    # A<->B: row(to=A): A->A=0,B->A=1  row(to=B): A->B=1,B->B=0
    cm.load_csv("A,B\n0,1\n1,0")
    cycles = cm.cycles()
    assert any(set(c) == {"A", "B"} for c in cycles)


def test_cycles_detects_self_loop():
    cm = CommMatrix()
    cm.load_csv("A\n1")  # A->A
    assert any(c == ["A"] for c in cm.cycles())


def test_cycles_empty_when_inactive():
    cm = CommMatrix()
    assert cm.cycles() == []
