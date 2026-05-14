# AgentAgora

여러 개의 자율 에이전트(예: 다중 Claude Code 인스턴스)가 **이름 있는
인스턴스로 서로를 발견하고 메시지를 주고받는** MCP 서버. v3에서 메시지 채널
단일 책임으로 재정의됨 (v1의 JSON Schema KV 기능은 v3에서 제거 — 자세한 이력은
이 문서 끝 'v1 → v3 변경' 참조).

각 에이전트는 자기만의 컨텍스트와 도구를 가진 채 독립적으로 동작하지만,
AgentAgora를 통하면:

- **이름 있는 인스턴스**로 자기를 노출하고 (`agora.register`)
- 다른 인스턴스에게 **명령을 디스패치**하고 (`agora.dispatch`)
- 자신에게 들어오는 명령을 **롱폴링으로 수신**할 수 있다 (`agora.wait`)

LangGraph처럼 워크플로를 그래프로 사전 정의하는 대신, **에이전트끼리
런타임에 서로를 발견하고 자유롭게 메시지를 주고받는** 모델이다.

---

## 설치

요구 사항: Python 3.13+.

```bash
git clone <this-repo> AgentAgora
cd AgentAgora
pip install -e .
# 또는 uv 사용
uv sync
```

설치 후 `agent-agora` 실행 파일이 PATH에 추가된다.

---

## 빠른 시작

### 1) 서버 기동

```bash
agent-agora --dir . --port 8420
```

기본은 HTTPS + self-signed cert. cert는 `~/.agent-agora/certs/`에
한 번 생성되고 재사용된다. 로컬 테스트라면 `--no-tls`로 평문 HTTP 사용 가능.

```bash
agent-agora --dir . --port 8420 --no-tls
```

성공 시 출력:

```
AgentAgora starting on http://127.0.0.1:8420/mcp
  Data dir : .../.agentagora
  Cert     : (none — HTTP mode, localhost only)
```

### 2) MCP 클라이언트 연결

Streamable HTTP 전용. 다른 transport는 지원하지 않는다.

Claude Code의 `.mcp.json` 예시:

```json
{
  "mcpServers": {
    "agora": {
      "type": "http",
      "url": "http://127.0.0.1:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "InstA",
        "X-Agora-Role": "orchestrator",
        "X-Agora-Description": "User-facing orchestrator"
      }
    }
  }
}
```

`X-Agora-Instance-Id` 헤더가 있으면 첫 MCP 요청 시
`AutoRegisterMiddleware`가 자동으로 `agora.register`를 호출한다 — 별도
register 도구 호출은 필요 없다.

---

## MCP 도구 레퍼런스

### 메타

- **`agora.info()`** — 서버 경로/포트/uptime 반환.

### 인스턴스 디렉터리

- **`agora.register(instance_id, role="worker", description="")`** —
  세션을 인스턴스 이름에 바인딩. 헤더 자동 등록을 쓰면 호출 불필요.
- **`agora.unregister()`** — 현재 세션 해제. 멱등.
- **`agora.instances()`** — 등록된 모든 인스턴스 나열.
- **`agora.find(query)`** — instance_id/role/description에 `query` 부분
  문자열(대소문자 무시)이 포함된 인스턴스 검색.

### 명령 채널

- **`agora.dispatch(target, payload, expect_result=False, cc=None, reply_to=None, in_reply_to=None, conversation_id=None, closing=False, priority="normal", deadline_ts=None)`** — 1:1 발신.
  - `target`: **단일 instance_id** (v3에서 단일 문자열로 변경). 팬-아웃은 `agora.broadcast` 사용.
  - `payload`: 자유 JSON.
  - `cc`: observer 목록 — 사본만 받고 응답 의무 없음.
  - `conversation_id`: 명시하면 그 대화에 묶임. 미지정 시 서버가 자동 부여.
  - `closing=True`: 송신 측 종료 신호.
  - `priority`: `"low" | "normal" | "high"`.
- **`agora.broadcast(payload, expect_result=False, ...)`** — 자기 제외 등록된 모든 인스턴스로 fan-out. dispatch와 같은 보조 인자 지원.
- **`agora.wait(timeout_ms=None, from_sources=None, by_conversation=None, sort="fifo")`** — 자기 큐에 쌓인 명령을 드레인.
  - 타임아웃 우선순위: 인자 → 헤더 `X-Agora-Wait-Timeout-Ms` → 서버 CLI 기본값.
  - `0`이면 무한 블록.
  - `from_sources` / `by_conversation`: AND 결합 필터. 미매칭 envelope는 큐에 보존.
  - `sort="priority"`: high → normal → low 순.
- **`agora.peek(target=None)`** — 큐 길이·in-flight 카운트 등 비파괴 조회.
- **`agora.conversation_status(conversation_id)`** — 한 대화의 메타(참가자·메시지 수·closed_by) 조회.
- **`agora.conversations_list(...)`** — 자기 참가 대화 목록.
- **`agora.close_thread(conversation_id)`** — 자기 쪽 close 신호 박기.

---

## 설정 헤더

`.mcp.json`의 `headers`에 박을 수 있는 키들:

| 헤더                          | 효과 |
|------------------------------|------|
| `X-Agora-Instance-Id`         | 첫 요청에서 자동 register (필수). |
| `X-Agora-Role`                | 자동 register 시 role. 기본 `worker`. |
| `X-Agora-Description`         | 자동 register 시 description. 기본 빈 문자열. |
| `X-Agora-Wait-Timeout-Ms`     | `agora.wait` 호출에서 timeout_ms 인자가 없을 때 사용할 디폴트. `0`이면 무한. |

---

## CLI 옵션

```
agent-agora [-h] [--port PORT] [--dir DIR] [--cert-dir CERT_DIR]
            [--no-tls]
            [--default-wait-timeout-ms MS | --no-timeout]
```

| 옵션                         | 기본값                        | 설명 |
|-----------------------------|------------------------------|------|
| `--port`                    | `8420`                       | listen 포트 |
| `--dir`                     | `.`                          | `.agentagora/` 부모 디렉터리 |
| `--cert-dir`                | `~/.agent-agora/certs`       | self-signed cert 저장소 (HTTPS 모드 한정) |
| `--no-tls`                  | (off)                        | TLS 끄고 평문 HTTP. localhost 한정. |
| `--default-wait-timeout-ms` | `60000`                      | `agora.wait` 디폴트 (헤더/인자 둘 다 없을 때). |
| `--no-timeout`              | (off)                        | wait 무한 블록. `--default-wait-timeout-ms`와 상호 배타. |

---

## 디자인 개요

- **Streamable HTTP MCP**: 모든 도구는 FastMCP의 `streamable_http_app()`을
  통해 노출. `Mcp-Session-Id` 헤더로 세션 식별.
- **Dispatcher**: per-instance future 기반 큐. dispatch 시 타깃의 큐에
  enqueue하고 대기 중인 future가 있으면 깨움. `_broadcast`는 발신자 제외
  모든 등록 인스턴스로 팬-아웃.
- **InstanceRegistry**: session_id ↔ instance_id 양방향 매핑. 같은
  instance_id로 새 세션이 register하면 이전 세션 매핑은 덮어씀.
- **AutoRegisterMiddleware**: ASGI 레벨에서 헤더 보고 자동 등록.
- **SessionCloseMiddleware**: HTTP 세션 종료 이벤트에 unregister 후크. 창
  닫으면 `agora.instances`에서 자동으로 사라짐.
---

## 개발 / 테스트

```bash
pip install -e ".[dev]"
pytest
```

- `tests/test_*.py`: 단위 테스트.
- `tests/test_integration.py`: dispatcher/registry/server를 in-process로
  결합한 시나리오 테스트 (A→B 디스패치, 브로드캐스트, reply writeback 등).
- 실제 HTTP transport + `Mcp-Session-Id` 헤더까지 검증하는 수동 절차는
  [`docs/manual-smoke-test.md`](docs/manual-smoke-test.md) 참고.

8개 인스턴스를 한 환경에 띄워보는 데모 셋업 예시:
[`~/AgoraTest/README.md`](../../AgoraTest/README.md) (로컬 환경 한정).

---

## v1 → v3 변경

v1은 "공유 상태 저장소(JSON Schema KV) + 명령 채널" 양립이었으나, 실측 사용
결과 KV 기능 호출이 0회로 확인되어 v3에서 제거됨. 제거 대상:

- `agora.set/get/append/delete/list` MCP 도구 5종
- `schema.py`, `store.py` 모듈
- `.agentagora/schemas.json` 파일 의존 (기존 파일은 v3 startup에서 warning 후 무시)
- `instances/commands/results/schemas` 예약 스키마명

추가된 것:

- `agora.broadcast` / `peek` / `conversation_status` / `conversations_list` / `close_thread` 도구 5종
- conversation 모델 (대화 단위 그룹핑·종료 신호·closed_by 추적)
- envelope 기반 dispatch (cc·priority·deadline_ts·closing)
- SQLite WAL 영속화 + 백그라운드 TTL/GC

KV 같은 요구가 다시 필요해지면 별 패키지로 도입 예정 (현재 계획 없음).

---

## 문서

| 종류 | 경로 | 내용 |
|------|------|------|
| 디자인 spec | [`docs/superpowers/specs/2026-05-14-agora-coordination-v3-design.md`](docs/superpowers/specs/2026-05-14-agora-coordination-v3-design.md) | v3 envelope·persistence·conversation 모델 등 핵심 변경 |
| 디자인 spec | [`docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md`](docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md) | Claude Code 플러그인 `cc-agora` (`/agora-spawn` 등 슬래시) |
| 구현 plan | [`docs/superpowers/plans/2026-05-14-agora-v3-messaging.md`](docs/superpowers/plans/2026-05-14-agora-v3-messaging.md) | v3 메시징 채널 구현 task 분해 |
| 구현 plan | [`docs/superpowers/plans/2026-05-15-cc-agora-plugin.md`](docs/superpowers/plans/2026-05-15-cc-agora-plugin.md) | cc-agora 플러그인 12-task TDD plan |
| 기능 제안 | [`docs/feature-proposals-2026-05-15.md`](docs/feature-proposals-2026-05-15.md) | 워커 brainstorming 산물 — `agora.transcript` / `agora.coverage` / `agora.reply` 등 server-side 도구 권고 |
| smoke test | [`docs/manual-smoke-test.md`](docs/manual-smoke-test.md) | HTTP transport + Mcp-Session-Id 수동 검증 절차 |

---

## 라이선스

TBD.
