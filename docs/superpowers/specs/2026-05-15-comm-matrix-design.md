# 통신 매트릭스 (Communication Matrix) — Design Spec

- 날짜: 2026-05-15
- 대상 코드: AgentAgora 서버 (`src/agent_agora/`)
- 베이스: v3 messaging
- 결정 방식: 사용자와 sequential 합의 (§6 결정 트레일)

## 1. 배경 / 목적

워커(참가자) 간 `agora.dispatch`·`agora.broadcast`는 기본적으로 모든 쌍에 허용된다. 그러나 운영 시 *대화 흐름을 강제*하고 싶을 때가 있다 — orchestrator hub-and-spoke(워커는 orchestrator에만 회신, 워커끼리 직접 통신 금지), pipeline(A→B→C 사슬) 등.

통신 매트릭스는 worker↔worker dispatch 권한을 N×N ACL로 정의한다. broker가 매 dispatch·broadcast에서 이 매트릭스를 검사해 금지된 쌍을 거부한다.

## 2. 범위 / Non-goals

### 범위

- worker↔worker dispatch ACL.
- `agora.dispatch`와 `agora.broadcast` 둘 다 적용.

### Non-goals

- **봇 통신** — 봇은 매트릭스 밖. 봇 통신은 [cc-agora bots spec](2026-05-15-cc-agora-bots-design.md)의 B2 schema routing 규칙이 관할. 매트릭스 축은 `agora.instances`(워커)만.
- **메시지 내용 필터** — 매트릭스는 *쌍* 단위 허용/금지만. payload 검사 아님.
- **role 기반 규칙** — 매트릭스는 instance_id 단위. role 쌍 기반 ACL은 후속(§7).

## 3. `comm-matrix.csv`

ACL은 `.agentagora/comm-matrix.csv` 파일로 정의한다.

### 형식

N개 워커에 대해 — 헤더 1줄 + 데이터 N줄, 총 **N+1줄**. 각 줄 **N개 컬럼**.

```
Inst1,Coder1,Reviewer1,Tester1
0,1,1,1
1,0,0,0
1,0,0,0
1,0,0,0
```

- **헤더 행** — N개 `from` 레이블 (instance_id).
- **데이터 행 i** — `to = 헤더[i]` (행 순서 = 헤더 컬럼 순서와 동일). N개 셀.
- **셀 `[행 i][열 j]`** — `1`이면 `from=헤더[j] → to=헤더[i]` dispatch 허용, `0`이면 거부.

위 예시 = hub-and-spoke. 헤더 순서 Inst1/Coder1/Reviewer1/Tester1 기준 — 행 1(`to=Inst1`)은 자기(0) 외 모든 from 허용, 행 2~4(`to=Coder1/Reviewer1/Tester1`)는 `Inst1`만 허용. 즉 워커는 orchestrator에만 회신하고 워커끼리 직접 통신은 차단된다.

### 행 순서 규약

데이터 행에 `to` 레이블을 따로 두지 않는다 — 행 i는 헤더 i번째 인스턴스가 `to`다. broker는 로드 시 **데이터 행 수 == 헤더 컬럼 수**를 검증하고, 불일치면 `ValueError("comm_matrix_shape_mismatch")`로 거부한다. 행 순서가 헤더와 어긋나면 silent 오류가 되므로, CSV 편집 시 행 추가·삭제는 반드시 헤더 컬럼과 함께 한다.

## 4. 동작

### 4.1 활성 조건

- `.agentagora/comm-matrix.csv`가 **없으면** — ACL 비활성. 모든 worker↔worker dispatch 허용 (현 v3 동작).
- **있으면** — whitelist 강제. 매트릭스 `1` 셀만 허용.

### 4.2 검사

broker는 `agora.dispatch`·`agora.broadcast` 처리 시:

- **`dispatch(from, to)`** — `matrix[to][from] == 1`이 아니면 `ValueError("comm_denied: <from> -> <to>")`.
- **`broadcast(from)`** — fan-out 대상 각 `to`에 대해 `matrix[to][from]`을 검사. `1`인 `to`에게만 전달, `0`·미등재는 조용히 제외(broadcast는 부분 전달 허용)하되 응답의 `denied` 목록에 보고.
- **미등재 워커** — CSV 헤더·행에 없는 instance_id가 `from` 또는 `to`면 거부 (엄격 whitelist — 흐름 강제가 목적). 새 워커를 흐름에 넣으려면 CSV를 갱신한다.
- **봇 대상** — 매트릭스 검사 안 함. 봇 통신은 bots spec 관할 (§2 Non-goals).

### 4.3 런타임 등록

`agora.register_comm_matrix(csv_text: str) -> dict` — CSV 텍스트를 받아 매트릭스를 교체한다. 파일 없이 런타임만으로도 ACL을 활성화할 수 있다. shape 검증(§3 행 순서 규약) 실패 시 거부.

## 5. 데이터 모델

서버에 `CommMatrix` (in-memory) — `allowed: dict[to, set[from]]` + `active: bool`. dispatcher가 `is_allowed(from, to) -> bool`로 질의한다. SQLite 영속은 두지 않는다 — 재시작 시 `.agentagora/comm-matrix.csv` 재로드로 충분. 런타임 등록분의 영속은 §7 후속.

## 6. 결정 트레일

### 결정 1 — ACL 강제 (조회 아님)

- **확정**: 매트릭스는 권한 정의. broker가 검사·거부.
- **트레일**: 사용자 — "ACL 강제임."

### 결정 2 — 목적: 대화 흐름 강제

- **확정**: hub-and-spoke·pipeline 등 토폴로지 제어가 목적.
- **트레일**: 사용자 — "통신 막는 이유: 대화 흐름 강제."

### 결정 3 — 봇 제외

- **확정**: 매트릭스 축은 워커(`agora.instances`)만. 봇은 매트릭스 밖.
- **트레일**: 사용자 — "봇은 여기에 해당하지 않고, 인스턴스간 대화 송신 가능 여부 체크임."

### 결정 4 — 파일 없으면 ACL off

- **확정**: `.agentagora/comm-matrix.csv`가 없으면 권한 검사 안 함 (all-allow). 파일이 곧 활성 스위치.
- **트레일**: 사용자 — "파일없으면 별도로 권한체크 X."

### 결정 5 — CSV 0/1, 순수 N×N

- **확정**: JSON 인접 리스트 대신 CSV 격자. 헤더 1줄(N from) + 데이터 N줄, 셀 0/1. `to` 레이블 열 없이 행 순서 = 헤더 순서.
- **트레일**: 사용자 — "json? csv에 0,1로 표기해도 충분할텐데", "n개 컬럼이 n줄, 헤더 포함 n+1줄." 초안의 JSON 인접 리스트는 과한 설계였고, CSV 격자가 "참가자 목록 × from/to" 매트릭스에 직관적이며 스프레드시트 편집이 쉽다.

### 결정 6 — broadcast도 매트릭스 적용

- **확정**: `agora.broadcast`도 매트릭스 필터. fan-out 대상 중 `1`인 to에게만.
- **트레일**: 사용자 — "broadcast도 권한 매트릭스 적용 필요." 흐름 강제가 broadcast로 우회되면 ACL이 무력화된다.

### 결정 7 — 런타임 등록 도구

- **확정**: `agora.register_comm_matrix(csv_text)`로 런타임 교체.
- **트레일**: 사용자 — "통신 매트릭스 등록 기능이 필요할지도."

## 7. 의문점·후속 작업

- **런타임 등록분의 영속** — `register_comm_matrix`로 교체한 매트릭스는 재시작 시 휘발(파일만 재로드). 파일 write-back 또는 SQLite 저장은 후속.
- **동적 워커와 매트릭스 정합** — 새 워커 등록 시 CSV 미등재 = deny. 자동 행·열 추가(디폴트 0/1)는 후속.
- **role 기반 ACL** — instance_id 단위라 워커 교체 시 CSV 갱신 필요. role 쌍 기반 규칙은 후속.
- **self-dispatch** — `matrix[A][A]`. 보통 0. 필요 시 CSV에 명시.
- **매트릭스 조회 도구** — 현 매트릭스를 조회하는 `agora.comm_matrix()` 추가 검토 (ACL이 dispatch 거부로만 드러나면 디버깅이 어렵다).

## 8. 구현 우선순위

1. `CommMatrix` 모듈 (`src/agent_agora/comm_matrix.py`) — CSV 파싱, shape 검증, `is_allowed(from, to)`.
2. 서버 시작 시 `.agentagora/comm-matrix.csv` 로드 (없으면 비활성).
3. Dispatcher 검사 hook — `dispatch`/`broadcast` 진입에 `is_allowed` 검사. dispatch는 거부(ValueError), broadcast는 부분 필터 + `denied` 보고.
4. `agora.register_comm_matrix` 도구.
5. 통합 테스트 — 파일 없음(all-allow), hub-and-spoke 강제, broadcast 부분 필터, 미등재 워커 거부, shape mismatch 거부.
