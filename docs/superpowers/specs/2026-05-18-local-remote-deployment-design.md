# AgentAgora local/remote 배포 설계

- 작성일: 2026-05-18
- 상태: 설계 승인 → 구현 플랜 대기
- 관련: `docs/backlog.md`

## 1. 배경 / 문제

AgentAgora 서버는 현재 localhost 전용이다.

- uvicorn이 `127.0.0.1`에만 바인딩한다(`__main__.py`) — 다른 PC는 패킷이 도달조차 못 한다.
- 인증은 `/admin/*` 라우트만 보호된다(`admin_routes.py`, `AGORA_ADMIN_TOKEN` Bearer,
  상수시간 비교). MCP 엔드포인트 `/mcp`·`/channel/wait`·file·dashboard 라우트는
  인증이 없다.
- `X-Agora-*` 헤더는 *신원 주장*일 뿐 인증이 아니다 — 누구나 임의 값을 설정할 수 있다.

다른 PC에서/로의 접속(트러스트된 사설망 — LAN/VPN)이 가까운 목표다. 이를 위해
배포를 secure 경로 기준으로 다시 구성한다.

## 2. 목표 / 비목표

**목표**

- local과 remote 배포를 둘 다 제대로 지원한다.
- secure(원격) 경로가 코드의 기준선이고, local은 명시적 완화 모드다 — localhost를
  베이스로 깔고 원격을 덧붙이지 않는다.

**비목표**

- 인터넷 노출·적대적 네트워크 대비(rate limiting, 공인 CA 인증서, per-worker 자격
  증명 등)는 범위 밖. **트러스트된 사설망**(운영자가 모든 머신을 통제)만 가정한다.
- `dispatcher`·메시지 라우팅 시맨틱은 바꾸지 않는다.

## 3. 설계 원칙

서버·클라이언트 코드는 항상 풀 secure 경로(바인딩 호스트·인증·TLS)를 갖춘다.
`--local`은 그 경로의 일부를 명시적으로 생략하는 완화 모드다. secure가 기본,
local이 예외다.

## 4. 모드 선택

`agent-agora`는 `--local` / `--remote` 중 **정확히 하나**를 요구한다.

- 둘 다 없음 → 기동 에러: 모드를 명시하라는 메시지.
- 둘 다 지정 → 기동 에러.
- `--port <n>`은 모드와 무관한 독립 플래그다. 기본값 `8420`. 두 모드 모두에서 동작.
- 기존 `--no-tls` 플래그는 **제거**한다 — TLS 여부는 모드가 결정한다(`--local`=평문,
  `--remote`=TLS). `--no-timeout`·`--default-wait-timeout-ms`·`--restore`·`--add-wait`
  등 wait·복원 관련 플래그는 모드와 무관하므로 그대로 둔다.

## 5. `--local` 모드 (완화)

- 바인딩: `127.0.0.1:<port>`.
- 인증: 없음 — 인증 미들웨어 미적용.
- 전송: 평문 HTTP.
- 현재 `--no-tls` localhost 동작과 동등하다.

## 6. `--remote` 모드 (secure)

다음 셋이 모두 필요하다. 하나라도 빠지면 기동 에러:

- `--host <addr>` — 워커들이 접속에 사용할 주소(LAN IP 또는 호스트명). uvicorn은
  이 주소(또는 `0.0.0.0`)에 바인딩하고, 광고 URL·인증서 SAN에 이 값을 쓴다.
- `AGORA_AUTH_TOKEN` 환경변수 — 공유 인증 토큰. 미설정 시 기동 거부.
- TLS — self-signed 인증서로 HTTPS 제공(§8).

## 7. 인증 레이어

`src/agent_agora/auth.py` (신규) — `BearerAuthMiddleware` ASGI 미들웨어,
`auto_register.py`의 `AutoRegisterMiddleware`와 같은 패턴.

- `--remote`일 때만 미들웨어를 배선한다. **모든 라우트**(`/mcp`·`/channel/wait`·
  file·dashboard·admin)에서 `Authorization: Bearer <AGORA_AUTH_TOKEN>` 헤더를
  검사한다. 헤더 없음·불일치 → `401 {"error": "unauthorized"}`.
- 토큰 비교는 `hmac.compare_digest`로 상수시간 비교한다(`admin_routes.py`와 동일).
- `/admin/*` 라우트는 그 위에 기존 `AGORA_ADMIN_TOKEN`을 **추가로** 요구한다 —
  워커 토큰은 관리 권한이 아니다. 즉 admin 호출은 두 검사를 모두 통과해야 한다.
- `--local`일 때는 미들웨어를 배선하지 않는다 — 무검사.
- `X-Agora-*` 헤더는 종전대로 *신원*용으로 남는다. 인증은 Bearer 토큰이 담당한다.

## 8. TLS · 인증서

### 8.1 생성·저장 (서버 측)

- `--remote`는 self-signed 인증서로 TLS를 제공한다. `certs.py`의 `ensure_certs`를
  확장해 인증서 SAN에 `--host` 값을 포함시킨다(`127.0.0.1`·`localhost`도 함께) —
  SAN에 워커가 접속하는 주소가 없으면 클라이언트가 인증서를 거부한다.
- 인증서는 deployment마다 다르다(SAN에 그 deployment의 `--host`가 박힌다). 저장
  위치는 deployment 데이터 디렉토리 아래로 둔다 — `<dir>/.agentagora/certs/`:
  - `cert.pem` — **공개** 인증서. 워커에 배포된다(§9). 비밀이 아니다.
  - `key.pem` — **비밀** 개인키. 서버를 절대 떠나지 않는다. 배포·커밋 금지.
- `--cert-dir`로 위치를 바꿀 수 있고, 그 디렉토리에 운영자가 직접 넣은
  `cert.pem`/`key.pem`이 있으면 그대로 쓴다(BYO 인증서). `--host`가 바뀌어 기존
  인증서 SAN이 더 이상 맞지 않으면 self-signed 인증서를 재생성한다.

### 8.2 클라이언트 신뢰 (option a — 인증서 배포)

워커는 서버의 self-signed 인증서를 신뢰해야 한다. 방식: 서버 `cert.pem`(공개본)을
워커 측에 두고, 워커의 HTTP·MCP 클라이언트가 그것을 CA로 지정해 검증한다
(`verify=<cert.pem 경로>`). OS 신뢰 저장소는 건드리지 않는다 — 워커 번들 안에서
자기완결적으로 처리한다.

> ⚠️ 미해결 — MCP 클라이언트 `streamable_http_client`가 커스텀 CA 경로 인자를
> 받는지 구현 플랜 단계에서 확인한다. 받지 못하면 폴백: 인증서를 OS 신뢰 저장소에
> 설치하는 절차를 문서화한다. httpx 클라이언트(`channel_adapter.py`·`bot.py`)는
> `verify=` 인자를 받으므로 문제없다.

## 9. 인증서 배포

option (a). 별도 배포 채널을 두지 않고 **워커 번들에 인증서를 동봉**한다.

- remote 배포에서 워커는 다른 PC에서 돈다 — 운영자는 워커 디렉토리(번들)를 그 PC로
  옮겨야 한다. 인증서는 이 번들 안에 실려 함께 이동한다.
- spawn 계열 스킬(`agora-spawn`·`agora-design-worker`·`agora-setup`)이 `--remote`
  배포 시 서버 `cert.pem`(**공개본만** — `key.pem`은 절대 복사 금지)을 각 워커
  디렉토리에 복사한다 — 예: `<worker-dir>/agora-cert.pem`.
- 워커의 `.mcp.json`·채널 어댑터·봇은 이 로컬 `agora-cert.pem`을 TLS 검증 CA로
  쓴다.

## 10. 클라이언트 설정 전파

- `server-info.json`(`agora-setup`이 `.agentagora/`에 기록 — 별도 spec)에
  `mode`·`host`·`port`·`tls`·`url`·인증서 경로를 기록한다. **토큰 값은 기록하지
  않는다.**
- spawn 계열 스킬이 `--remote` 배포 시 생성하는 워커 `.mcp.json`에 다음을 baking:
  - `url`: `https://<host>:<port>/mcp`
  - `headers`: `X-Agora-*`(종전) + `Authorization: Bearer <token>`
  - TLS 검증을 위한 `agora-cert.pem` 참조
- 채널 어댑터·봇도 토큰과 인증서 경로를 받아 HTTP·MCP 호출에 쓴다.
- 토큰 값은 운영자가 환경변수/입력으로 공급한다. 워커 `.mcp.json`에는 헤더로
  들어가므로 워커 PC에 평문으로 존재한다 — 트러스트된 사설망·운영자 통제 머신
  가정에서 수용한다.

## 11. 에러 처리

- 모드 미지정 / 중복 지정 → 기동 에러.
- `--remote`인데 `--host` 누락 또는 `AGORA_AUTH_TOKEN` 미설정 → 기동 에러.
- `--remote`에서 Bearer 헤더 없음·불일치 → `401`.
- 인증서 SAN이 `--host`와 불일치 → 클라이언트 TLS 검증 실패(인증서 재생성으로 예방).

## 12. item 1 관계

item 1(wait-tool-gating, `GET /channel/wait` 라우트)은 이미 master에 병합됐다
(`b95ddb4`). 이 설계의 `BearerAuthMiddleware`가 `/channel/wait`를 포함한 전 라우트를
덮으므로, item 1이 라우트를 무인증으로 둔 부분은 이 설계가 흡수한다.

## 13. 검토했다 접은 대안

- **리버스 프록시(caddy/nginx)로 TLS·인증 종단** — 외부 의존성·별도 설정을 더하고,
  "서버 자체가 원격을 지원"한다는 원칙(§3)에 어긋난다.
- **FastMCP 내부 인증(도구·세션 단위)** — 비-MCP 라우트(`/channel/wait`·file·
  dashboard·admin)를 덮지 못해 HTTP 라우트는 별도 인증이 필요 → 일관성이 깨진다.

## 14. 구현·테스트 순서

local 경로부터 구현·검증하고 그다음 remote로 간다. 구현 플랜의 단계 분해 권장:

1. 모드 플래그(`--local`/`--remote`) + 바인딩 + `--local` 모드 — local 환경에서 전부 검증 가능.
2. `BearerAuthMiddleware` + `--remote` 인증 — 단위·통합 테스트로 한 머신에서 검증 가능.
3. TLS + 인증서 SAN — `127.0.0.1`에 HTTPS로 붙어 한 머신에서 검증 가능.
4. spawn/setup 스킬의 인증서·설정 전파.

실제 cross-PC 검증만 머신 2대가 필요하다 — 그 외는 한 머신의 로컬 테스트로 덮인다.

## 15. 검증 / 테스트

- 모드 플래그 검증 — 미지정·중복·`--remote` 필수값 누락 시 기동 에러.
- `BearerAuthMiddleware` — 토큰 없음·불일치 시 401, 일치 시 통과, `--local`에서 우회.
- `/admin/*` — 워커 토큰만으로는 거부, admin 토큰까지 있어야 통과.
- `certs.py` — 생성된 인증서 SAN에 `--host`가 포함된다.
- spawn/setup — `--remote` 배포 시 워커 번들에 `agora-cert.pem`이 들어가고
  `.mcp.json`에 https URL·Bearer 헤더가 baking된다.

## 16. 파일 영향

| 파일 | 변경 |
|---|---|
| `src/agent_agora/__main__.py` | `--local`/`--remote`/`--host` 플래그, `--no-tls` 제거, 모드 검증, 바인딩 호스트·TLS·미들웨어 배선 |
| `src/agent_agora/auth.py` | 신규 — `BearerAuthMiddleware` |
| `src/agent_agora/certs.py` | `ensure_certs`에 `host` 인자 — SAN에 포함, SAN 불일치 시 재생성 |
| `src/agent_agora/channel_adapter.py`·`bot.py` | httpx·MCP 클라이언트에 토큰 헤더·인증서 CA 전달 |
| `plugin/cc-agora-ops/scripts/spawn.py` 및 spawn/setup 스킬 | `--remote` 배포 시 인증서 동봉·`.mcp.json` 전파 |
| `docs/channel-mode.md`·`docs/usage-guide.md`·`README.md` | local/remote 배포 절차 문서화 |

규모가 크다 — 구현 플랜에서 §14 단계로 분해한다.
