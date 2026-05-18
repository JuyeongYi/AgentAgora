# comm-matrix · file-policy 정규식 규칙 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** comm-matrix CSV 헤더와 file-policy worker 키를 정확한 인스턴스명 대신 정규식 패턴(`re.fullmatch`)으로 해석하고, 다중 매칭 시 권한 높은 쪽(comm-matrix=max weight, file-policy=OR)을 택한다.

**Architecture:** 설계 spec `docs/superpowers/specs/2026-05-18-comm-matrix-file-policy-regex-design.md` 기준. `CommMatrix`·`FilePolicy`는 load 시 헤더/키를 `re.compile`하고, 조회 시 인스턴스 id를 모든 패턴에 `fullmatch`해 매칭 셀/항목을 모은다. `*` 와일드카드 폐지(→`.*`), file-policy `fallback` 필드 폐지(→`.*` 키).

**Tech Stack:** Python 3.13, `re` 표준 라이브러리, pytest. 테스트 실행: `uv run --extra dev python -m pytest`.

---

## 파일 구조

```
src/agent_agora/errors.py            수정 — comm_matrix_invalid_pattern 코드 추가
src/agent_agora/comm_matrix.py       수정 — 헤더 정규식 컴파일, weight_of max 매칭
src/agent_agora/file_policy.py       수정 — worker 키 정규식, can_* OR, fallback 폐지
tests/test_v4_comm_matrix.py         수정 — 정규식 테스트 추가, _STAR 테스트 교체
tests/test_file_policy.py            수정 — 정규식 테스트 추가, _POLICY/fallback 교체
plugin/cc-agora-ops/skills/agora-make-comm-matrix/SKILL.md   수정 — * → .*
plugin/cc-agora-ops/skills/agora-setup/SKILL.md              수정 — * → .*
docs/comm-matrix.md                  수정 — 정규식 규칙 문서화
```

`CommMatrix`·`FilePolicy`는 각각 한 파일에 닫혀 있고 인터페이스(`weight_of`·`is_allowed`·`snapshot` / `can_upload`·`can_download`·`snapshot`)는 불변 — 호출부(`dispatcher.py`·`file_routes.py`) 변경 없음.

---

## Task 1: errors.py — `comm_matrix_invalid_pattern` 코드

**Files:**
- Modify: `src/agent_agora/errors.py`
- Test: `tests/test_v4_comm_matrix.py`

- [ ] **Step 1: 에러 코드 존재 테스트를 갱신 (실패 확인용)**

`tests/test_v4_comm_matrix.py`의 `test_comm_matrix_error_codes_present`(5–7행)를 아래로 교체:

```python
def test_comm_matrix_error_codes_present():
    assert {"comm_denied", "comm_matrix_shape_mismatch",
            "comm_matrix_invalid_cell", "comm_matrix_invalid_pattern"} <= set(ERROR_MESSAGES)
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `uv run --extra dev python -m pytest tests/test_v4_comm_matrix.py::test_comm_matrix_error_codes_present -q`
Expected: FAIL — `comm_matrix_invalid_pattern`이 `ERROR_MESSAGES`에 없음.

- [ ] **Step 3: 에러 코드 추가**

`src/agent_agora/errors.py`의 `ERROR_MESSAGES`에서 `comm_matrix_invalid_cell` 줄 바로 다음에 추가:

```python
    "comm_matrix_invalid_cell": "[agora] comm-matrix CSV 셀 오류: {detail}",
    "comm_matrix_invalid_pattern": "[agora] comm-matrix CSV 정규식 헤더 오류: {detail}",
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `uv run --extra dev python -m pytest tests/test_v4_comm_matrix.py::test_comm_matrix_error_codes_present -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/errors.py tests/test_v4_comm_matrix.py
git commit -m "feat: comm_matrix_invalid_pattern 에러 코드 추가"
```

---

## Task 2: comm_matrix.py — 정규식 헤더 매칭

**Files:**
- Modify: `src/agent_agora/comm_matrix.py` (전체 교체)
- Test: `tests/test_v4_comm_matrix.py`

- [ ] **Step 1: 정규식 동작 테스트 추가 (실패 확인용)**

`tests/test_v4_comm_matrix.py`에서 `_STAR` 상수(443–449행)와 그것을 쓰는 5개 테스트 — `test_star_row_fallback_for_unlisted_to`, `test_star_column_fallback_for_unlisted_from`, `test_star_star_catch_all`, `test_explicit_cell_beats_star`, `test_star_fallback_feeds_is_allowed` (452–487행) — 를 **삭제**하고 그 자리에 아래를 넣는다. `test_no_star_csv_stays_strict_whitelist`(490–495행)는 그대로 둔다(`*` 미사용 — 정확명은 자명한 정규식).

```python
_REGEX_GROUP = "hub,coder-.*\n0,3\n7,0"


def test_regex_header_matches_group():
    cm = CommMatrix()
    cm.load_csv(_REGEX_GROUP)
    # coder-.* 행/열은 coder-N 전체에 fullmatch
    assert cm.weight_of("coder-1", "hub") == 3
    assert cm.weight_of("coder-2", "hub") == 3
    assert cm.weight_of("hub", "coder-9") == 7


def test_regex_fullmatch_not_partial():
    cm = CommMatrix()
    cm.load_csv(_REGEX_GROUP)
    # 'decoder'는 coder-.* 그룹이 아님 (fullmatch — 부분 매칭 안 함)
    assert cm.weight_of("decoder", "hub") == 0


def test_dotstar_catch_all_column():
    cm = CommMatrix()
    # 행 .*(catch-all), hub / 데이터: to=.* 행 전부 0, to=hub 행 from=.* 열 5
    cm.load_csv(".*,hub\n0,0\n5,0")
    # 미등재 from은 '.*' from-열을 통해 hub에 도달
    assert cm.weight_of("ghost", "hub") == 5
    assert cm.weight_of("anyone", "hub") == 5


def test_multi_match_takes_max_weight():
    cm = CommMatrix()
    # 명시적 coder-1 to-행은 전부 0, 넓은 coder-.* to-행은 8
    cm.load_csv("coder-1,coder-.*\n0,0\n8,8")
    # coder-1은 두 행 모두에 매칭 — 높은 weight(8)가 이긴다
    assert cm.weight_of("coder-1", "coder-1") == 8


def test_load_csv_rejects_invalid_regex_header():
    cm = CommMatrix()
    with pytest.raises(AgoraError) as ei:
        cm.load_csv("A,*\n0,0\n0,0")
    assert ei.value.code == "comm_matrix_invalid_pattern"
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `uv run --extra dev python -m pytest tests/test_v4_comm_matrix.py -q`
Expected: 신규 5개 테스트 FAIL (현행 `weight_of`는 정확명 dict 조회라 `coder-.*` 패턴을 리터럴로 취급).

- [ ] **Step 3: comm_matrix.py 전체 교체**

`src/agent_agora/comm_matrix.py`를 아래 내용으로 교체:

```python
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
```

- [ ] **Step 4: comm-matrix 테스트 전체 실행해 통과 확인**

Run: `uv run --extra dev python -m pytest tests/test_v4_comm_matrix.py -q`
Expected: PASS — 신규 5개 테스트 + 기존 테스트(정확명·shape·weight 정렬 등) 전부 통과. 정확명 헤더(`Inst1`,`Coder1` 등)는 자명한 정규식이라 기존 테스트가 그대로 통과한다.

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/comm_matrix.py tests/test_v4_comm_matrix.py
git commit -m "feat: comm-matrix 헤더를 정규식 패턴으로 (다중 매칭 시 max weight)"
```

---

## Task 3: file_policy.py — 정규식 worker 키

**Files:**
- Modify: `src/agent_agora/file_policy.py` (전체 교체)
- Test: `tests/test_file_policy.py`

- [ ] **Step 1: `_POLICY` 상수 교체 + 정규식 테스트 추가 (실패 확인용)**

`tests/test_file_policy.py`의 `_POLICY` 상수(11–17행)를 아래로 교체 — `fallback` 필드를 `workers`의 `".*"` 키로 이전:

```python
_POLICY = json.dumps({
    "workers": {
        "Coder1": {"r": ["*"], "w": ["*.py", "*.md", "!secret_*.py"]},
        "Reviewer1": {"r": ["*.md"], "w": []},
        ".*": {"r": ["*.txt"], "w": []},
    },
})
```

`test_fallback_for_unlisted`(44–49행)를 아래로 교체(이름·주석만 갱신, 동작 동일 — `.*` catch-all):

```python
def test_dotstar_catch_all_for_unlisted():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_download("Ghost", "readme.txt") is True   # .* catch-all r
    assert fp.can_download("Ghost", "app.py") is False
    assert fp.can_upload("Ghost", "app.py") is False        # .* catch-all w=[]
```

파일 끝(`test_load_json_rejects_bad` 뒤)에 정규식 테스트를 추가:

```python
def test_regex_worker_key_matches_group():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"coder-.*": {"r": ["*.py"], "w": ["*.py"]}}}))
    assert fp.can_upload("coder-1", "app.py") is True
    assert fp.can_upload("coder-2", "app.py") is True
    assert fp.can_download("coder-9", "lib.py") is True


def test_regex_worker_key_fullmatch_not_partial():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"coder-.*": {"r": ["*.py"], "w": ["*.py"]}}}))
    # 'decoder'는 coder 그룹 아님 — 매칭 항목 없음 → 무제한
    assert fp.can_upload("decoder", "anything.exe") is True


def test_multi_match_unions_permission():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {
        "coder-1": {"r": ["*.md"], "w": []},
        "coder-.*": {"r": [], "w": ["*.py"]},
    }}))
    # coder-1은 두 항목 모두에 매칭 — 업로드는 넓은 항목이, 다운로드는 좁은 항목이 허용 (OR)
    assert fp.can_upload("coder-1", "app.py") is True
    assert fp.can_download("coder-1", "notes.md") is True


def test_load_json_rejects_invalid_regex_key():
    fp = FilePolicy()
    with pytest.raises(AgoraError) as ei:
        fp.load_json(json.dumps({"workers": {"*": {"r": [], "w": []}}}))
    assert ei.value.code == "file_policy_invalid"


def test_load_json_rejects_fallback_field():
    fp = FilePolicy()
    with pytest.raises(AgoraError) as ei:
        fp.load_json(json.dumps({"workers": {}, "fallback": {"r": ["*"], "w": []}}))
    assert ei.value.code == "file_policy_invalid"
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `uv run --extra dev python -m pytest tests/test_file_policy.py -q`
Expected: FAIL — 현행 `load_json`은 `fallback` 필드를 허용(거부 안 함)하고, worker 키를 리터럴로 조회하므로 정규식·fallback-거부 테스트가 실패.

- [ ] **Step 3: file_policy.py 전체 교체**

`src/agent_agora/file_policy.py`를 아래 내용으로 교체:

```python
"""파일 공유 권한 — 워커별 r/w gitignore 패턴. .agentagora/file-policy.json.

워커 키는 정규식 패턴 — 인스턴스 id를 re.fullmatch로 대조한다.
비활성(파일 없음) 시 전원 무제한. CommMatrix와 같은 거버넌스 패턴.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pathspec

from agent_agora.errors import AgoraError


class FilePolicy:
    """워커별 파일 업/다운로드 권한. 워커 키는 정규식, r/w는 gitignore식 패턴."""

    def __init__(self) -> None:
        self._workers: dict[str, dict[str, Any]] = {}
        self._compiled: dict[str, re.Pattern[str]] = {}
        self.active: bool = False

    def load_json(self, text: str) -> None:
        """file-policy.json 텍스트를 파싱해 *제자리 교체*. 잘못된 구조는 AgoraError.
        워커 키는 정규식으로 컴파일된다. 폐지된 'fallback' 필드가 있으면 거부."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AgoraError("file_policy_invalid", detail=str(e)) from None
        if not isinstance(data, dict):
            raise AgoraError("file_policy_invalid", detail="최상위는 JSON 객체여야 함")
        if "fallback" in data:
            raise AgoraError(
                "file_policy_invalid",
                detail="'fallback' 필드는 폐지됨 — workers의 '.*' 키로 이전하라")
        workers = data.get("workers", {})
        if not isinstance(workers, dict):
            raise AgoraError("file_policy_invalid", detail="'workers'는 객체여야 함")
        compiled: dict[str, re.Pattern[str]] = {}
        for key in workers:
            try:
                compiled[key] = re.compile(key)
            except re.error as e:
                raise AgoraError(
                    "file_policy_invalid",
                    detail=f"worker 키 '{key}'는 정규식이 아님: {e}") from None
        self._workers = workers
        self._compiled = compiled
        self.active = True

    def _matching(self, worker_id: str) -> list[dict[str, Any]]:
        """worker_id에 fullmatch되는 모든 정책 항목. 비활성이면 빈 리스트."""
        if not self.active:
            return []
        return [entry for key, entry in self._workers.items()
                if self._compiled[key].fullmatch(worker_id) is not None]

    @staticmethod
    def _match(patterns: list[str], file_name: str) -> bool:
        spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        return spec.match_file(file_name)

    def can_upload(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 업로드할 수 있는가.
        매칭 항목 중 하나라도 허용하면 허용. 매칭 항목 없으면 무제한."""
        entries = self._matching(worker_id)
        if not entries:
            return True
        return any(self._match(e.get("w", []), file_name) for e in entries)

    def can_download(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 다운로드할 수 있는가.
        매칭 항목 중 하나라도 허용하면 허용. 매칭 항목 없으면 무제한."""
        entries = self._matching(worker_id)
        if not entries:
            return True
        return any(self._match(e.get("r", ["*"]), file_name) for e in entries)

    def snapshot(self) -> dict[str, Any]:
        """현재 정책 조회용 (admin GET)."""
        if not self.active:
            return {}
        return {"workers": dict(self._workers)}


def load_file_policy(path: Path) -> FilePolicy:
    """path의 file-policy.json을 로드. 파일이 없으면 비활성 FilePolicy(무제한)."""
    fp = FilePolicy()
    if path.exists():
        fp.load_json(path.read_text("utf-8"))
    return fp
```

- [ ] **Step 4: file-policy 테스트 전체 실행해 통과 확인**

Run: `uv run --extra dev python -m pytest tests/test_file_policy.py -q`
Expected: PASS — 신규 5개 + 기존 테스트 전부. 정확명 키(`Coder1`,`Reviewer1`)는 자명한 정규식이라 기존 동작 보존.

- [ ] **Step 5: 커밋**

```bash
git add src/agent_agora/file_policy.py tests/test_file_policy.py
git commit -m "feat: file-policy worker 키를 정규식으로 (다중 매칭 OR, fallback 폐지)"
```

---

## Task 4: 생성 스킬의 `*` → `.*`

`agora-make-comm-matrix`·`agora-setup` 스킬은 CSV에 `*` fallback 행/열을 쓰라고 지시한다. `*`는 무효 정규식이므로 `.*`로 바꾼다. (`plugin/cc-agora-ops/scripts/comm_matrix.py` admin 클라이언트는 CSV를 전달만 하므로 변경 불필요.)

**Files:**
- Modify: `plugin/cc-agora-ops/skills/agora-make-comm-matrix/SKILL.md`
- Modify: `plugin/cc-agora-ops/skills/agora-setup/SKILL.md`

- [ ] **Step 1: `*` 사용처 찾기**

Run: `grep -n "\\*" plugin/cc-agora-ops/skills/agora-make-comm-matrix/SKILL.md plugin/cc-agora-ops/skills/agora-setup/SKILL.md`
Expected: comm-matrix CSV의 fallback 행/열을 `*`로 기술하는 줄들이 출력된다 (예: "a `*` fallback row and column").

- [ ] **Step 2: comm-matrix 헤더로서의 `*`를 `.*`로 교체**

Step 1이 출력한 줄들에서, **comm-matrix CSV의 행/열 라벨·헤더를 가리키는 `*`**만 `.*`로 바꾼다. 패턴 매칭과 무관한 `*`(마크다운 강조 `**bold**`, 목록 `* item` 등)는 건드리지 않는다. fallback을 설명하는 산문도 "`*` fallback" → "`.*` catch-all 패턴"으로 갱신한다.

- [ ] **Step 3: 변경 확인**

Run: `grep -n "\\.\\*\|fallback\|catch-all" plugin/cc-agora-ops/skills/agora-make-comm-matrix/SKILL.md plugin/cc-agora-ops/skills/agora-setup/SKILL.md`
Expected: fallback 행/열이 `.*`로 기술됨.

- [ ] **Step 4: 커밋**

```bash
git add plugin/cc-agora-ops/skills/agora-make-comm-matrix/SKILL.md plugin/cc-agora-ops/skills/agora-setup/SKILL.md
git commit -m "docs: comm-matrix 생성 스킬의 * 와일드카드를 .* 정규식으로"
```

---

## Task 5: docs/comm-matrix.md — 정규식 규칙 문서화

**Files:**
- Modify: `docs/comm-matrix.md`

- [ ] **Step 1: 현재 문서에서 헤더·`*` 설명 위치 확인**

Run: `grep -n "헤더\|header\|\\*\|와일드카드\|fallback" docs/comm-matrix.md`
Expected: CSV 헤더를 인스턴스명으로, fallback을 `*`로 설명하는 절이 출력된다.

- [ ] **Step 2: 정규식 규칙 절 반영**

`docs/comm-matrix.md`에서 Step 1이 가리킨 부분을 갱신한다. 다음 내용을 담는다:
- CSV 헤더(행·열 라벨)는 **정규식 패턴**이다. 인스턴스 id를 `re.fullmatch`로 대조한다 — 패턴이 id 전체와 일치해야 매칭.
- 정확한 인스턴스명은 자명한 정규식이므로 그대로 동작한다(`Coder1`은 `Coder1`에만 fullmatch).
- 역할군은 `coder-.*` 같은 패턴 한 줄로 커버한다.
- catch-all은 `.*`로 쓴다(기존 `*` 와일드카드는 폐지).
- 여러 패턴이 동시 매칭하면 **max weight**(권한 높은 쪽)를 택한다.

- [ ] **Step 3: 커밋**

```bash
git add docs/comm-matrix.md
git commit -m "docs: comm-matrix 정규식 헤더 규칙 문서화"
```

---

## Self-Review (작성자 체크)

**Spec 커버리지** (`2026-05-18-comm-matrix-file-policy-regex-design.md`):
- §4 CommMatrix 정규식 헤더·`weight_of` max·`*`→`.*`·invalid pattern 에러 → Task 1·2. ✓
- §5 FilePolicy 정규식 키·`can_*` OR·`fallback` 폐지·invalid 에러 → Task 3. ✓
- §6 마이그레이션(`*`→`.*`, `fallback`→`.*` 키) → 테스트의 `_STAR`·`_POLICY` 교체(Task 2·3) + 생성 스킬(Task 4). ✓
- §7 검증/테스트 → Task 2·3의 신규 테스트가 다중 매칭 max/OR·invalid·`.*`·fullmatch·`fallback` 거부를 커버. ✓
- §8 파일 영향 → Task 1–5가 errors·comm_matrix·file_policy·테스트·스킬·docs 전부 커버. `cc-agora-ops/scripts/comm_matrix.py`는 CSV 전달만 하므로 제외(spec §8이 과다 기재). ✓

**Placeholder 스캔:** 구현 스텝은 전체 파일 내용을, 테스트 스텝은 실제 테스트 코드를 포함. Task 4·5는 SKILL.md·docs 산문 편집이라 grep으로 위치를 짚고 교체 내용을 명시 — placeholder 아님.

**타입·시그니처 일관성:** `CommMatrix.weight_of/is_allowed/snapshot`, `FilePolicy.can_upload/can_download/snapshot`, `load_comm_matrix/load_file_policy` 시그니처는 현행과 동일 — 호출부(`dispatcher.py`·`file_routes.py`·`server.py`) 무변경. 신규 내부 멤버 `_compiled`는 두 클래스에서 일관되게 `dict[str, re.Pattern[str]]`.
