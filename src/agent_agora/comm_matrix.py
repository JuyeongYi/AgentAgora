"""worker↔worker dispatch ACL — N×N comm matrix, 정규식 헤더."""
from __future__ import annotations

import re
from pathlib import Path

from agent_agora.errors import AgoraError


class CommMatrix:
    """worker↔worker dispatch 권한 + 우선순위 weight. CSV로 로드.
    비활성(파일 없음) 시 all-allow.

    CSV 헤더(행·열 라벨)는 정규식 패턴이다. 인스턴스 id를 re.fullmatch로
    각 패턴에 대조한다. 여러 패턴이 동시 매칭하면 max weight를 택한다.
    `_weights[to_pat][from_pat]` = `from_pat`→`to_pat` 엣지의 정수 weight.
    """

    def __init__(self) -> None:
        self._weights: dict[str, dict[str, int]] = {}
        self._compiled: dict[str, re.Pattern[str]] = {}
        self.active: bool = False

    def load_csv(self, csv_text: str) -> None:
        """CSV(헤더 1줄 + 데이터 N줄, 셀 0 이상 정수, 헤더는 정규식)를 파싱해
        매트릭스를 *제자리 교체*한다. shape 불일치 → AgoraError
        (comm_matrix_shape_mismatch), 비정수·음수 셀 → comm_matrix_invalid_cell,
        컴파일 불가 헤더 → comm_matrix_invalid_pattern."""
        rows = [line.split(",") for line in csv_text.splitlines() if line.strip()]
        if not rows:
            raise AgoraError("comm_matrix_shape_mismatch", detail="빈 CSV")
        header = [h.strip() for h in rows[0]]
        n = len(header)
        data = rows[1:]
        if len(data) != n:
            raise AgoraError(
                "comm_matrix_shape_mismatch",
                detail=f"데이터 {len(data)}행 != 헤더 {n}컬럼")
        compiled: dict[str, re.Pattern[str]] = {}
        for h in header:
            try:
                compiled[h] = re.compile(h)
            except re.error as e:
                raise AgoraError(
                    "comm_matrix_invalid_pattern",
                    detail=f"헤더 '{h}'는 정규식이 아님: {e}") from None
        weights: dict[str, dict[str, int]] = {}
        for i, row in enumerate(data):
            cells = [c.strip() for c in row]
            if len(cells) != n:
                raise AgoraError(
                    "comm_matrix_shape_mismatch",
                    detail=f"{i + 1}번째 데이터 행이 {len(cells)}컬럼 (헤더 {n}컬럼)")
            row_weights: dict[str, int] = {}
            for j in range(n):
                try:
                    w = int(cells[j])
                except ValueError:
                    raise AgoraError(
                        "comm_matrix_invalid_cell",
                        detail=f"{i + 1}번째 행 {j + 1}번째 셀 '{cells[j]}'는 정수가 아님",
                    ) from None
                if w < 0:
                    raise AgoraError(
                        "comm_matrix_invalid_cell",
                        detail=f"{i + 1}번째 행 {j + 1}번째 셀 {w}는 음수")
                row_weights[header[j]] = w
            weights[header[i]] = row_weights
        self._weights = weights
        self._compiled = compiled
        self.active = True

    def weight_of(self, from_: str, to: str) -> int:
        """from_→to 엣지의 정수 weight. 비활성이면 0.
        활성이면 to에 fullmatch되는 행-패턴 × from_에 fullmatch되는 열-패턴의
        교차 셀 중 max weight. 매칭 없으면 0."""
        if not self.active:
            return 0
        best = 0
        for to_pat, row in self._weights.items():
            if self._compiled[to_pat].fullmatch(to) is None:
                continue
            for from_pat, w in row.items():
                if w > best and self._compiled[from_pat].fullmatch(from_) is not None:
                    best = w
        return best

    def is_allowed(self, from_: str, to: str) -> bool:
        """from_→to dispatch가 허용되는가. 비활성이면 항상 True.
        활성이면 weight_of > 0 — strict whitelist."""
        if not self.active:
            return True
        return self.weight_of(from_, to) > 0

    def snapshot(self) -> dict[str, dict[str, int]]:
        """현재 매트릭스를 {to_pattern: {from_pattern: weight}} dict로 반환 (조회용)."""
        return {to: dict(froms) for to, froms in self._weights.items()}


def load_comm_matrix(path: Path) -> CommMatrix:
    """path의 comm-matrix.csv를 로드한다. 파일이 없으면 비활성 CommMatrix(all-allow)."""
    cm = CommMatrix()
    if path.exists():
        cm.load_csv(path.read_text("utf-8"))
    return cm
