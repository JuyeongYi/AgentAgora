"""worker↔worker dispatch ACL — N×N comm matrix (comm-matrix v2: 정수 weight)."""
from __future__ import annotations

from pathlib import Path

from agent_agora.errors import AgoraError


class CommMatrix:
    """worker↔worker dispatch 권한 + 우선순위 weight. CSV로 로드.
    비활성(파일 없음) 시 all-allow, weight 평탄(0).

    `_weights[to][from]` = `from`→`to` 엣지의 정수 weight.
    `0`=금지, `>0`=허용 + 그 값이 수신자 인박스 처리 우선순위(클수록 먼저).
    """

    def __init__(self) -> None:
        self._weights: dict[str, dict[str, int]] = {}
        self.active: bool = False

    def load_csv(self, csv_text: str) -> None:
        """CSV(헤더 1줄 + 데이터 N줄, 셀 0 이상 정수)를 파싱해 매트릭스를
        *제자리 교체*한다. shape 불일치 시 AgoraError(comm_matrix_shape_mismatch),
        비정수·음수 셀은 AgoraError(comm_matrix_invalid_cell)."""
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
        self.active = True

    def weight_of(self, from_: str, to: str) -> int:
        """from_→to 엣지의 정수 weight. 비활성이면 0.
        활성이면 셀 값, 미등재 to/from은 '*' 와일드카드 행/열로 폴백, 없으면 0."""
        if not self.active:
            return 0
        row = self._weights.get(to)
        if row is None:
            row = self._weights.get("*", {})   # 미등재 to → '*' 행
        if from_ in row:
            return row[from_]
        return row.get("*", 0)                  # 미등재 from → 행의 '*' 열, 없으면 0

    def is_allowed(self, from_: str, to: str) -> bool:
        """from_→to dispatch가 허용되는가. 비활성이면 항상 True.
        활성이면 weight_of > 0 — strict whitelist(미등재/0 셀은 거부)."""
        if not self.active:
            return True
        return self.weight_of(from_, to) > 0

    def snapshot(self) -> dict[str, dict[str, int]]:
        """현재 매트릭스를 {to: {from: weight}} dict로 반환 (조회용)."""
        return {to: dict(froms) for to, froms in self._weights.items()}


def load_comm_matrix(path: Path) -> CommMatrix:
    """path의 comm-matrix.csv를 로드한다. 파일이 없으면 비활성 CommMatrix(all-allow)."""
    cm = CommMatrix()
    if path.exists():
        cm.load_csv(path.read_text("utf-8"))
    return cm
