# comm-matrix `*` fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `CommMatrix.weight_of`가 `*` 와일드카드 행/열을 미등재 `from`/`to`의 fallback으로 사용하게 한다.

**Architecture:** `*`는 CSV의 평범한 라벨이라 `load_csv`·shape 검증은 무변경 — `_weights["*"]`·`_weights[to]["*"]`가 자연히 채워진다. `weight_of` 한 메서드만 고쳐 미등재 `to`는 `*` 행, 미등재 `from`은 행의 `*` 열로 폴백한다. `*` 없는 CSV는 동작 불변(strict whitelist). 변경이 작아 단일 태스크.

**Tech Stack:** Python 3.13, pytest. 테스트는 `.venv\Scripts\python.exe -m pytest`. 셸 PowerShell. Pyright 진단은 무시(pytest 정답).

spec: `docs/superpowers/specs/2026-05-18-comm-matrix-fallback-design.md`.

---

### Task 1: `weight_of` `*` fallback

**Files:**
- Modify: `src/agent_agora/comm_matrix.py`
- Test: `tests/test_v4_comm_matrix.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_v4_comm_matrix.py`에 추가. `CommMatrix`·`load_csv`는 파일에 이미 import돼 있다.

```python
# header에 *(from 와일드카드 열), 첫 데이터 행에 *(to 와일드카드 행)
_STAR = "\n".join([
    "*,Inst1,Coder1",
    "0,2,2",      # to=*       — 미등재 수신자 fallback 행
    "5,0,1",      # to=Inst1
    "5,1,0",      # to=Coder1
])


def test_star_row_fallback_for_unlisted_to():
    cm = CommMatrix()
    cm.load_csv(_STAR)
    # Ghost(미등재 to), Inst1(등재 from) → '*' 행의 Inst1 열 = 2
    assert cm.weight_of("Inst1", "Ghost") == 2
    assert cm.weight_of("Coder1", "Ghost") == 2


def test_star_column_fallback_for_unlisted_from():
    cm = CommMatrix()
    cm.load_csv(_STAR)
    # Ghost(미등재 from) → Inst1 행의 '*' 열 = 5
    assert cm.weight_of("Ghost", "Inst1") == 5
    assert cm.weight_of("Ghost", "Coder1") == 5


def test_star_star_catch_all():
    cm = CommMatrix()
    cm.load_csv(_STAR)
    # 둘 다 미등재 → '*' 행의 '*' 열 = 0
    assert cm.weight_of("Ghost", "Phantom") == 0


def test_explicit_cell_beats_star():
    cm = CommMatrix()
    cm.load_csv(_STAR)
    # 등재 to·from은 '*'로 폴백하지 않는다
    assert cm.weight_of("Inst1", "Coder1") == 1
    assert cm.weight_of("Coder1", "Coder1") == 0


def test_star_fallback_feeds_is_allowed():
    cm = CommMatrix()
    cm.load_csv(_STAR)
    assert cm.is_allowed("Inst1", "Ghost") is True   # weight 2 > 0
    assert cm.is_allowed("Ghost", "Phantom") is False  # weight 0


def test_no_star_csv_stays_strict_whitelist():
    cm = CommMatrix()
    cm.load_csv("Inst1,Coder1\n0,1\n1,0")  # '*' 없음
    assert cm.weight_of("Ghost", "Inst1") == 0
    assert cm.is_allowed("Ghost", "Inst1") is False
    assert cm.is_allowed("Inst1", "Ghost") is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -k "star" -v`
Expected: `test_star_row_fallback_for_unlisted_to`·`test_star_column_fallback_for_unlisted_from`·`test_star_star_catch_all`·`test_star_fallback_feeds_is_allowed`가 FAIL — 현 `weight_of`는 미등재 to/from에 무조건 0을 반환한다. (`test_explicit_cell_beats_star`·`test_no_star_csv_stays_strict_whitelist`는 현 동작으로도 통과할 수 있다.)

- [ ] **Step 3: `weight_of`에 fallback 로직**

`src/agent_agora/comm_matrix.py`의 `weight_of` 메서드를 교체한다. 현재:

```python
    def weight_of(self, from_: str, to: str) -> int:
        """from_→to 엣지의 정수 weight. 비활성이면 0(평탄).
        활성이면 셀 값, 미등재 쌍은 0."""
        if not self.active:
            return 0
        return self._weights.get(to, {}).get(from_, 0)
```

변경 후:

```python
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
```

`load_csv`·`is_allowed`·`snapshot`은 건드리지 않는다 — `*`는 평범한 라벨이라 파싱이
그대로 처리하고, `is_allowed`는 `weight_of`를 호출하므로 fallback이 자동 반영된다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_v4_comm_matrix.py -k "star" -v`
Expected: 6개 신규 테스트 전부 PASS.

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS — `*` 없는 기존 CSV는 `_weights.get("*")`가 없어 `weight_of`가
현 strict whitelist와 동일하게 동작하므로 기존 comm-matrix·flush 정렬 테스트 불변.

- [ ] **Step 6: 커밋**

```bash
git add src/agent_agora/comm_matrix.py tests/test_v4_comm_matrix.py
git commit -m "feat: comm-matrix — * 와일드카드 fallback 행/열"
```

---

## 완료 기준

- `weight_of`가 미등재 `to`는 `*` 행, 미등재 `from`은 행의 `*` 열로 폴백한다.
- `*`/`*`는 catch-all. 명시 셀은 `*`보다 우선.
- `is_allowed`가 `*` fallback weight를 따른다.
- `*` 없는 CSV는 strict whitelist 동작 불변.
- 전체 테스트 스위트 통과.
