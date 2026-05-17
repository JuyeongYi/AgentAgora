# comm-matrix v2 — CommMatrix Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `CommMatrix`를 0/1 불리언 ACL에서 0 이상 정수 weight 모델로 확장한다.

**Architecture:** CSV 셀을 정수로 파싱해 `_weights[to][from]`에 담는다. `weight_of`가 신규 조회 API, `is_allowed`는 `weight_of > 0`으로 재정의된다. 정렬 동작(flush)은 이 플랜에서 건드리지 않는다 — Plan 2 소관. 따라서 이 플랜만 머지해도 dispatch 동작은 불변(0/1 CSV 하위호환).

**Tech Stack:** Python 3.13, pytest. spec: `docs/superpowers/specs/2026-05-17-comm-matrix-v2-priority-design.md`.

테스트는 `.venv\Scripts\python.exe -m pytest`로 실행한다 (Python 3.13 환경).

---

### Task 1: `comm_matrix_invalid_cell` 에러 코드

**Files:**
- Modify: `src/agent_agora/errors.py:21-24` (ERROR_MESSAGES dict의 comm-matrix codes 구간)
- Test: `tests/test_v4_comm_matrix.py:5-6` (`test_comm_matrix_error_codes_present`)

- [ ] **Step 1: 실패하는 테스트로 수정**

`tests/test_v4_comm_matrix.py`의 기존 `test_comm_matrix_error_codes_present`를 다음으로 교체:

```python
def test_comm_matrix_error_codes_present():
    assert {"comm_denied", "comm_matrix_shape_mismatch",
            "comm_matrix_invalid_cell"} <= set(ERROR_MESSAGES)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py::test_comm_matrix_error_codes_present -v`
Expected: FAIL — `comm_matrix_invalid_cell`이 `ERROR_MESSAGES`에 없음.

- [ ] **Step 3: 에러 코드 추가**

`src/agent_agora/errors.py`의 `ERROR_MESSAGES`에서 `comm_matrix_shape_mismatch` 줄 다음에 한 줄 추가:

```python
    "comm_matrix_shape_mismatch": "[agora] comm-matrix CSV shape 불일치: {detail}",
    "comm_matrix_invalid_cell": "[agora] comm-matrix CSV 셀 오류: {detail}",
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py::test_comm_matrix_error_codes_present -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/errors.py tests/test_v4_comm_matrix.py
git commit -m "feat: comm_matrix_invalid_cell 에러 코드"
```

---

### Task 2: CommMatrix v2 — 정수 weight 모델

`comm_matrix.py` 전체를 정수 weight 모델로 교체한다. 클래스가 작고 내부 표현(`_allowed` → `_weights`)·`is_allowed`·`snapshot`이 강하게 묶여 있어 한 작업으로 처리한다. `snapshot()`의 반환 형태가 바뀌므로 이를 소비하는 기존 테스트도 같은 작업에서 갱신해야 테스트 스위트가 깨지지 않는다.

**Files:**
- Modify: `src/agent_agora/comm_matrix.py` (전체)
- Test: `tests/test_v4_comm_matrix.py` (신규 테스트 + 기존 snapshot 테스트 갱신)
- Test: `tests/test_admin_routes.py:53-62` (`test_get_returns_matrix_snapshot` 갱신)

- [ ] **Step 1: 신규 weight 테스트 작성 (실패 예상)**

`tests/test_v4_comm_matrix.py`의 `_HUB` 정의 바로 다음에 추가:

```python
_WEIGHTED = "\n".join([
    "Inst1,Coder1,Reviewer1,Tester1",
    "0,3,3,3",
    "10,0,0,0",
    "10,0,0,0",
    "10,0,0,0",
])


def test_load_csv_parses_integer_weights():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    assert cm.weight_of("Coder1", "Inst1") == 3
    assert cm.weight_of("Inst1", "Coder1") == 10
    assert cm.weight_of("Coder1", "Coder1") == 0


def test_weight_of_inactive_matrix_is_zero():
    cm = CommMatrix()
    assert cm.weight_of("anyone", "anyone_else") == 0


def test_weight_of_unlisted_pair_is_zero():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    assert cm.weight_of("Ghost", "Inst1") == 0
    assert cm.weight_of("Inst1", "Ghost") == 0


def test_is_allowed_equals_weight_positive():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    assert cm.is_allowed("Coder1", "Inst1") is True   # weight 3
    assert cm.is_allowed("Coder1", "Coder1") is False  # weight 0


def test_zero_one_csv_still_works():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    assert cm.weight_of("Coder1", "Inst1") == 1
    assert cm.is_allowed("Coder1", "Inst1") is True
    assert cm.is_allowed("Inst1", "Inst1") is False


def test_load_csv_rejects_negative_cell():
    cm = CommMatrix()
    with pytest.raises(AgoraError) as ei:
        cm.load_csv("A,B\n0,-1\n1,0")
    assert ei.value.code == "comm_matrix_invalid_cell"


def test_load_csv_rejects_noninteger_cell():
    cm = CommMatrix()
    with pytest.raises(AgoraError) as ei:
        cm.load_csv("A,B\n0,x\n1,0")
    assert ei.value.code == "comm_matrix_invalid_cell"


def test_snapshot_returns_weight_map():
    cm = CommMatrix()
    cm.load_csv(_WEIGHTED)
    snap = cm.snapshot()
    assert snap["Inst1"] == {"Inst1": 0, "Coder1": 3, "Reviewer1": 3, "Tester1": 3}
    assert snap["Coder1"] == {"Inst1": 10, "Coder1": 0, "Reviewer1": 0, "Tester1": 0}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -k "weight or zero_one or negative_cell or noninteger_cell" -v`
Expected: FAIL — `CommMatrix`에 `weight_of` 속성 없음.

- [ ] **Step 3: comm_matrix.py 전체 교체**

`src/agent_agora/comm_matrix.py` 전체를 아래로 교체:

```python
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
        """from_→to 엣지의 정수 weight. 비활성이면 0(평탄).
        활성이면 셀 값, 미등재 쌍은 0."""
        if not self.active:
            return 0
        return self._weights.get(to, {}).get(from_, 0)

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
```

- [ ] **Step 4: 신규 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -k "weight or zero_one or negative_cell or noninteger_cell" -v`
Expected: PASS

- [ ] **Step 5: snapshot 형태가 바뀐 기존 테스트 갱신**

`tests/test_v4_comm_matrix.py`의 기존 `test_snapshot_returns_sorted_allowed_map`를 삭제한다 (Step 1에서 추가한 `test_snapshot_returns_weight_map`가 대체). `test_snapshot_inactive_is_empty`는 그대로 둔다 — `_weights`가 비어 있으면 여전히 `{}`.

`tests/test_admin_routes.py`의 `test_get_returns_matrix_snapshot` 마지막 assert를 교체:

```python
def test_get_returns_matrix_snapshot():
    cm = CommMatrix()
    cm.load_csv(_HUB)
    r = _client(cm).get("/admin/comm-matrix",
                        headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["matrix"]["Coder1"] == {"Inst1": 1, "Coder1": 0}
```

(`_HUB`는 `"Inst1,Coder1\n0,1\n1,0\n"` — `Coder1` 행의 from `Inst1`=1, `Coder1`=0.)

`admin_routes.py`는 변경하지 않는다 — GET 응답이 `comm_matrix.snapshot()`을 그대로 직렬화하므로 형태 변경이 자동 반영된다.

- [ ] **Step 6: comm-matrix 전체 + admin 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py tests/test_admin_routes.py -v`
Expected: 전부 PASS. (`comm_denied`·hub-and-spoke·broadcast 테스트는 `0/1` CSV 하위호환으로 변경 없이 통과해야 한다.)

- [ ] **Step 7: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS — `is_allowed` 시맨틱이 0/1 CSV에 대해 불변이라 dispatcher 테스트도 그대로 통과.

- [ ] **Step 8: 커밋**

```bash
git add src/agent_agora/comm_matrix.py tests/test_v4_comm_matrix.py tests/test_admin_routes.py
git commit -m "feat: CommMatrix v2 — 정수 weight 모델"
```

---

## 완료 기준

- `CommMatrix.weight_of(from_, to)` 가 정수 weight를 반환한다.
- `is_allowed` 가 활성 매트릭스에서 `weight_of > 0` 과 동치다.
- 기존 `0/1` CSV가 변경 없이 동작한다 (`1`→weight 1).
- 음수·비정수 셀이 `comm_matrix_invalid_cell` 로 거부된다.
- `snapshot()`·admin GET이 `{to:{from:weight}}` 형태다.
- 전체 테스트 스위트 통과.
