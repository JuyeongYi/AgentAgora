# 통신 매트릭스 (comm-matrix)

AgentAgora 워커 간 디스패치 권한·우선순위를 N×N CSV 한 장으로 제어하는 기능이다.

---

## 개요

통신 매트릭스(comm-matrix)는 워커↔워커 `agora.dispatch` ACL(접근 제어 목록)이다.
`matrix[to][from]` 셀에 **0 이상의 정수 weight**를 두어 두 가지를 동시에 표현한다.

| 값 | 의미 |
|----|------|
| `0` | 해당 `from→to` 엣지 **금지** |
| `>0` | 허용 + 수신자 인박스 처리 **우선순위** (클수록 먼저) |

`weight_of(from, to)` 메서드가 정수를 반환하고, `is_allowed(from, to)`는 그 값이
`> 0`이면 `True`를 반환한다.

매트릭스가 **비활성**(파일 없음)이면 모든 디스패치가 허용되고 `weight_of`는 `0`을
반환한다. 매트릭스가 **활성**이면 미등재 엣지는 기본 거부(strict whitelist)다.

---

## CSV 형식

```
,InstA,InstB,InstC
InstA,0,1,2
InstB,1,0,1
InstC,2,1,0
```

- **헤더 행** — `from` 인스턴스 목록. 첫 번째 셀은 관례상 비워 두거나 라벨 문자열을
  넣는다(파싱에서 행 라벨로 처리됨).
- **데이터 행** — 행 라벨이 `to` 인스턴스. 각 셀이 해당 `from→to` weight.
- **정사각(N×N)** — 행 수(데이터)와 열 수(헤더)가 같아야 한다. shape 불일치 시 로드
  실패 (`comm_matrix_shape_mismatch`).
- 셀 값은 **0 이상의 정수**여야 한다. 비정수·음수는 `comm_matrix_invalid_cell` 오류.

---

## `*` 와일드카드 폴백

`*`를 일반 라벨처럼 CSV에 넣으면 미등재 인스턴스에 대한 폴백 weight를 지정할 수 있다.

- **`*` 데이터 행** — 매트릭스에 없는 `to`(수신자)에 적용되는 폴백 행.
- **`*` 헤더 열** — 매트릭스에 없는 `from`(발신자)에 적용되는 폴백 열.
- **`_weights["*"]["*"]`** — 발신자·수신자 둘 다 미등재인 catch-all.

폴백 해석 순서:

1. `to` 행이 명시돼 있으면 그 행을 사용.
2. `to`가 없으면 `*` 행으로 폴백.
3. 해당 행에서 `from` 열이 있으면 그 셀 값 사용.
4. `from`이 없으면 같은 행의 `*` 열로 폴백. 그것도 없으면 `0`.

`*`가 **없는** CSV는 strict whitelist다 — 매트릭스에 등재되지 않은 `from`·`to`는
모두 거부된다. `*` 폴백은 하위 호환을 깨지 않는다.

예시 — 허브·스포크 구성에 `*` 활용:

```
*,pm,coder,reviewer
0,1,1,1
1,0,1,1
1,1,0,0
1,1,0,0
```

헤더(`from` 목록): `*`, `pm`, `coder`, `reviewer`. 데이터 행 라벨(`to`): `*`, `pm`,
`coder`, `reviewer`. `*`를 포함하면 (N+1)×(N+1) 정사각이 된다.

---

## 기동 시 로드

서버는 기동 디렉토리 아래 `.agentagora/comm-matrix.csv`를 탐색한다.

- 파일이 있으면 로드 → 매트릭스 **활성**.
- 파일이 없으면 매트릭스 **비활성** — 모든 디스패치 허용.

서버 기동 옵션:

```bash
agent-agora --dir /path/to/project --port 8420 --no-tls --no-timeout
```

`--dir`이 `.agentagora/` 탐색의 기준 디렉토리다.

---

## 런타임 교체 (admin HTTP 엔드포인트)

서버를 재시작하지 않고 매트릭스를 교체·조회할 수 있다. MCP 도구 경유 교체는 보안상
제거됐으며, **운영자 전용 admin HTTP 엔드포인트**만 제공한다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/admin/comm-matrix` | 바디 CSV로 in-memory 매트릭스 교체 |
| `GET`  | `/admin/comm-matrix` | 현재 매트릭스 상태 조회 |

**인증** — `AGORA_ADMIN_TOKEN` 환경 변수에 토큰을 설정하고 서버를 기동해야 한다.
요청 헤더에 `Authorization: Bearer <token>`을 포함해야 한다.
`AGORA_ADMIN_TOKEN`이 설정되지 않으면 admin 엔드포인트 자체가 등록되지 않는다(기본 비활성 = 기본 안전).

`POST` 성공 응답:

```json
{ "status": "ok", "active": true }
```

`GET` 성공 응답:

```json
{
  "active": true,
  "matrix": {
    "InstA": { "InstB": 1, "InstC": 2 },
    "InstB": { "InstA": 1, "InstC": 1 }
  }
}
```

`matrix` 필드는 `{to: {from: weight}}` 구조다. `*` 폴백 행·열이 있으면 포함된다.

---

## 적용 범위

comm-matrix가 게이팅하는 범위와 게이팅하지 않는 범위:

| 대상 | 게이팅 여부 |
|------|------------|
| 워커→워커 `agora.dispatch` | **게이팅** — `is_allowed` 검사 |
| 스키마 라우팅 메시지(봇 대상) | 게이팅 안 함 |
| `cc` 사본 | 게이팅 안 함 |
| `agora.broadcast` | 차단된 수신자를 `denied` 목록으로 보고 |

`agora.broadcast`는 허용된 수신자에게만 전송하고, 차단된 인스턴스는 응답의
`denied` 배열에 나열한다.

---

## 운영자 슬래시 스킬

cc-agora-ops 플러그인이 comm-matrix를 작성·적용하는 두 가지 슬래시 스킬을 제공한다.

### `/cc-agora-ops:agora-make-comm-matrix [<out-path>]`

현재 등록된 워커 인스턴스 목록을 읽어 comm-matrix CSV를 **작성**한다.

1. `agora.instances`로 등록된 워커 목록을 가져온다.
2. 운영자에게 토폴로지를 질문한다 — 허브·스포크, 전체 허용, 커스텀.
3. CSV를 생성하고 `<out-path>`에 저장한다(기본값: `.agentagora/comm-matrix.csv`).
4. 적용 방법을 안내한다.

기본 경로로 저장하면 서버 재시작 시 자동으로 로드된다. 재시작 없이 즉시 반영하려면
`/cc-agora-ops:agora-comm-matrix`를 사용한다.

### `/cc-agora-ops:agora-comm-matrix [<csv-path>] [--server-url]`

실행 중인 서버에 comm-matrix를 **적용**하거나 현재 상태를 조회한다.

- `<csv-path>` 제공 → `POST /admin/comm-matrix`로 매트릭스 교체.
- `<csv-path>` 생략 → `GET /admin/comm-matrix`로 현재 매트릭스 조회.
- `AGORA_ADMIN_TOKEN` 환경 변수가 세션에 설정돼 있어야 한다.
- `--server-url` 기본값은 `http://127.0.0.1:8420`.

---

## 참고

- [`src/agent_agora/comm_matrix.py`](../src/agent_agora/comm_matrix.py) — `CommMatrix` 구현
- [`src/agent_agora/admin_routes.py`](../src/agent_agora/admin_routes.py) — admin HTTP 라우트
- [`docs/superpowers/specs/2026-05-18-comm-matrix-fallback-design.md`](superpowers/specs/2026-05-18-comm-matrix-fallback-design.md) — `*` 와일드카드 설계 문서
- [`docs/usage-guide.md`](usage-guide.md) — 전체 워커·봇·매트릭스 사용 가이드
