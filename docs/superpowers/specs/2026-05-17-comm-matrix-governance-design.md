# comm-matrix 거버넌스 — Design Spec

- 날짜: 2026-05-17
- 대상 코드: `src/agent_agora/server.py` · `__main__.py` + admin 엔드포인트(신규) + 문서·예제
- 베이스: comm-matrix 기능 (구현·머지됨 — `CommMatrix`, dispatch/broadcast ACL, `agora.register_comm_matrix`)
- 결정 방식: 사용자와 sequential 합의 (§5 결정 트레일)

## 1. 배경 / 목적

comm-matrix는 워커↔워커 dispatch를 N×N ACL로 강제한다. 런타임 교체는 현재
`agora.register_comm_matrix` MCP 도구가 담당한다. 그런데 이 도구는 `@mcp.tool`로
노출돼 **등록된 워커 누구나** 호출할 수 있다 — ACL에 종속된 워커가 그 ACL을
재작성할 수 있다. AgentAgora는 워커 인증이 없어(`X-Agora-Role`은 자기가 적는
헤더, auto-register가 그대로 신뢰) "orchestrator만 호출" 같은 role 게이팅도
무의미하다. 거부당한 워커가 전부-`1` 매트릭스로 갈아끼우면 ACL이 무력화된다.
즉 지금의 comm-matrix는 강제 경계가 아니라 권고에 머문다.

해결 — comm-matrix 변경을 **운영자 전용 제어 평면**으로 옮긴다. MCP 도구에서
제거하고, 운영자만 접근하는 토큰 게이트 admin HTTP 엔드포인트로 대체한다.

## 2. 비범위

- **워커 인증·격리** — AgentAgora는 워커 인증이 없다. 본 spec은 comm-matrix
  거버넌스만 다룬다.
- **`agora.flush`** — 채널 모드에서 `agora.wait`가 사실상 논블로킹 드레인이 된
  점 관련 별도 도구 논의. 후속, 본 spec 범위 밖.
- **`.agentagora/comm-matrix.csv` 파일 쓰기 보호** — §5 결정 3 참조. 불필요로
  결론.
- **comm-matrix CSV 포맷** — 현행 N×N 0/1 CSV 유지.

## 3. 설계

### 3.1 `agora.register_comm_matrix` MCP 도구 제거

`server.py`의 `@mcp.tool(name="agora.register_comm_matrix")` 정의(현
`server.py:102-110`)를 삭제한다. 워커 도구 목록에서 사라져 AI가 ACL을 건드릴
경로가 없어진다. `CommMatrix.load_csv`·`is_allowed`, Dispatcher의
dispatch/broadcast ACL 검사는 그대로 둔다 — 매트릭스 *기능*은 유지하고
*워커가 변경하는 경로*만 없앤다.

### 3.2 운영자 admin 엔드포인트

`mcp.streamable_http_app()`이 만든 Starlette 앱에 admin 라우트를 추가한다
(`run_server`에서 `AutoRegisterMiddleware`를 붙이는 지점 옆).

- **`POST /admin/comm-matrix`** — 요청 바디 = CSV 텍스트. `comm_matrix.load_csv(body)`
  로 in-memory 매트릭스를 제자리 교체. shape 오류 → 400 + 한국어 에러 메시지.
  성공 → 200 `{"status":"ok","active":true}`.
- **`GET /admin/comm-matrix`** — 현재 매트릭스 상태 조회 →
  `{"active": <bool>, "matrix": {<to>: [<from>, ...]}}`.

런타임 교체는 **in-memory만** 바꾼다 — 디스크 `.agentagora/comm-matrix.csv`는
건드리지 않는다. 재기동 후에도 유지하려면 운영자가 디스크 CSV를 직접 편집한다
(그 파일은 startup seed). POST 변경이 휘발성인 것은 의도된 동작이다.

### 3.3 토큰 게이트

admin 엔드포인트는 `AGORA_ADMIN_TOKEN` 환경변수로 게이팅한다.

- env 미설정 → admin 라우트를 **등록하지 않는다**. `/admin/comm-matrix`는 404.
  기본 비활성 = 기본 안전.
- env 설정 → 라우트 등록. 요청에 `Authorization: Bearer <token>` 헤더가 있고
  값이 일치해야 한다. 불일치·누락 → 401. 비교는 `hmac.compare_digest`(상수시간).
- env var를 쓰는 이유: CLI 플래그(`--admin-token`)는 `ps`/프로세스 목록에 평문
  노출된다.

### 3.4 영향받는 파일

| 파일 | 변경 |
| --- | --- |
| `src/agent_agora/server.py` | `agora.register_comm_matrix` 도구 제거 |
| `src/agent_agora/admin_routes.py` (신규) | admin 엔드포인트 핸들러 + 토큰 검증 + 라우트 팩토리 |
| `src/agent_agora/__main__.py` | `run_server`에서 `AGORA_ADMIN_TOKEN`을 읽어 admin 라우트 조건부 등록 |
| `examples/comm_demo/` | `register_comm_matrix` 대신 startup 전 `.agentagora/comm-matrix.csv` 배치로 수정 |
| `examples/README.md` | comm-matrix 런타임 교체 서술 갱신 (도구 → admin 엔드포인트) |
| `tests/test_v4_*`(comm-matrix) · `test_integration` | `register_comm_matrix` 도구 테스트 제거, admin 엔드포인트 테스트 추가 |
| `README.md` | 도구 레퍼런스에서 `agora.register_comm_matrix` 제거, admin 엔드포인트 + `AGORA_ADMIN_TOKEN` 문서화 |

### 3.5 구현 노트

- admin 라우트는 Starlette `Route("/admin/comm-matrix", endpoint, methods=["GET","POST"])`.
  핸들러는 `comm_matrix` 인스턴스와 토큰을 클로저로 캡처한다.
- POST 바디: `await request.body()` → `.decode("utf-8")`.
- 토큰 검증은 핸들러 진입 시 — `Authorization` 헤더 파싱 후 `hmac.compare_digest`.
- `run_server`: `admin_token = os.environ.get("AGORA_ADMIN_TOKEN")`. truthy면
  `admin_routes.make_admin_route(comm_matrix, admin_token)`을 `starlette_app`에
  추가. falsy면 추가하지 않는다.

## 4. 동작 예 (운영자)

```bash
# 서버 기동 (토큰 설정)
set AGORA_ADMIN_TOKEN=...secret...
agent-agora --dir . --port 8420 --no-tls

# 운영자가 매트릭스 교체
curl -X POST http://127.0.0.1:8420/admin/comm-matrix \
  -H "Authorization: Bearer ...secret..." \
  --data-binary @comm-matrix.csv

# 워커가 시도 → agora.register_comm_matrix 도구 자체가 없음.
#                admin 엔드포인트는 토큰 없으면 401.
```

## 5. 결정 트레일

- **결정 1 — MCP 도구 제거.** `agora.register_comm_matrix`는 워커 누구나 호출
  가능 → ACL 자가-재작성 구멍. 워커 인증이 없어 role 게이팅도 불가. 도구를
  제거해 워커의 ACL 변경 경로를 끊는다. 대안(role 게이팅 / 기본-off 플래그로
  도구 유지)은 모두 인증 부재 때문에 우발적 호출을 완전히 막지 못한다.
- **결정 2 — 운영자 admin 엔드포인트.** 런타임 교체 기능 자체는 유효하다
  (재기동 없이 ACL 갱신). 워커가 못 보는 별도 제어 평면 — 토큰 게이트 HTTP
  엔드포인트 — 으로 옮긴다.
- **결정 3 — 디스크 CSV 잠금은 필수 아님.** 런타임 권위는 in-memory(토큰
  게이트 POST). 디스크 CSV는 startup seed 전용이고 서버는 워커보다 먼저 뜬다 —
  이후 변경은 POST로만 일어나므로 워커의 디스크 변조는 런타임 매트릭스에
  무영향. 따라서 파일 잠금은 본 변경의 필수 요소가 아니다. 원한다면 워커
  settings의 `permissions.deny`로 `.agentagora/**` 쓰기를 막아 startup seed까지
  defense-in-depth를 더할 수 있다 — `deny`는 하드 차단이라 `run.bat`의
  `--dangerously-skip-permissions`로도 우회되지 않고 Bash 쓰기까지 막는다. 다만
  이는 워커 설정(`settings.local.json`) 영역이라 본 spec 범위 밖이다.
- **결정 4 — 토큰은 env var, 위협 모델 명시.** CLI 플래그는 `ps` 노출 → env
  var. 단일 머신·단일 유저 환경에선 작심한 워커가 서버 프로세스 env를 들여다볼
  수 있으나, 이는 AgentAgora 전체의 워커 비격리 한계다. 본 변경의 목표는
  **AI가 도구를 보고 우발적/무심하게 ACL을 바꾸는 것**의 차단 — 그 목표는
  도구 제거 + 토큰 게이트로 달성된다. 작심한 동일-유저 공격 방어는 범위 밖.
