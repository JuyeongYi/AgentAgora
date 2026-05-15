"""worker↔worker dispatch ACL — N×N comm matrix (comm-matrix design spec)."""
from __future__ import annotations

from pathlib import Path

from agent_agora.errors import AgoraError


class CommMatrix:
    """worker↔worker dispatch 권한. CSV로 로드. 비활성(파일 없음) 시 all-allow.

    `_allowed[to]` = `to`에게 dispatch가 허용된 `from` instance_id 집합.
    """

    def __init__(self) -> None:
        self._allowed: dict[str, set[str]] = {}
        self.active: bool = False

    def load_csv(self, csv_text: str) -> None:
        """CSV 텍스트(헤더 1줄 + 데이터 N줄, 셀 0/1)를 파싱해 매트릭스를 *제자리 교체*한다.
        shape 불일치 시 AgoraError(comm_matrix_shape_mismatch)."""
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
        allowed: dict[str, set[str]] = {}
        for i, row in enumerate(data):
            cells = [c.strip() for c in row]
            if len(cells) != n:
                raise AgoraError(
                    "comm_matrix_shape_mismatch",
                    detail=f"{i + 1}번째 데이터 행이 {len(cells)}컬럼 (헤더 {n}컬럼)")
            to_label = header[i]
            allowed[to_label] = {header[j] for j in range(n) if cells[j] == "1"}
        self._allowed = allowed
        self.active = True

    def is_allowed(self, from_: str, to: str) -> bool:
        """from_ -> to dispatch가 허용되는가. 비활성이면 항상 True.
        활성이면 strict whitelist — 미등재 from/to는 거부(False)."""
        if not self.active:
            return True
        return from_ in self._allowed.get(to, set())


def load_comm_matrix(path: Path) -> CommMatrix:
    """path의 comm-matrix.csv를 로드한다. 파일이 없으면 비활성 CommMatrix(all-allow)."""
    cm = CommMatrix()
    if path.exists():
        cm.load_csv(path.read_text("utf-8"))
    return cm
