# comm-matrix · file-policy 정규식 규칙 — 설계

- 작성일: 2026-05-18
- 상태: 설계 작성 → 유저 검토 대기
- 관련: `src/agent_agora/comm_matrix.py`, `src/agent_agora/file_policy.py`

## 1. 배경 / 문제

comm-matrix(`comm_matrix.py`)와 file-policy(`file_policy.py`)는 워커 인스턴스를 **정확한 이름**으로 식별한다 — comm-matrix CSV 헤더 = 인스턴스명, file-policy `workers` 키 = 인스턴스 id. 워커 수가 늘면 N×N CSV·정책 항목을 인스턴스마다 일일이 적어야 한다. `coder-1`·`coder-2`·`coder-3`처럼 역할이 같은 워커군에 동일 규칙을 주려면 행·항목이 중복된다.

## 2. 목표 / 비목표

**목표** — comm-matrix 헤더와 file-policy worker 키를 정규식 패턴으로 해석한다. `coder-.*` 한 줄로 역할군 전체를 커버한다.

**비목표** — file-policy의 r/w 파일명 패턴(gitignore식) 변경. `dispatcher`·라우팅 시맨틱 변경. comm-matrix CSV의 N×N 구조 변경.

## 3. 설계 원칙

인스턴스 id는 `re.fullmatch`로 패턴에 대조한다 — 패턴이 id 전체와 일치해야 매칭(`coder`가 `decoder`·`coder-1`을 부분 매칭하는 사고 방지). 정확한 이름은 자명한 정규식이므로(`InstA`는 `InstA`에만 fullmatch) 기존 정확명 설정이 그대로 동작한다. 여러 패턴이 동시 매칭하면 **권한 높은 쪽**을 택한다.

## 4. CommMatrix

- CSV 헤더(행 라벨·열 라벨)를 정규식 패턴으로 해석한다. N×N 구조·CSV 포맷·정수 weight 셀은 불변.
- `load_csv`: 각 헤더를 `re.compile`한다. 컴파일 실패 시 `AgoraError("comm_matrix_invalid_pattern", ...)`.
- `weight_of(from_, to)`: `to`에 `fullmatch`되는 모든 행-패턴 × `from_`에 `fullmatch`되는 모든 열-패턴의 교차 셀을 수집 → **max weight**를 반환한다(= 권한 높은 쪽). 매칭 셀이 없으면 `0`(현행 "미등재 → 0" 유지).
- `*` 와일드카드는 폐지한다 — catch-all은 `.*`로 쓴다(`*`는 유효하지 않은 정규식).
- `is_allowed` = `weight_of > 0` (불변).

## 5. FilePolicy

- `file-policy.json`의 `workers` 키를 정규식 패턴으로 해석한다.
- `fallback` 필드는 폐지한다 — catch-all은 `.*` 키로 표현한다. `load_json`에서 `fallback` 필드가 남아 있으면 `AgoraError("file_policy_invalid", detail="fallback은 폐지됨 — workers의 \".*\" 키로 이전하라")` (조용한 권한 변경 방지).
- `load_json`: 각 worker 키를 `re.compile`한다. 실패 시 `AgoraError("file_policy_invalid", ...)`.
- `can_upload`/`can_download(worker_id, file_name)`: `worker_id`에 `fullmatch`되는 모든 항목을 수집 → 그중 **하나라도** 해당 op를 허용하면 허용한다(OR = 권한 높은 쪽). 매칭 항목이 없으면 무제한(현행 "미등재 → 무제한" 유지).
- r/w의 gitignore식 파일명 패턴 매칭은 불변 — **워커 키만** 정규식으로 바뀐다.

## 6. 마이그레이션

- comm-matrix CSV: 헤더 `*` → `.*`. 정확한 인스턴스명 헤더는 수정 불필요(자명한 정규식).
- file-policy.json: `"fallback": {...}` → `"workers"`에 `".*"` 키로 이전. 정확명 키는 수정 불필요.

## 7. 검증 / 테스트

- comm-matrix — 정규식 헤더 다중 매칭 시 max weight; 잘못된 정규식 헤더 → load 에러; `.*` catch-all 동작; 정확명 fullmatch(부분 매칭 안 됨).
- file-policy — 다중 매칭 항목 OR 동작; 잘못된 정규식 키 → load 에러; `fallback` 잔존 → load 에러; `.*` catch-all; 매칭 없으면 무제한.
- 기존 테스트 중 헤더·키에 `*`·`fallback`을 쓰는 케이스는 `.*`로 갱신한다.

## 8. 파일 영향

| 파일 | 변경 |
|---|---|
| `src/agent_agora/comm_matrix.py` | 헤더 정규식 컴파일, `weight_of` 패턴 매칭 + max weight |
| `src/agent_agora/file_policy.py` | worker 키 정규식 컴파일, 다중 매칭 수집, `can_*` OR, `fallback` 폐지 |
| `src/agent_agora/errors.py` | `comm_matrix_invalid_pattern` 코드 추가 |
| `tests/test_v4_comm_matrix.py` · `tests/test_file_policy.py` | 정규식 케이스 추가, `*`·`fallback` 케이스 갱신 |
| `plugin/cc-agora-ops/scripts/comm_matrix.py` · `skills/agora-make-comm-matrix` · `skills/agora-setup` | 생성하는 catch-all 행/열을 `*` → `.*`로 (필수 — `*`는 무효 정규식) |
| `docs/comm-matrix.md` | 정규식 규칙·`.*` catch-all 문서화 |

## 9. 미해결

없음 — 범위가 작고 결정이 모두 끝났다.
