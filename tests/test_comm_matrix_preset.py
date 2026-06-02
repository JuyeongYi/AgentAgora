"""review-gated comm-matrix 프리셋 검증 — coder는 reviewer를 거쳐야 writer에 닿는다.

B-10(reviewer 트리거 신뢰성)의 구조적 강제: 페르소나 자율 준수가 아니라 ACL로
"coder→writer 직접 dispatch"를 comm_denied로 막아 리뷰 게이트를 토폴로지에 박는다.
"""
from pathlib import Path

from agent_agora.comm_matrix import CommMatrix

PRESET = (Path(__file__).resolve().parent.parent
          / "plugin" / "cc-agora-ops" / "presets" / "review-gated.csv")


def _cm() -> CommMatrix:
    cm = CommMatrix()
    cm.load_csv(PRESET.read_text("utf-8"))
    return cm


def test_review_gate_coder_cannot_reach_writer_directly():
    cm = _cm()
    assert cm.is_allowed("coder1", "writer1") is False    # ★ 게이트: 직접 금지
    assert cm.is_allowed("coder1", "reviewer1") is True    # coder→reviewer 허용
    assert cm.is_allowed("reviewer1", "writer1") is True   # reviewer→writer만 허용


def test_pipeline_edges():
    cm = _cm()
    assert cm.is_allowed("planner1", "coder1") is True
    assert cm.is_allowed("coder1", "tester1") is True
    assert cm.is_allowed("tester1", "coder1") is True      # 테스트 실패 → 재작업
    assert cm.is_allowed("reviewer1", "coder1") is True    # 리뷰 지적 → 재작업
    # writer는 종착 — coder/tester로 되돌리지 않는다
    assert cm.is_allowed("writer1", "coder1") is False


def test_everyone_reports_to_orchestrator():
    cm = _cm()
    for role in ("planner1", "coder1", "tester1", "reviewer1", "writer1", "general1"):
        assert cm.is_allowed(role, "orchestrator1") is True


def test_operator_bypass_regardless_of_gate():
    cm = _cm()
    assert cm.is_allowed("operator:alice", "writer1") is True
    assert cm.is_allowed("coder1", "operator:alice") is True


def test_case_insensitive_persona_match():
    cm = _cm()
    assert cm.is_allowed("Coder1", "Writer1") is False     # (?i) — 대소문자 무관
    assert cm.is_allowed("Coder1", "Reviewer1") is True


def test_cycles_diagnostic_runs():
    # tester↔coder, reviewer↔coder 등 의도된 재작업 루프가 있으므로 cycles는 비어있지 않다.
    # (진단 정보일 뿐 — 거부하지 않는다.)
    cm = _cm()
    assert isinstance(cm.cycles(), list)
