# AgentAgora

여러 개의 자율 에이전트(예: 다중 Claude Code 인스턴스)가 **이름 있는
인스턴스로 서로를 발견하고 메시지를 주고받는** MCP 서버.

- **메시지 채널 (v3 코어)** — 워커 인스턴스 간 dispatch / broadcast / wait,
  conversation 모델, SQLite 영속화.
- **스키마 · 봇 · 통신 매트릭스 (v4 레이어)** — 모든 메시지는 `msgtype`로
  스키마 검증되고, 봇은 스키마를 구독해 fan-out으로 받으며, 워커↔워커 통신은
  N×N ACL(comm-matrix)로 제한할 수 있다.

처음이라면 [`docs/usage-guide.md`](docs/usage-guide.md)(처음 쓰는 사람용
가이드)와 [`examples/README.md`](examples/README.md)(바로 띄워보는 예제)부터.

---

## 무엇에 쓰나

각 에이전트(Claude Code 인스턴스)는 자기만의 컨텍스트와 페르소나를 갖고
독립적으로 돌아간다. AgentAgora는 그 사이의 **공용 우체국** 역할:

- 한 PM 인스턴스가 사용자 요청을 받아 **여러 워커 인스턴스(코더·테스터·리뷰어
  등)에 일을 나눠 보낸다**.
- 워커들은 자기 차례가 올 때까지 **롱폴링으로 대기**하다가 명령이 도착하면
  처리하고 답신한다.
- 워커끼리도 서로 부를 수 있다 — 리뷰어가 테스터에게 추가 검증을 요청하는 식.
- **봇**(스키마 구독자)은 특정 `msgtype`의 메시지를 자동으로 받아 처리한다 —
  LLM 워커가 아닌 결정론적 처리기를 메시지 망에 끼워 넣는 경로.

LangGraph처럼 워크플로를 그래프로 사전 정의하지 않는다. **에이전트끼리
런타임에 서로를 발견하고 자유롭게 메시지를 주고받는** 게 핵심 차이.

전형적인 사용 사례:

- 다중 에이전트 협업 실험 (역할 분리, 책임 위임, 의견 수렴).
- LLM 기반 코드 리뷰·테스트·문서화의 분업 워크플로.
- 사람 한 명이 PM 인스턴스를 통해 워커 6~8명을 운영하는 1:N 셋업.

## 전체 흐름

```
   ┌──────────┐                          ┌──────────┐
   │   InstA  │  agora.dispatch(B, ...)   │   InstB  │
   │  (PM)    │ ───────────────────────▶ │  (worker)│
   └────┬─────┘                          └─────┬────┘
        │                                      │
        │ agora.wait()  ◀───── 응답 envelope ──┤
        │                                      │
        ▼                                      ▼
   사용자에 보고                          (작업 처리 후
                                          답신 dispatch)

    인스턴스 등록은 .mcp.json 헤더로 자동
    (X-Agora-Instance-Id 등 — 아래 '설정 헤더' 참조)
```

핵심 사이클: **등록(자동) → dispatch → wait → 답신 → 정리**.

`agora.broadcast`로 자기 제외 전원 fan-out, `agora.peek`로 큐 상태 조회,
`conversation_id`로 같은 대화에 묶어 다회차 라운드도 가능.

## 운영 패턴

가장 단순한 형태는 **로컬 한 머신에서 N개 인스턴스**:

```
~/AgoraTest/
  Inst1/          # PM (orchestrator) — .mcp.json + CLAUDE.md
  Inst2/          # general worker
  Inst3/          # researcher
  ...
  .agentagora/    # 서버 데이터 (SQLite + WAL, schemas.jsonl, comm-matrix.csv)
  run-server.bat  # agent-agora 기동 스크립트
```

각 `Inst*/` 안에서 `claude` 명령을 실행하면 그 디렉토리의 `.mcp.json` 헤더로
서버에 자동 등록된다. 각자 별도 터미널에서 띄우면 N개 에이전트가 동시에 돈다.

워커는 기본적으로 `agora.wait` 폴링으로 메시지를 받지만, Claude Code의
`claude/channel`을 활용한 **채널 모드**([`docs/channel-mode.md`](docs/channel-mode.md))를
대신 쓰면 서버 push로 워커를 깨울 수 있다 — 블록된 도구 콜 없이 진짜 idle 상태로 기다린다.

새 워커를 추가하려면 디렉토리·`CLAUDE.md`·`.mcp.json`·hook 설정을 손으로
챙겨야 하는데, 그걸 한 줄로 줄이는 Claude Code 플러그인이 별도로 있다 —
[`plugin/cc-agora/`](plugin/cc-agora/).

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

기본은 HTTPS + self-signed cert. cert는 `~/.agent-agora/certs/`에 한 번
생성되고 재사용된다. 로컬 테스트라면 `--no-tls`로 평문 HTTP 사용 가능.

```bash
agent-agora --dir . --port 8420 --no-tls
```

성공 시 출력:

```
AgentAgora starting on http://127.0.0.1:8420/mcp
  Data dir : .../.agentagora
  DB       : .../.agentagora/agora.db
  Cert     : (none -- HTTP mode, localhost only)
```

서버는 기동 시 `<dir>/.agentagora/`에 다음을 둔다 — `agora.db`(SQLite),
`schemas.jsonl`(기본 스키마, 없으면 동봉본 복사), `comm-matrix.csv`(있으면
로드, 없으면 ACL 비활성).

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

`X-Agora-Instance-Id` 헤더가 있으면 첫 MCP 요청 시 `AutoRegisterMiddleware`가
자동으로 `agora.register`를 호출한다 — 별도 register 도구 호출은 필요 없다.

### 3) 직접 띄워보기

서버 + 봇 + 워커를 파이썬 스크립트만으로 end-to-end 굴려보는 최소 예제는
[`examples/`](examples/)에 있다 — echo 봇(스키마 fan-out)과 comm-matrix
ACL 데모. [`examples/README.md`](examples/README.md) 참조.

---

## 핵심 개념

- **msgtype / 스키마** — 모든 dispatch·broadcast·bot_emit payload는 JSON
  객체이고 `msgtype` 필드가 필수다. 서버는 그 `msgtype`으로 등록된 JSON
  Schema를 찾아 payload를 검증한다. 스키마는 immutable이며 두 종류 —
  `conversation`(워커↔워커)·`bot-task`(봇 입출력). 기본 스키마 6종(`default`,
  `worker_freeform`, `bot_reply`, `bot_error`, `closing`, `ack`)이 동봉돼 있고,
  `agora.register_schema`로 런타임 추가할 수 있다.
- **워커 vs 봇** — 워커는 `agora.register`로 등록하는 LLM 인스턴스. 봇은
  `agora.register_bot`으로 등록하는 별도 네임스페이스의 스키마 구독자다.
  `handler` 봇은 구독 스키마의 메시지를 받고, `observer` 봇은 모든 메시지를
  사본으로 받는다. 봇은 dispatch/broadcast 대신 `agora.bot_emit`으로 회신한다.
- **schema-routed dispatch** — `agora.dispatch`에 `target`을 생략하면 payload의
  `msgtype`을 구독한 핸들러 봇에게 fan-out된다 (어느 봇이 받는지 사전에 몰라도 됨).
- **통신 매트릭스(comm-matrix)** — 워커가 다른 워커에게 dispatch할 수 있는지를
  N×N ACL로 강제한다. `.agentagora/comm-matrix.csv`가 있으면 startup에 로드,
  없으면 비활성(전부 허용). 봇으로 가는 schema-routed 메시지나 cc는 대상이 아니다.

---

## MCP 도구 레퍼런스

### 메타

- **`agora.info()`** — 서버 경로/포트/uptime 반환.

### 스키마

- **`agora.register_schema(name, body, kind, purpose)`** — 스키마 등록.
  `body`에 `msgtype` property 필수. immutable — 같은 이름·다른 body는 거부.
  `kind`는 `"conversation"` 또는 `"bot-task"`.
- **`agora.schemas()`** — 등록된 스키마 전체(name·kind·purpose·body).
- **`agora.schemas_list()`** — 스키마 메타데이터만 (body 제외).

### 인스턴스 디렉터리

- **`agora.register(instance_id, role="worker", description="", wait_mode=None)`** —
  세션을 인스턴스 이름에 바인딩. 헤더 자동 등록을 쓰면 호출 불필요.
- **`agora.register_bot(instance_id, description, bot_mode="handler", subscribe_schemas=None, emit_schemas=None, schemas=None)`** —
  세션을 봇으로 등록. `handler`면 `subscribe_schemas`(모두 `bot-task` kind) 필수.
  `observer`면 스키마 무관 전체 메시지를 cc로 수신. `schemas`로 신규 스키마를
  등록과 동시에 인라인 정의할 수 있다. 파이썬 봇은 `agent_agora.bot.AgoraBot`([`docs/bot-sdk.md`](docs/bot-sdk.md))을 상속하면
  등록·wait 루프·회신을 SDK가 처리한다.
- **`agora.unregister()`** — 현재 세션 해제 (워커·봇 모두). 멱등.
- **`agora.instances()`** — 등록된 워커 인스턴스 나열 (큐 깊이·in-flight 포함).
- **`agora.bots()`** — 등록된 봇만 나열 (구독 스키마 포함).
- **`agora.find(query)`** — 워커·봇을 통합 검색. 결과는 `kind: worker|bot`로 태깅.

### 명령 채널

- **`agora.dispatch(payload, target=None, expect_result=False, cc=None, reply_to=None, in_reply_to=None, conversation_id=None, closing=False, priority="normal", deadline_ts=None)`** — 발신.
  - `payload`: JSON 객체. `msgtype` 필수 — 등록 스키마로 검증된다.
  - `target`: **단일 instance_id**. 생략하면 payload `msgtype`을 구독한 봇에게
    schema-routed (구독 봇이 없으면 `no_route`).
  - `cc`: observer 목록 — 사본만 받고 응답 의무 없음.
  - `conversation_id`: 명시하면 그 대화에 묶임. 미지정 시 서버가 자동 부여.
  - `closing=True`: 송신 측 종료 신호. `priority`: `"low"|"normal"|"high"`.
- **`agora.broadcast(payload, expect_result=False, ...)`** — 자기 제외 등록된 모든
  워커로 fan-out + 구독 봇에게도 전달. comm-matrix에 막힌 대상은 `denied`로 보고.
- **`agora.bot_emit(payload, in_reply_to=None)`** — 봇 전용 회신. `in_reply_to`를
  주면 원 메시지의 발신자에게, 생략하면 payload `msgtype` 구독 봇에 fan-out.
- **`agora.wait(timeout_ms=None, from_sources=None, by_conversation=None, sort="fifo")`** —
  자기 큐에 쌓인 명령을 드레인. 워커·봇 모두 사용.
  - 타임아웃 우선순위: 인자 → 헤더 `X-Agora-Wait-Timeout-Ms` → 서버 CLI 기본값.
    `0`이면 무한 블록.
  - `from_sources` / `by_conversation`: AND 결합 필터. 미매칭 envelope는 큐 보존.
  - `sort="priority"`: high → normal → low 순.
- **`agora.peek(targets=None)`** — 큐 길이·in-flight 카운트 등 비파괴 조회.

### 대화

- **`agora.conversation_status(conversation_id)`** — 한 대화의 메타(참가자·메시지
  수·closed_by) 조회.
- **`agora.conversations_list(participant=None, status=None, limit=100)`** — 대화 목록.
- **`agora.close_thread(conversation_id, reason="")`** — 자기 쪽 close 신호 박기.

### 통신 매트릭스

- **`agora.register_comm_matrix(csv_text)`** — 워커↔워커 ACL을 CSV 텍스트로 런타임
  교체. 형식은 [`examples/README.md`](examples/README.md) 참조. 서버 전역에 적용.

---

## 설정 헤더

`.mcp.json`의 `headers`에 박을 수 있는 키들:

| 헤더                          | 효과 |
|------------------------------|------|
| `X-Agora-Instance-Id`         | 첫 요청에서 자동 register (필수). |
| `X-Agora-Role`                | 자동 register 시 role. 기본 `worker`. |
| `X-Agora-Description`         | 자동 register 시 description. 기본 빈 문자열. |
| `X-Agora-Wait-Timeout-Ms`     | `agora.wait`에 timeout_ms 인자가 없을 때 쓸 디폴트. `0`이면 무한. |

---

## CLI 옵션

```
agent-agora [-h] [--port PORT] [--dir DIR] [--cert-dir CERT_DIR] [--no-tls]
            [--db-path DB_PATH] [--max-inbox-depth N]
            [--close-timeout-ms MS] [--dead-session-timeout-ms MS]
            [--gc-retention-days DAYS] [--gc-hour HOUR]
            [--default-wait-timeout-ms MS | --no-timeout]
```

| 옵션                         | 기본값                        | 설명 |
|-----------------------------|------------------------------|------|
| `--port`                    | `8420`                       | listen 포트 |
| `--dir`                     | `.`                          | `.agentagora/` 부모 디렉터리 |
| `--cert-dir`                | `~/.agent-agora/certs`       | self-signed cert 저장소 (HTTPS 모드 한정) |
| `--no-tls`                  | (off)                        | TLS 끄고 평문 HTTP. localhost 한정. |
| `--db-path`                 | `<dir>/.agentagora/agora.db` | SQLite 경로 |
| `--max-inbox-depth`         | `100`                        | 인스턴스별 대기 큐 상한. `0`이면 무제한. |
| `--close-timeout-ms`        | `300000`                     | half_closed 대화의 자동 close TTL. |
| `--dead-session-timeout-ms` | `1800000`                    | 무응답 인스턴스 자동 해제 임계. |
| `--gc-retention-days`       | `90`                         | closed 대화 메시지 보존 기간. |
| `--gc-hour`                 | `3`                          | 일일 메시지 GC 실행 시각(UTC). |
| `--default-wait-timeout-ms` | `60000`                      | `agora.wait` 디폴트 (헤더/인자 둘 다 없을 때). |
| `--no-timeout`              | (off)                        | wait 무한 블록. `--default-wait-timeout-ms`와 상호 배타. |

---

## 디자인 개요

- **Streamable HTTP MCP**: 모든 도구는 FastMCP의 `streamable_http_app()`을 통해
  노출. `Mcp-Session-Id` 헤더로 세션 식별.
- **Dispatcher**: per-instance future 기반 큐 + SQLite cold path. dispatch 시
  타깃 큐에 enqueue하고 대기 중 future가 있으면 깨운다. 매 메시지에서 payload
  `msgtype`를 스키마 검증하고, 워커→워커 dispatch면 comm-matrix ACL을 확인한다.
- **InstanceRegistry / BotRegistry**: 워커·봇을 각각 별도 네임스페이스로 관리.
  `session_id ↔ instance_id` 양방향 매핑. `BotRegistry`는 구독 스키마 역인덱스로
  fan-out 라우팅을 지원한다.
- **SchemaRegistry**: name → JSON Schema. 컴파일된 validator를 캐시. immutable.
- **CommMatrix**: 워커↔워커 dispatch N×N ACL. CSV로 로드/교체.
- **AutoRegisterMiddleware**: ASGI 레벨에서 `X-Agora-*` 헤더를 보고 자동 등록.
- **백그라운드 sweep**: 60초 주기로 close TTL·dead-session 정리, 일 1회 메시지 GC.

---

## 개발 / 테스트

```bash
pip install -e ".[dev]"
pytest
```

- `tests/test_v3_*`: v3 메시징 코어 (dispatcher·registry·persistence·recovery·TTL/GC).
- `tests/test_v4_*`: v4 레이어 (schemas·schema 강제·bot registry·routing·comm-matrix).
- `tests/test_plugin_*`: cc-agora 플러그인.
- `tests/test_integration.py`: dispatcher/registry/server in-process 결합 시나리오.
- 실제 HTTP transport를 굴려보는 예제는 [`examples/`](examples/) 참조.

---

## v1 → v3 → v4 변경

**v1 → v3** — v1은 "공유 상태 저장소(JSON Schema KV) + 명령 채널" 양립이었으나,
실측 사용 결과 KV 호출이 0회로 확인되어 v3에서 제거됨. `agora.set/get/...` 도구
5종과 `schema.py`·`store.py`가 빠지고, `agora.broadcast`/`peek`/conversation
모델·envelope 기반 dispatch·SQLite WAL 영속화가 들어왔다.

**v3 → v4** — 메시지 채널 위에 세 레이어를 추가:

- **스키마 강제** — 모든 payload에 `msgtype` 필수, 등록 JSON Schema로 검증.
  `agora.register_schema`/`schemas`/`schemas_list` 도구.
- **봇 라우팅** — `BotRegistry` + 스키마 구독 fan-out. `agora.register_bot`/
  `bots`/`bot_emit` 도구, schema-routed dispatch(`target` 생략).
- **통신 매트릭스** — 워커↔워커 dispatch N×N ACL. `agora.register_comm_matrix` 도구.

설계 이력은 `docs/superpowers/specs/`의 각 design spec에 보존돼 있다.

---

## 문서

| 종류 | 경로 | 내용 |
|------|------|------|
| 사용 가이드 | [`docs/usage-guide.md`](docs/usage-guide.md) | 처음 쓰는 사람용 — 서버·워커·봇·매트릭스 단계별 |
| 봇 SDK | [`docs/bot-sdk.md`](docs/bot-sdk.md) | AgoraBot 봇 SDK 사용법 |
| 채널 모드 | [`docs/channel-mode.md`](docs/channel-mode.md) | claude/channel push로 워커를 깨우는 모드 (폴링 대안) |
| 실행 예제 | [`examples/README.md`](examples/README.md) | echo 봇 + comm-matrix 데모 실행 가이드 |
| 디자인 spec | [`docs/superpowers/specs/2026-05-15-cc-agora-bots-design.md`](docs/superpowers/specs/2026-05-15-cc-agora-bots-design.md) | 스키마·봇 pub/sub broker 모델 |
| 디자인 spec | [`docs/superpowers/specs/2026-05-15-comm-matrix-design.md`](docs/superpowers/specs/2026-05-15-comm-matrix-design.md) | 워커↔워커 통신 ACL |
| 디자인 spec | [`docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md`](docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md) | Claude Code 플러그인 `cc-agora` |
| 구현 plan | [`docs/superpowers/plans/`](docs/superpowers/plans/) | 위 spec들의 task 분해 plan |
| 백로그 | [`docs/backlog.md`](docs/backlog.md) | 미뤄둔 작업·향후 기능 후보 |
| smoke test | [`docs/manual-smoke-test.md`](docs/manual-smoke-test.md) | HTTP transport + Mcp-Session-Id 수동 검증 절차 |

---

## 라이선스

TBD.
