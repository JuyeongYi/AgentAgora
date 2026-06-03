from agent_agora.provisioning import matrix
from agent_agora.comm_matrix import CommMatrix


TEAM = [
    {"id": "Coder1", "allow": ["Reviewer1"]},
    {"id": "Reviewer1", "allow": [".*"]},
    {"id": "Tester1", "allow": []},
]


def test_csv_header_is_square_node_list():
    csv = matrix.build_csv(TEAM)
    lines = csv.strip().splitlines()
    header = lines[0].split(",")
    # 노드 = 워커 3 + 비-id 정규식 ".*" 1 = 4
    assert header == ["Coder1", "Reviewer1", "Tester1", ".*"]
    # 정사각: 데이터 행 수 == 헤더 길이
    assert len(lines) - 1 == len(header)


def test_csv_roundtrips_through_commmatrix_with_correct_direction():
    csv = matrix.build_csv(TEAM)
    cm = CommMatrix()
    cm.load_csv(csv)
    # Coder1 → Reviewer1 허용, Reviewer1.allow=[".*"]라 역방향도 허용
    assert cm.is_allowed("Coder1", "Reviewer1") is True
    assert cm.is_allowed("Reviewer1", "Coder1") is True
    # Coder1은 Tester1에게 불가(allow에 없음)
    assert cm.is_allowed("Coder1", "Tester1") is False
    # Reviewer1은 .*라 임의 워커에게 가능
    assert cm.is_allowed("Reviewer1", "Tester1") is True
    # Tester1은 allow 없음 → 아무에게도 불가
    assert cm.is_allowed("Tester1", "Coder1") is False
    # self는 미명시면 불가
    assert cm.is_allowed("Coder1", "Coder1") is False


def test_empty_allow_everywhere_blocks_all():
    team = [{"id": "A", "allow": []}, {"id": "B", "allow": []}]
    cm = CommMatrix()
    cm.load_csv(matrix.build_csv(team))
    assert cm.is_allowed("A", "B") is False
    assert cm.is_allowed("B", "A") is False
