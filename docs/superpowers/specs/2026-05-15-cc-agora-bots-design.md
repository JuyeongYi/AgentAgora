# cc-agora Bots — Design Spec (v4: pub/sub broker 모델 + schema 정합 정정)

- 날짜: 2026-05-15
- 대상 코드: AgentAgora 서버 (`src/agent_agora/`) + cc-agora plugin v2.2 (`plugin/cc-agora/`)
- 베이스: [`2026-05-15-cc-agora-plugin-design.md`](2026-05-15-cc-agora-plugin-design.md) (v2.1)
- 결정 방식: 사용자와 sequential 합의. 본 spec은 4번 진화했다 — §6 결정 트레일에 v1→v2→v3→v4 evolution 보존.
- v4 트리거: 8-인스턴스 공동 review(§6 결정 18)에서 v3의 Critical 자기모순 3건이 검출됨 — 본 버전은 그 정정본이다.

## 0. 설계 진화 요약

| 버전 | 모델 | 폐기/정정 사유 |
| ---- | ---- | -------- |
| v1 | 봇이 `agora.wait` long-poll + 자체 schema protocol | "MCP와 겹친다"는 통찰로 재검토 |
| v2 | 봇 = MCP server, AgentAgora가 proxy/broker | 호출 주도권이 여전히 caller에 — 봇의 *수동 감시* 본질 못 살림 |
| v3 | 봇 = AgentAgora에 attach된 schema subscriber. broker가 schema 매칭 자동 fan-out | 결정 17(generic schema 폐기)이 본문 4곳과 자기모순 — back-compat 붕괴 |
| **v4** | v3 모델 유지 + schema 정합 정정 (결정 18~20) | (현행) |

**v3 turning point** (사용자 통찰): "MCP는 *agent*에 붙어 agent가 상황 보고 tool을 *명시 호출*한다. agora-bot은 *AgentAgora*에 붙어 메시지 흐름을 *감시*하다 자기 schema에 맞으면 *자동 반응*한다." → 봇은 inversion of control. caller가 봇을 고르는 게 아니라, 메시지가 흐르고 broker가 schema로 라우팅한다.

**v4 turning point** (8-인스턴스 review): v3 결정 17은 "generic `string`/`jsonl` 폐기, 소스코드 `default` schema 하나"를 못박았으나, 같은 문서의 §2 non-goal·§7·§8.9·§9.1이 여전히 "generic schema가 v3 워커 free-form payload를 흡수"를 전제했다. 더 심각하게 `default` body(`{timestamp, level, msg, category}` + `additionalProperties:false`, 로그 엔트리 형태)로는 기존 워커 payload(`{msgtype, type, from, ts, message}`)가 100% `schema_violation`으로 깨진다. v4는 (1) `msgtype` 필수 단일화, (2) LLM 워커 통신 전용 `worker_freeform` schema를 `default`와 *별개로* 소스코드 기본 제공에 존치, (3) 모든 schema body가 `msgtype` property를 명시하도록 정정한다.

## 1. 배경

### 1.1 MCP vs agora-bot

| | MCP | agora-bot |
| --- | --- | --- |
| 무엇에 attach | agent (LLM) | AgentAgora (broker) |
| 호출 주도권 | agent가 상황 인지 후 *명시 선택·호출* | broker가 메시지 흐름에서 schema 매칭 *자동 라우팅* |
| 봇/tool의 성격 | 능동 invocation 대상 | 수동 subscriber — schema match 시 자동 반응 |
| 발견 | agent가 `tools/list` | orchestrator가 `agora.bots` / `agora.find` |

봇은 *결정적 backend 처리*를 담당한다 — pytest 실행, 빌드 트리거, metric 적재 등. LLM이 아니므로 입력 형식이 *예측 가능*해야 하고(→ schema), 능동적으로 일을 벌이지 않는다(→ reply만, fan-out 자동 반응).

### 1.2 대표 use case

- `bot_pytest_runner` — `pytest_run` schema 구독. orchestrator가 `{msgtype:"pytest_run", ...}` 메시지를 흘리면 자동 수신 → 실행 → 결과를 `agora.bot_emit`으로 전파.
- `bot_metric_logger` — `metric_log` schema 구독. 여러 워커가 metric을 흘리면 fan-out으로 모두 수신, emit 없음 (적재만).
- `bot_transcript_archiver` — `bot-observer` 모드. schema 무관 모든 메시지 cc로 받아 archive.

## 2. 목표 / Non-goals

### 목표

1. **봇 = schema subscriber** — AgentAgora에 attach. broker가 schema 매칭으로 envelope 자동 fan-out.
2. **Schema Registry 부활** — runtime mutable, `name:body` (JSON Schema). v1 모델 복귀.
3. **단일 구독 + 결과 emit** — 봇은 `subscribe_schemas`로 처리할 schema를 구독하고(다봇 OK), 결과는 `agora.bot_emit`으로 비동기 전파한다 (결정 25).
4. **broker routing** — caller는 봇을 명시 선택하지 않아도 됨. schema가 routing key.
5. **observer 모드** — schema 무관 전체 메시지 cc.
6. **클라이언트 보강** (별도 plugin spec v2.2) — `/cc-agora:agora-spawn-bot`, bot manifest, 봇 boilerplate.
7. **(v4) schema 정합** — 모든 schema body가 `msgtype` property를 명시하고, LLM 워커 free-form 통신을 담는 `worker_freeform` schema가 소스코드 기본 제공된다 (결정 18~20).

### Non-goals (명시 제외)

- **봇 = MCP server (v2 모델)** — 폐기. 봇은 MCP *client* (wait subscriber). §6 결정 11.
- **봇의 자발적 dispatch** — reply (`in_reply_to`)만 허용. 자발적 새 task·broadcast 금지. 결정 3.
- **봇의 동기 RPC** — 봇은 모두 fire-and-forget. caller가 봇 결과를 동기로 기다리지 않는다. 결과는 `agora.bot_emit`이 비동기 전파한다 (결정 25).
- **봇 측 listener** — 봇은 outbound HTTP listener를 띄우지 않는다. `agora.wait` long-poll client. 결정 13.
- **LLM 워커 통신 형식 강제** — `worker_freeform` schema가 자연어 free-form을 흡수한다. msgtype만 `"worker_freeform"`으로 박으면 `message` 필드가 자유 형식. v4 §3.2·§5.3.
- **`msgtype` 미지정 허용** — 폐기. 모든 payload는 `msgtype` 필수, 미지정 fallback schema는 없다 (결정 18). v3 §3.2의 "미지정 시 default" 절은 §3.4와 모순이라 삭제됐다.
- **Streaming progress** — 봇의 중간 progress 알림. 후속.
- **Schema 완전 immutability** — v4에서 완화 검토(결정 20·§7). 동일 이름 + body 불변 원칙은 유지하되 BACKWARD-compatible additive evolution을 후속 우선순위로 상향.

## 3. 컴포넌트

### 3.1 봇 = schema subscriber (MCP client)

봇은 표준 MCP client다. AgentAgora의 `agora.*` 도구만 사용한다 — 자기 MCP server를 띄우지 않는다.

봇의 lifecycle:

1. `agora.register_bot(bot_mode="handler", subscribe_schemas=[...], ...)` 로 등록 + 구독 선언.
2. `agora.wait(timeout_ms=0)` long-poll loop.
3. envelope 수신 → `payload.msgtype` 확인 → 해당 handler 함수 실행.
4. 결과를 알리려면 `agora.bot_emit(payload, in_reply_to=<cmd_id>)`. 알릴 결과가 없으면 생략 (fire-and-forget).
5. 루프 반복.

봇은 LLM이 아니므로 페르소나·CLAUDE.md·Stop hook이 없다. 순수 코드 loop.

### 3.2 Schema Registry (부활)

`src/agent_agora/schemas.py` 신규. runtime mutable 카탈로그 — `dict[name, body]` + `threading.Lock`. SQLite 영속.

**모든 메시지는 schema를 따른다 — 예외 없음 (결정 17·18).** payload는 `msgtype`이 *필수*다. `msgtype` 미지정은 `payload_missing_msgtype` 에러로 거부된다 — v3의 "미지정 시 default 적용" fallback은 §3.4의 "msgtype 필수"와 모순이라 v4에서 삭제됐다 (결정 18).

#### 기본 제공 schemas — `.agentagora/schemas.jsonl`에서 실행 시점 등록 (결정 21)

schema 카탈로그의 초기 등록은 소스코드 하드코딩이 아니라 **`.agentagora/schemas.jsonl`** 파일에서 이뤄진다. 서버 시작 시 이 파일의 각 라인(line-delimited JSON — `{"name": ..., "kind": "conversation"|"bot-task", "purpose": "<언제 쓰는 schema인지>", "body": {...JSON Schema...}}`)을 registry에 등록한다.

`.agentagora/schemas.jsonl`이 없으면 서버는 **repo 동봉 `default_schemas.jsonl`**(bare-minimum schema 묶음)을 `.agentagora/`로 복사한 뒤 로드한다. schema body를 Python 소스코드에 dict로 하드코딩하지 않는다 (결정 21) — 그래야 사용자가 코드 배포 없이 파일만 편집해 schema를 고칠 수 있다. 사용자는 이 파일에 도메인 schema를 직접 추가할 수 있고, 봇이 `register_bot`의 `schemas` 인자로 넣는 schema는 runtime 등록분이다.

| name | 용도 |
| ---- | ---- |
| `default` | 로그 엔트리 표준 형식. `msgtype: "default"`로 *명시* 지정한 메시지에 적용. (미지정 fallback 아님 — 결정 18.) |
| `worker_freeform` | **(v4 신규)** LLM 워커 간 자연어 free-form 통신 표준. `message` 필드가 자유 텍스트. v3 워커 payload가 착지하는 schema (결정 19). |
| `bot_reply` | 봇 처리 결과 표준 (`bot_emit` payload). |
| `bot_error` | 봇 handler 실패 표준. |
| `closing` / `ack` | 대화 종결 / forward 통지. |

**모든 schema는 `kind`와 `purpose` 메타를 가진다 (결정 23).** `kind`는 둘 중 하나다:

- `"conversation"` — 에이전트(워커) 간 대화용. `worker_freeform`, `default`, `closing`, `ack` 등. **봇이 구독할 수 없다.**
- `"bot-task"` — 봇 작업 요청용. 봇이 구독하는 도메인 schema.

`purpose`는 "언제 쓰는 schema인지"를 적은 한 줄 설명으로, `agora.schemas_list`·`agora.find`가 노출해 caller가 schema 선택을 판단하는 근거가 된다.

주고받는 메시지는 *기본적으로 에이전트 간 대화*(`conversation` kind)다. 봇이 등록하는 schema는 반드시 `bot-task` kind여야 하며 — 봇이 `conversation` schema를 구독하면 워커끼리의 모든 대화를 가로채므로 `register_bot`이 거부한다. caller가 봇에 작업을 보내려면 `bot-task` schema로 `msgtype`을 박는다. **그 자체가 "봇 전용 경로로 던진다"는 명시**다 — 별도 플래그·전용 도구 없이 `msgtype`의 kind가 경로를 가른다.

**모든 schema body는 `msgtype` property를 명시한다 (결정 20).** `additionalProperties: false`인 schema가 `msgtype` property를 빠뜨리면, §3.4의 "payload는 `msgtype` 필수"와 충돌해 *라우팅 가능한 모든 메시지*가 `schema_violation`으로 거부된다 (v3 Critical 결함). 따라서 `default`를 포함한 모든 기본 제공·도메인 schema는 `properties.msgtype`을 반드시 포함한다.

`default` schema body (JSON Schema Draft 2020-12) — v4 정정 (`msgtype` property 추가):

```json
{
  "type": "object",
  "required": ["msgtype", "timestamp", "level", "msg", "category"],
  "properties": {
    "msgtype":   {"type": "string", "const": "default"},
    "timestamp": {"type": "string", "format": "date-time"},
    "level":     {"type": "string", "enum": ["debug", "info", "warn", "error"]},
    "msg":       {"type": "string"},
    "category":  {"type": "string"}
  },
  "additionalProperties": false
}
```

예시 payload:

```json
{"msgtype": "default", "timestamp": "2024-01-01T10:00:00Z", "level": "info", "msg": "서버 시작", "category": "system"}
```

`worker_freeform` schema body (v4 신규 — v3 워커 통신 흡수, §9.1 정합):

```json
{
  "type": "object",
  "required": ["msgtype", "type", "from", "ts", "message"],
  "properties": {
    "msgtype": {"type": "string", "const": "worker_freeform"},
    "type":    {"type": "string", "enum": ["task", "reply", "closing", "ack"]},
    "from":    {"type": "string"},
    "ts":      {"type": "string", "format": "date-time"},
    "message": {"type": "string"}
  },
  "additionalProperties": true
}
```

`worker_freeform`은 `additionalProperties: true` — LLM 워커가 자유롭게 보조 필드를 덧붙이는 현실(`in_reply_to`, `subject`, role 메타 등)을 흡수하기 위함. 반대로 `default`(로그)와 봇 schema는 `additionalProperties: false`로 엄격히 닫는다 — 결정적 backend 처리는 입력이 예측 가능해야 하기 때문(§1.1).

`type` enum 4종(`task`/`reply`/`closing`/`ack`)은 [`cc-agora-plugin-design.md`](2026-05-15-cc-agora-plugin-design.md) §5.3과 동일하다 — single source는 plugin §5.3이며 본 schema가 이를 참조한다 (미결 A 정합).

`bot_reply` schema body (봇 결과 표준 — `kind: "bot-task"`, §9.11):

```json
{
  "type": "object",
  "required": ["msgtype", "from", "ts", "result"],
  "properties": {
    "msgtype": {"type": "string", "const": "bot_reply"},
    "from":    {"type": "string"},
    "ts":      {"type": "string", "format": "date-time"},
    "result":  {}
  },
  "additionalProperties": false
}
```

`bot_error` schema body (봇 처리 실패 — `kind: "bot-task"`):

```json
{
  "type": "object",
  "required": ["msgtype", "from", "ts", "error_code", "error_message"],
  "properties": {
    "msgtype":       {"type": "string", "const": "bot_error"},
    "from":          {"type": "string"},
    "ts":            {"type": "string", "format": "date-time"},
    "error_code":    {"type": "string"},
    "error_message": {"type": "string"},
    "traceback":     {"type": "string"}
  },
  "additionalProperties": false
}
```

`closing` schema body (대화 종결 — `kind: "conversation"`):

```json
{
  "type": "object",
  "required": ["msgtype", "from", "ts"],
  "properties": {
    "msgtype": {"type": "string", "const": "closing"},
    "from":    {"type": "string"},
    "ts":      {"type": "string", "format": "date-time"},
    "reason":  {"type": "string"}
  },
  "additionalProperties": false
}
```

`ack` schema body (forward 통지 — `kind: "conversation"`):

```json
{
  "type": "object",
  "required": ["msgtype", "from", "ts", "ack_for"],
  "properties": {
    "msgtype": {"type": "string", "const": "ack"},
    "from":    {"type": "string"},
    "ts":      {"type": "string", "format": "date-time"},
    "ack_for": {"type": "string"}
  },
  "additionalProperties": false
}
```

도메인 schema는 봇·admin이 `agora.register_schema`로 추가한다.

#### 핵심 함수

```python
class SchemaRegistry:
    def register(self, name: str, body: dict, registered_by: str | None) -> None: ...  # 동일 이름 + 다른 body → ValueError(schema_immutable). body에 msgtype property 없으면 ValueError(schema_missing_msgtype).
    def get(self, name: str) -> dict | None: ...
    def validator(self, name: str) -> Draft202012Validator | None: ...   # 컴파일된 검증기 캐시 (hot path)
    def list_meta(self) -> list[dict]: ...
```

`register`는 등록 시 body가 `properties.msgtype`을 포함하는지 검증한다 (결정 20). 누락 시 `schema_missing_msgtype`.

### 3.3 등록 경로 — 참가자와 봇 분리 (결정 16)

등록 경로가 둘이다. **참가자(worker)와 봇은 별개 네임스페이스**이며 명단도 분리된다 (§3.9).

#### `agora.register` — 참가자(worker) 전용

```
agora.register(instance_id, role, description="", wait_mode=None) -> dict
```

기존 v3 그대로. 봇 관련 인자 없음. LLM 워커는 `.mcp.json` 헤더로 `AutoRegisterMiddleware` 자동 등록.

#### `agora.register_bot` — 봇 전용 (신규)

```
agora.register_bot(
    instance_id: str,
    description: str,                              # 필수 (결정 9)
    bot_mode: Literal["handler","observer"] = "handler",
    subscribe_schemas: list[str] = [],             # 봇이 처리하는 schema. 다봇 구독 OK (결정 25).
    emit_schemas: list[str] = [],                  # bot_emit으로 흘릴 결과 schema 사전 선언 (선택).
    schemas: dict[str, dict] = {},                 # 신규 schema body 동시 등록 (결정 6, 7)
) -> dict
```

봇은 `.mcp.json` 헤더 자동 등록을 *쓰지 않는다* — 봇은 코드 loop이라 헤더 부트스트랩이 불필요하고, 명시 `agora.register_bot` 도구 호출이 자연스럽다. 봇 식별은 *어느 등록 도구를 호출했는가*로 결정된다 (`bot_*` prefix 같은 이름 규칙 폐기 — 결정 10).

#### 검증 규칙

- `description` 필수 (`description_required`).
- `bot_mode == "handler"` → `subscribe_schemas`가 비어있지 않아야 (`subscribe_required`).
- `bot_mode == "observer"` → `subscribe_schemas`/`emit_schemas` 무시 (schema 무관 전체 수신).
- `subscribe_schemas`는 다봇 구독 OK — 같은 schema를 여러 봇이 구독하면 매칭 시 모두에 fan-out (결정 25, RPC 단일 봇 제약 폐기).
- 모든 schema 이름은 registry에 존재해야. 미존재는 `schemas` 인자로 동시 등록.
- 구독 schema(`subscribe_schemas`)는 모두 `kind: "bot-task"`여야 한다. `conversation` kind schema 구독 시도는 `cannot_subscribe_conversation`으로 거부 — 봇이 워커 대화를 가로채는 것을 차단 (결정 23).
- **(v4) schema diff preflight** — `schemas` 인자의 schema 이름이 registry에 *이미 다른 body로* 존재하면 `schema_immutable`로 봇 기동 *전에* 차단한다. 이는 봇 코드 안 schema body를 고친 채 재배포할 때 발생하는 deadlock(§9.9)을 등록 시점에 명시적으로 드러낸다.

### 3.4 Dispatcher fan-out 라우팅

#### Envelope schema validation

모든 `agora.dispatch`/`agora.broadcast`의 payload는 `msgtype` 필수 (`payload_missing_msgtype`). registry에서 schema 조회 후 validate. 실패 → `schema_violation`. 미존재 → `unknown_msgtype`. `msgtype` 미지정 fallback은 없다 (결정 18).

#### Routing — 봇 체커 우선 (결정 22)

**어떤 참가자(worker)·봇의 큐에 enqueue하기 전에, 모든 메시지는 먼저 봇 체커를 통과한다.** 봇 체커는 `payload.msgtype`을 `BotRegistry`의 schema 역인덱스와 대조해 매칭 봇을 결정하는 단계다. target이 worker든 bot이든, target만 지정됐든 broadcast든 — 이 단계를 우회하는 메시지는 없다.

caller가 `agora.dispatch`/`agora.broadcast` 호출 시 broker의 처리 순서:

1. **schema validation** — payload `msgtype` 필수 + registry validate.
2. **봇 체커** — `msgtype`을 구독하는 봇을 `BotRegistry` 역인덱스로 조회. 매칭 봇 집합 결정.
3. **enqueue** — 다음 수신자 큐에 envelope을 넣는다:
   - **target 인스턴스** — `target` 명시 시 그 인스턴스 (delivered_as=`primary`). worker든 bot이든.
   - **schema 매칭 봇** — 2단계 결과 (delivered_as=`subscribed`). 같은 schema를 구독한 봇이 여럿이면 모두에 fan-out. target이 그 봇과 같으면 중복 enqueue 안 함.
   - **observer** — 모든 bot-observer (delivered_as=`cc`).

#### target 생략 (schema-routed dispatch)

`agora.dispatch`에서 `target`을 생략할 수 있다 (신규). 이때:

- `payload.msgtype`을 구독하는 봇 전부가 수신 (다봇이면 fan-out). primary 없음 — schema-routed.
- 어느 봇도 구독 안 하는 schema + target 없음 → `ValueError("no_route: <msgtype>")`.

즉 caller는 *봇을 명시 선택할 필요 없이* schema만 맞추면 broker가 라우팅. 사용자 통찰 "봇은 감시·자동반응"의 핵심.

### 3.5 Routing 매트릭스

| caller 호출 | 도달 |
| ----------- | ---- |
| `dispatch(target=worker_X, payload)` | worker_X (primary) + msgtype 구독 봇 fan-out + observer |
| `dispatch(target=bot_X, payload)` | bot_X — 단 bot_X가 그 msgtype 구독해야 (미구독 `unhandled_schema`) + observer |
| `dispatch(payload)` target 생략 | msgtype 구독 봇 전부 fan-out + observer |
| `broadcast(payload)` | 모든 worker + msgtype 구독 봇 fan-out + observer |
| `bot_emit(payload, in_reply_to=X)` | broker가 X의 원 source에 라우팅 + observer |
| `bot_emit(payload)` | msgtype 구독 봇 fan-out + observer |

### 3.6 봇 결과 emit (결정 25)

봇은 모두 fire-and-forget이다 — 동기 reply가 없다. caller가 봇 schema(`kind: "bot-task"`)로 메시지를 흘리면 봇이 받아 처리한다. `expect_result`는 봇 대상에 무의미하다.

봇이 처리 결과를 알리려면 **`agora.bot_emit`** 전용 도구를 쓴다:

```
agora.bot_emit(payload, in_reply_to: str | None = None)
```

- `in_reply_to` **지정 시** — broker가 원 메시지의 `source`를 찾아 그 인스턴스 큐에 결과를 enqueue. 봇은 원 caller가 누구인지 몰라도 된다.
- `in_reply_to` **미지정 시** — `payload.msgtype`을 구독하는 봇·대상에 schema-routed fan-out.
- `payload`는 다른 메시지와 동일하게 schema validation을 거친다. 봇이 `register_bot`의 `emit_schemas`로 결과 schema를 사전 선언하면 caller가 결과 형식을 미리 안다.

봇은 `agora.dispatch`·`agora.broadcast`를 호출할 수 없다 — 두 도구는 봇에 노출되지 않는다. 따라서 봇이 특정 참가자 큐를 직접 고르는 경로는 존재하지 않으며, 결과 전파는 항상 broker가 매개한다.

### 3.7 봇 emit payload 규약

- `agora.bot_emit`의 `payload`는 `msgtype`이 필수이며 registry schema를 통과해야 한다.
- 결과 표준 schema — `bot_reply`(정상 결과) / `bot_error`(처리 실패). 봇이 도메인 결과 schema를 쓰려면 등록 필요.
- 봇 실패도 *조용히 사라지지 않는다* — handler 예외 시 봇 SDK가 `bot_error`를 `in_reply_to=<원 cmd_id>`로 emit한다. caller는 `bot_error` 수신으로 봇이 실패했음을 안다.

### 3.8 observer

- `bot-observer` 모드는 schema 무관 *모든* dispatch/broadcast를 `delivered_as='cc'`로 수신.
- 응답 없음 — observer의 dispatch도 차단.
- inbox_full 시 누락 허용 (advisory). `skipped_full`에 보고.
- use case — transcript archive, metric 집계, audit.

### 3.9 Discovery 도구

- `agora.register_schema(name, body)` — schema 등록. immutable. body에 `msgtype` property 필수 (결정 20).
- `agora.schemas()` / `agora.schemas_list()` — 카탈로그 전체 / 메타.
- `agora.instances()` — **참가자(worker)만** 반환. 봇 제외 (결정 10·16).
- `agora.bots()` — **봇만** 반환. `bot_mode` + description + subscribe_schemas + emit_schemas.
- `agora.find(query)` — 참가자 + 봇 *모두* 검색 (description·role·구독 schema 이름 매칭). 결과 항목에 `kind: "worker" | "bot"` 표시.

`agora.instances`와 `agora.bots`의 명단이 분리되는 이유 (결정 10·16) — 봇은 *대화 참가자*가 아니라 *broker에 attach된 backend*다. orchestrator가 위임 후보를 고를 때 보는 참가자 명단에 봇이 섞이면 LLM 워커 매칭이 흐려진다. 둘을 한 번에 보려면 `agora.find`로 통합 검색.

### 3.10 봇 클라이언트 boilerplate

```python
# bot_pytest_runner.py — 표준 MCP client
import asyncio
from agora_bot_sdk import BotClient   # cc-agora plugin v2.2 제공 (얇은 wrapper)

bot = BotClient(
    instance_id="bot_pytest_runner",
    description="Run pytest scenarios on demand.",
    agora_url="http://127.0.0.1:8420/mcp",
)

@bot.handler("pytest_run", schema={...JSON Schema, properties.msgtype 포함...})
async def pytest_run(args: dict, envelope) -> dict:
    # ... handler. return 값이 있으면 SDK가 agora.bot_emit으로 전파 ...
    return {"msgtype": "bot_reply", "passed": 12, "failed": 0}

@bot.handler("metric_log", schema={...properties.msgtype 포함...})
async def metric_log(args: dict, envelope) -> None:
    # ... fire-and-forget handler. return None이면 emit 없음 ...
    pass

if __name__ == "__main__":
    asyncio.run(bot.run())   # register + wait loop + bot_emit 자동
```

`BotClient` SDK는 register + wait loop + schema validate + handler 디스패치 + reply 전송을 wrap. 봇 작성자는 handler 함수만 작성. SDK는 schema body에 `msgtype` property가 없으면 등록 전 `schema_missing_msgtype`을 raise한다 (결정 20). SDK는 plugin spec v2.2 범위.

### 3.11 cc-agora plugin v2.2 (요약, 별도 spec)

- `/cc-agora:agora-spawn-bot <id> <bot.json>` — bot manifest 셋업.
- `bot.json` — `description`, `handler_modules`, `schemas{name:body}`.
- 봇 디렉토리 — `bot.py` (BotClient 사용) + `bot.json` + `.mcp.json` (등록 헤더). `CLAUDE.md`/preset 없음.
- `templates/bot.py.template` — BotClient boilerplate.
- `agora_bot_sdk` 패키지.

## 4. 운영 규약

### 4.1 envelope `delivered_as` 확장

| 값 | 의미 |
| -- | ---- |
| `primary` | 명시 target. |
| `cc` | 명시 cc observer 또는 bot-observer. |
| `subscribed` (신규) | schema 매칭으로 fan-out된 봇. 봇이 처리 책임. |

봇은 envelope의 `delivered_as`로 자기가 *책임 수신자(subscribed)*인지 *관찰자(cc)*인지 구분.

### 4.2 Schema validation 비용

`Draft202012Validator(body)` 객체를 registry가 schema별로 컴파일·캐싱. 매 dispatch마다 재컴파일 금지 (hot path).

### 4.3 Schema immutability (v4 완화 검토)

동일 이름 재등록 — body 같으면 idempotent, 다르면 `schema_immutable` ValueError. 변경 필요 시 새 이름.

**(v4) 한계 인지** — 완전 immutability는 봇 redeploy deadlock(§9.9)을 일으킨다. 봇 코드 안 schema body에 필드를 추가하면 재시작 시 `register_bot`이 `schema_immutable`로 실패해 봇이 기동 자체를 못 한다. v4는 두 가지로 대응한다 — (1) `register_bot` schema diff preflight(§3.3)로 deadlock을 등록 시점에 명시적으로 표면화, (2) §7의 BACKWARD-compatible additive evolution(optional field 추가만 허용)을 후속 우선순위로 상향. day-1 범위는 (1)까지, 자동 버저닝은 §7 후속.

### 4.4 봇 reply schema

봇 `bot_emit` payload의 `msgtype`은 registry에 존재해야 한다. 봇이 도메인 결과 schema를 쓰려면 등록 필요. `bot_reply`/`bot_error`는 항상 사용 가능.

### 4.5 에러 응답 한국어 (cc-agora plugin §5.6 확장)

| 코드 | 메시지 |
| ---- | ------ |
| `payload_missing_msgtype` | `[agora] payload에 msgtype이 없습니다. 모든 메시지는 msgtype이 필수입니다.` |
| `unknown_msgtype` | `[agora] msgtype '<x>'는 registry에 없습니다.` |
| `schema_violation` | `[agora] schema_violation: <상세>` |
| `schema_immutable` | `[agora] schema '<name>'는 다른 body로 이미 등록됨.` |
| `schema_missing_msgtype` | `[agora] schema '<name>' body에 msgtype property가 없습니다. (결정 20)` |
| `no_route` | `[agora] msgtype '<x>'를 구독하는 봇이 없고 target도 없습니다.` |
| `unhandled_schema` | `[agora] 봇 <id>는 msgtype '<x>'를 구독하지 않습니다.` |
| `bot_emit_not_a_bot` | `[agora] agora.bot_emit은 봇만 호출할 수 있습니다.` |
| `description_required` | `[agora] 봇 mode는 description이 필수입니다.` |
| `subscribe_required` | `[agora] bot-handler는 구독 schema가 비어있을 수 없습니다.` |

## 5. 데이터 모델 변경

### 5.1 데이터 모델 — 참가자와 봇 분리 (결정 16)

`InstanceInfo`(참가자)는 v3 그대로 — 봇 필드를 추가하지 않는다. 봇은 별도 dataclass + 별도 registry.

```python
@dataclass(frozen=True)
class BotInfo:
    instance_id: str
    session_id: str
    description: str
    bot_mode: Literal["handler", "observer"]
    subscribe_schemas: tuple[str, ...] = ()           # 구독 schema (다봇 OK)
    emit_schemas: tuple[str, ...] = ()                # bot_emit 결과 schema (선택 사전 선언)
    registered_at: str = ""
    last_seen_at: str | None = None


class BotRegistry:
    """InstanceRegistry와 병렬. 봇 전용 네임스페이스.
    subscribe schema → 다봇 역인덱스 (fan-out 라우팅용)를 보관."""
    ...
```

`agora.instances`는 `InstanceRegistry`만, `agora.bots`는 `BotRegistry`만 조회. `agora.find`는 둘 다 훑어 `kind` 표시. dispatcher의 fan-out 라우팅(§3.4)은 `BotRegistry`의 schema 역인덱스로 매칭 봇을 찾는다.

### 5.2 SQLite migration (v2)

```sql
CREATE TABLE IF NOT EXISTS schemas (
    name TEXT PRIMARY KEY,
    body TEXT NOT NULL,                 -- JSON Schema (properties.msgtype 필수 — 결정 20)
    registered_at TEXT NOT NULL,
    registered_by TEXT
);

CREATE TABLE IF NOT EXISTS bot_subscriptions (
    instance_id TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('subscribe','emit')),
    PRIMARY KEY (instance_id, schema_name),
    FOREIGN KEY (schema_name) REFERENCES schemas(name)
);
CREATE INDEX IF NOT EXISTS idx_bot_sub_schema ON bot_subscriptions(schema_name);
```

`messages` 테이블은 `delivered_as` CHECK에 `'subscribed'` 추가. 서버 재시작 시 schema·subscription 복원. 시작 시 소스코드 기본 제공 schema(`default`, `worker_freeform`, `bot_reply`, `bot_error`, `closing`, `ack`)를 idempotent 재등록한다.

### 5.3 v3 워커 통신 회귀 (worker_freeform)

기존 v3 LLM 워커는 payload를 free-form으로 보낸다 — `{msgtype, type, from, ts, message, ...}`. v4에서 이들은 `msgtype: "worker_freeform"`을 박아 `worker_freeform` schema로 validate된다. `worker_freeform`의 `additionalProperties: true` 덕에 워커가 덧붙이는 보조 필드(`in_reply_to`, `subject`, role 메타)는 통과한다. 워커 측 변경은 `msgtype` 값 하나를 `"worker_freeform"`으로 고정하는 것뿐 — `.mcp.json` 헤더 또는 워커 preset에서 기본값으로 주입 가능.

## 6. 결정 트레일

### v1 → v2 → v3 → v4 evolution

- **v1** — 봇이 `agora.wait` long-poll + 자체 schema protocol. 결정 1~12 (schema registry, name:body, RPC/oneway 함수 분리 등).
- **v2** — 사용자 통찰 "봇 = MCP server와 겹친다" → 봇을 MCP server로, AgentAgora를 proxy로 재설계. 결정 11(옵션 X), 12~14.
- **v3** — 사용자 통찰 "MCP는 agent에 붙어 명시 호출, 봇은 AgentAgora에 붙어 메시지 감시·자동반응" → proxy 모델 폐기, **pub/sub broker 모델**로 재설계. v1의 wait 기반 + schema registry 부활. 결정 15~17.
- **v4** — 8-인스턴스 공동 review에서 결정 17이 본문 4곳과 자기모순함이 검출됨. broker 모델 자체는 유지하되 schema 정합을 정정. 결정 18~20.

### 결정 1~10 (v1, 대부분 v3에서 부활)

| # | 결정 | v4 상태 |
| - | ---- | ------- |
| 1 | Schema 강제 + generic fallback | **변경** — schema 강제 유지, 단 "fallback"이 아닌 명시 `worker_freeform` schema (결정 18·19). |
| 2 | 봇 수신 = schema routing | **부활·강화** — broker fan-out. |
| 3 | 봇 dispatch = reply만 | **유지**. |
| 4 | produces schema 선언 | **변경** — reply는 registry schema (bot_reply/bot_error 또는 도메인). |
| 5 | 처리 schema = 봇 등록 시 선언 | **유지** — `subscribe_schemas`. |
| 6 | Schema registry runtime mutable | **부활**. |
| 7 | Schema 등록 형태 name:body | **부활·강화** — body에 msgtype property 필수 (결정 20). |
| 8 | 봇 목록·schema 조회 도구 | **유지** — `agora.bots`/`agora.schemas`. |
| 9 | 봇 description 필수 | **유지**. |
| 10 | `bot_*` prefix convention only | **변경** — prefix 폐기. 별도 등록 도구로 식별 (결정 16). |

### 결정 11 — 옵션 X (MCP server 봇) 채택 후 철회

- **v2 확정**: 봇 = MCP server. **v3에서 철회**.
- **트레일**: 사용자 1차 통찰 "봇은 MCP와 겹친다"로 옵션 X 채택. 그러나 2차 통찰 "MCP는 명시 호출, 봇은 감시·자동반응"으로, MCP-server 모델은 *호출 주도권*이 caller에 남아 봇의 본질(수동 subscriber)과 어긋남이 드러남. v3 pub/sub로 회귀.
- **보존 가치**: 봇과 MCP의 *형식적 유사성*(schema=tool)은 사실이나, *제어 흐름*이 반대 — MCP는 caller-driven, 봇은 broker-driven. 이 구분이 v3·v4의 핵심.

### 결정 12 — Fire-and-forget = oneway schema 구독

- **확정**: `subscribe_oneway_schemas`. RPC와 *함수 레벨 분리* (사용자 결정 11). oneway는 다봇 fan-out.
- **폐기 (결정 25)**: 모든 봇이 fire-and-forget으로 통합되어 RPC/oneway 구분 자체가 소멸. `subscribe_schemas` 하나만 남는다.

### 결정 13 — 봇 = MCP client (wait subscriber)

- **확정**: 봇은 listener를 띄우지 않는다. `agora.wait` long-poll. broker가 envelope push, 봇이 pull.

### 결정 14 — broker가 routing 주체

- **확정**: caller는 봇을 명시 선택할 필요 없음. `target` 생략 가능, `payload.msgtype`이 routing key.

### 결정 15 — RPC schema는 단일 봇

- **확정**: `subscribe_schemas`(RPC) schema는 한 봇만 구독. 두 번째 구독 시도 `rpc_schema_taken`. oneway는 다봇 OK.
- **트레일**: RPC는 reply가 *하나*여야 caller의 expect_result가 일관. fan-out RPC면 N reply로 caller 혼란.
- **폐기 (결정 25)**: RPC 개념 소멸. 모든 봇 schema는 다봇 구독 OK이며, 다봇이면 메시지가 전부에 fan-out된다.

### 결정 16 — 참가자와 봇 등록 경로·명단 분리

- **확정**: 등록 경로 둘 — `agora.register`(worker) / `agora.register_bot`(bot). 조회 명단 둘 — `agora.instances`(worker만) / `agora.bots`(bot만). 봇은 *참가자 명단에서 제외*. 둘을 한 번에 보려면 `agora.find`.
- **트레일**: 봇은 *broker에 attach된 backend*이지 *대화 참가자*가 아니므로 orchestrator의 위임 후보 명단에서 빠져야 매칭이 흐려지지 않는다.

### 결정 17 — 모든 메시지 schema 필수 (v4에서 §3.2 fallback 절 정정)

- **v3 확정**: 모든 dispatch/broadcast payload는 schema를 따른다. `msgtype` 미지정 시 단일 `default` schema 적용. generic `string`/`jsonl` 폐기.
- **v4 정정**: "msgtype 미지정 시 default 적용" 절은 §3.4의 "msgtype 필수"와 직접 모순(미지정 상태가 존재할 수 없음)이라 **삭제**. `msgtype`은 *항상 필수*이며 미지정 fallback은 없다. `default` schema는 폐기되지 않고 `msgtype: "default"`로 *명시* 지정하는 로그 엔트리 schema로 남는다. "generic schema 폐기"는 결정 19로 부분 번복된다.
- **유지**: schema 강제 원칙("무조건 스키마를 쓰게 한다"). 로그 엔트리 default schema가 하나라는 점.

### 결정 18 — v3 결정 17의 자기모순 검출 (8-인스턴스 review)

- **트리거**: 8개 인스턴스(orchestrator + 7 worker)가 v3 spec을 공동 review. 6개 워커가 독립적으로 동일 Critical 자기모순을 지목.
- **검출된 Critical 자기모순 3건**:
  1. **결정 17 ↔ §2·§7·§8.9·§9.1** — 결정 17은 generic `string`/`jsonl` 폐기를 못박았으나 네 곳이 여전히 generic schema 존재를 전제. `default` body(로그 엔트리)로는 v3 워커 payload가 100% `schema_violation`.
  2. **`default` schema에 `msgtype` property 부재** — `additionalProperties: false`인데 `msgtype` property가 없어, `msgtype`을 단 모든 라우팅 가능 메시지가 `schema_violation`으로 거부됨.
  3. **§3.2 "msgtype 미지정 시 default" ↔ §3.4 "msgtype 필수"** — 필수라면 미지정 상태가 불가능, §3.2 fallback 절이 dead clause.
- **확정 해소**: (1) → 결정 19, (2) → 결정 20, (3) → 결정 17 v4 정정(§3.2 fallback 절 삭제, msgtype 필수 단일화).
- **경험적 입증**: review 직전 동일 인스턴스들이 진행한 envelope-spec 토론의 모든 dispatch가 `{from, type, message, ts}` 형태였다 — `default` body로 검증 시 100% 회귀. 이 사실이 (1)의 severity를 경험적으로 확정.

### 결정 19 — worker_freeform schema 소스코드 기본 제공

- **확정**: LLM 워커 free-form 통신 전용 `worker_freeform` schema를 `default`와 *별개로* 소스코드 기본 제공 schema에 존치한다. body는 `{msgtype, type, from, ts, message}` required + `type` enum 4종 + `additionalProperties: true`.
- **트레일**: 8-인스턴스 review의 reviewer 권고 (a) 채택. 결정 17 트레일의 "재도입 트리거"(default 하나로 표현 못 하는 트래픽 누적 시 추가 generic schema 등록)와 정합하며, v3 워커 마이그레이션 비용이 0에 가깝다(`msgtype` 값 하나 고정). writer 보강 — `string`이라는 이름은 "결정 17 = default 하나"와 혼동을 부르므로 `worker_freeform`으로 명명.
- **`default`와의 구분**: `default`는 로그 엔트리(`additionalProperties: false`, 엄격), `worker_freeform`은 워커 통신(`additionalProperties: true`, 보조 필드 흡수). 둘은 별개 schema이며 "default schema는 하나"는 *로그 엔트리 default가 하나*라는 의미로 좁혀진다.

### 결정 20 — 모든 schema body에 msgtype property 필수

- **확정**: registry에 등록되는 모든 schema body(기본 제공·도메인 포함)는 `properties.msgtype`을 명시해야 한다. `SchemaRegistry.register`가 등록 시 검증하고, 누락 시 `schema_missing_msgtype`.
- **트레일**: 8-인스턴스 review에서 coder·writer가 독립 검출. `additionalProperties: false`인 schema가 `msgtype` property를 빠뜨리면 `msgtype` 필수 규칙(§3.4)과 충돌해 모든 메시지가 거부된다. reviewer 권고 — validate 전 `msgtype` strip 방식보다 "모든 body가 msgtype property 명시"가 안전하다. strip은 모든 validator 경로에 숨은 전처리를 강제해 누락 시 silent-pass 진입로가 된다.

### 결정 21 — schema 초기 등록은 `.agentagora/schemas.jsonl`

- **확정**: schema 카탈로그 초기 등록은 `.agentagora/schemas.jsonl`에서. 파일이 없으면 repo 동봉 `default_schemas.jsonl`(bare-minimum 묶음)을 복사. schema body를 Python 소스코드에 하드코딩하지 않는다.
- **트레일**: 사용자 — "기본적으로 .agentagora/schemas.jsonl에 있는건 실행 시점에 등록", "bare-minimum 용도로 몇 가지 만들도록, 소스코드에 박지는 않는 것으로". 소스코드 하드코딩은 schema를 코드 배포 없이 못 고치게 만든다. 파일 기반은 사용자 직접 편집 + repo 버전관리가 가능하다.
- **bare-minimum 묶음**: `worker_freeform`, `default`, `closing`, `ack` (모두 conversation kind). 봇 결과 schema(`bot_reply`/`bot_error`)는 미결 결정 B(봇 fire-and-forget 전환)에 종속 — 확정 시 추가.

### 결정 22 — 봇 체커 우선 라우팅

- **확정**: 모든 dispatch/broadcast는 어느 큐에 enqueue하기 전 봇 체커(schema 매칭)를 통과한다. target이 worker든 bot이든 우회 불가.
- **트레일**: 사용자 — "어떤 참가자의 큐에 넣건, 모든 메시지는 봇 체커에 먼저 들어가야 한다". 봇의 *수동 감시* 본질(§1.1)을 라우팅 순서로 못박았다.

### 결정 23 — schema kind (conversation / bot-task) + purpose

- **확정**: 모든 schema는 `kind`(`"conversation"` | `"bot-task"`)와 `purpose`(한 줄 용도 설명) 메타를 가진다. 봇은 `bot-task` schema만 구독 가능. caller가 `bot-task` schema로 `msgtype`을 박는 것이 곧 "봇 경로" 명시 — 별도 플래그·전용 도구가 필요 없다.
- **트레일**: 사용자 — "주고받는 메시지는 기본적으로 에이전트간 대화용 스키마. 봇이 등록하는 스키마는 이 점을 감안", "스키마 등록 시 언제 쓰는지까지 있어야 함", "봇 전용 queue에 던지라고 명시할 수 있어야". `kind`가 대화/봇 경로를 가르고, `purpose`가 caller의 schema 선택 근거가 된다. 봇이 `conversation` schema를 구독하면 워커 대화를 전부 가로채므로 금지된다.

### 결정 24 — `worker_freeform` `additionalProperties: true` (E2)

- **확정**: `worker_freeform`은 `additionalProperties: true`. LLM 워커가 보조 필드를 자유롭게 덧붙이는 현실을 흡수한다. payload/envelope 중복 시 *envelope 인자가 truth*, payload 측 중복 필드는 무시된다.
- **트레일**: 사용자 E2 채택. `false`(엄격)는 LLM 워커의 비결정적 출력에 취약하다 — 사소한 필드 추가 하나로 메시지가 통째 `schema_violation`. 봇 schema와 `default`(로그)는 `additionalProperties: false`로 엄격히 닫고, 워커 대화 schema(`worker_freeform`)만 연다.

### 결정 25 — 봇 fire-and-forget + schema-routed 결과 emit (B2)

- **확정**: 봇은 모두 fire-and-forget이다. RPC/oneway 구분 폐기 — `subscribe_schemas` 단일 list. 봇은 `target` 지정 dispatch·`agora.broadcast`를 못 한다(도구 미노출). 봇이 처리 결과를 흘리려면 `agora.bot_emit(payload, in_reply_to=<원 cmd_id|None>)` 전용 도구를 쓴다 — 봇은 수신자를 *고르지 않고*, broker가 `in_reply_to`로 원 caller를 찾아 그 인스턴스 큐로 라우팅하거나(in_reply_to 지정 시), `payload.msgtype` 구독자에 schema-routed fan-out한다(미지정 시).
- **트레일**: 사용자 — "봇은 큐에 넣지 않는다 → 모든 게 fire-and-forget. 두 타입 나누는 것도 의미 없어질 듯." B1(봇 outgoing 0, pure sink)은 pytest_runner처럼 결과가 쓸모의 핵심인 봇을 무력화한다. B2 채택 — 봇은 결과를 emit하되 *특정 큐를 직접 고르지 않는다*. broker가 매개한다.
- **연쇄 정리**:
  - 결정 3(봇 dispatch는 reply만) → 결정 25로 대체.
  - 결정 11·12·15(RPC/oneway 함수 분리·oneway·RPC 단일 봇) → RPC 개념 소멸로 폐기.
  - `subscribe_schemas` + `subscribe_oneway_schemas` → `subscribe_schemas` 하나. 봇 schema는 다봇 구독 OK(`rpc_schema_taken` 폐기).
  - `expect_result` 봇 대상 무의미 — 봇은 동기 reply가 없다.
- **봇 도구 표면**: `agora.register_bot`, `agora.wait`, `agora.bot_emit` 3개뿐. `agora.dispatch`/`agora.broadcast`는 봇에 노출되지 않으므로, 봇이 특정 참가자 큐에 직접 넣을 수단 자체가 없다.

### 결정 트레일 — review 진행 메타

8-인스턴스 review는 orchestrator(Inst1)가 broker로 spec 파일 경로를 fan-out, 7개 워커가 각자 Read로 파일을 읽고 역할 관점에서 검토 → reviewer(Inst5) 단일 hub로 수렴 → reviewer가 6건 종합 판정(Critical 3 / Important 2). 이 절차 자체가 v4 broker 모델의 fan-out + 단일 hub 수렴 패턴의 실증이다.

## 7. 의문점·후속 작업

- **Schema versioning (우선순위 상향)** — v4는 완전 immutability의 redeploy deadlock(§9.9)을 인지했다. 후속 — Confluent Schema Registry식 BACKWARD-compatible additive evolution: optional field 추가만 허용, required·routing-relevant 필드 변경은 금지. `name@version` 자동 부여 + 버전 미지정 dispatch는 broker가 최신으로 라우팅. day-1 범위는 `register_bot` schema diff preflight(§3.3)까지.
- **다봇 구독 시 중복 처리** — 같은 schema를 N봇이 구독하면 한 메시지를 N봇이 모두 처리한다. 의도된 fan-out이지만, competing-consumer(하나만 처리하는 부하분산)가 필요하면 후속 — `subscribe_schemas`에 `load_balance=true` 옵션?
- **schema-routed dispatch에서 구독 봇이 전부 죽어 있을 때** — `no_route`. caller가 재시도 정책 결정.
- **observer backpressure** — observer가 모든 메시지 fan-out 수신. inbox_full 자주. observer 전용 큰 inbox depth.
- **봇 SDK (`agora_bot_sdk`)** — register + wait loop + handler dispatch wrap. plugin spec v2.2.
- **Streaming progress** — 봇 장기 작업의 중간 progress. 후속.
- **Schema 등록 RBAC** — 누구나 등록 가능. 외부 사용자 발생 시 admin token.
- **봇이 LLM 워커 메시지를 "엿듣는" 범위** — handler 봇은 schema 매칭만, observer 봇은 전체. 워커끼리의 `worker_freeform` 메시지를 handler 봇이 보려면 그 워커가 도메인 schema로 보내야. 의도된 경계.

## 8. 구현 우선순위 (의존성 트리)

v3의 선형 list는 critical path를 가렸다. v4는 의존성 트리로 재구성하고, 모든 scope의 root 결정 노드를 §8-0으로 명시한다.

### §8-0. ROOT 결정 노드 (해소 완료)

`generic schema 존치 여부` — v3에서 이 노드가 미해결인 채 §1 Schema Registry의 scope조차 확정 불가했다. **v4에서 결정 19(`worker_freeform` 존치) + 결정 17 정정으로 해소.** 이하 모든 항목은 이 노드 위에 선다.

### 의존성 트리

```
§8-0 generic schema 존치 (결정 19) ── 해소
  │
  ├─ 1. Schema Registry (schemas.py)
  │     소스코드 기본 제공: default, worker_freeform, bot_reply, bot_error, closing, ack
  │     모든 body에 msgtype property (결정 20) + validator 캐시 + schema_missing_msgtype 검증
  │     │
  │     ├─ 2. SQLite migration v2 (schemas, bot_subscriptions, delivered_as CHECK)
  │     │
  │     ├─ 3. BotRegistry + BotInfo (InstanceRegistry와 병렬, subscribe schema 역인덱스)
  │     │     │
  │     │     └─ 5. server.py 도구 (register_bot, register_schema, schemas, bots, find 확장)
  │     │           register_bot schema diff preflight (§3.3) 포함
  │     │           │
  │     │           └─ 6. Dispatcher 라우팅 보강
  │     │                 dispatch/broadcast schema validation (msgtype 필수)
  │     │                 fan-out (primary + subscribed + cc)
  │     │                 target 생략 schema-routed dispatch
  │     │                 다봇 구독 fan-out / agora.bot_emit 라우팅 / 봇은 dispatch·broadcast 도구 미노출
  │     │
  │     └─ 4. 봇 등록 — 헤더 변경 없음 (register_bot 명시 호출, AutoRegisterMiddleware는 worker 전용 유지)
  │
  └─ 7. 에러 한국어화 (§4.5 표)

8. 통합 테스트 (1~7 완료 후) — §8.8
9. plugin spec v2.2 (별도) — /cc-agora:agora-spawn-bot, agora_bot_sdk, bot.py.template
```

### §8.8 통합 테스트

- schema routing fan-out, 다봇 구독 fan-out, target 생략 라우팅, observer 전체 수신, `agora.bot_emit` 라우팅(in_reply_to 유무), 봇 결과 chain conversation.
- **worker_freeform 회귀** — v3 워커 payload(`{msgtype:"worker_freeform", type, from, ts, message, +보조필드}`)가 `worker_freeform` schema를 통과하는지. v3 §5.3 type enum 4종 정합.
- **msgtype property 검증** — `msgtype` property 없는 schema body 등록 시 `schema_missing_msgtype`. `default` 포함 모든 기본 제공 schema가 `msgtype` property를 가지는지.
- **msgtype 필수** — `msgtype` 없는 payload dispatch 시 `payload_missing_msgtype`. (v3 §8.8-9의 "generic string 흡수 회귀"는 worker_freeform 회귀로 대체됨.)
- **schema diff preflight** — 동일 이름 다른 body로 `register_bot` 시 `schema_immutable`로 기동 전 차단.

## 9. 자기 모순·구현 시 충돌 가능 지점

- **9.1 worker_freeform schema와 v3 §5.3 type enum 정합** — 기존 워커 payload가 `worker_freeform` schema(`{msgtype, type, from, ts, message}` required + `type` enum 4종 + `additionalProperties: true`)를 통과해야 회귀 없음. 워커는 `msgtype: "worker_freeform"` 고정.
- **9.2 schema-routed dispatch + target 동시 명시** — caller가 target도 주고 msgtype도 봇 구독 schema면? 권장: target 우선, 매칭 봇에도 둘 다 전달(primary + subscribed).
- **9.3 봇이 결과를 emit 안 하고 죽음** — 봇은 fire-and-forget이라 caller in_flight hang은 없으나, 기대한 결과가 영영 안 온다. 봇 다운 감지는 §7 후속.
- **9.4 봇 대상 expect_result** — 봇은 fire-and-forget이라 `expect_result`가 무의미. broker는 봇 대상 메시지의 `expect_result`를 무시한다. caller는 봇 결과를 `agora.bot_emit` 흐름으로 받는다.
- **9.5 observer가 자기 자신 메시지 수신** — 봇은 dispatch 못 하므로 자기발 메시지 없음. reply는 cc됨 — observer가 reply도 봄. 명세 명시.
- **9.6 schema 등록과 구독의 atomicity** — `register(schemas={...}, subscribe_schemas=[...])`가 schema 등록 일부 실패 시. 모든 schema 사전 검증(msgtype property 포함) 후 일괄 등록, 부분 등록 금지.
- **9.7 fan-out 트래픽** — 한 schema를 N봇이 구독 + M 메시지 = N×M envelope. inbox_full 위험. 봇도 wait를 부지런히 돌면 완화. observer는 누락 허용이나 handler 봇은 누락 불가 — inbox depth 충분히.
- **9.8 schema 구독 봇이 전부 unregister된 뒤** — 그 schema는 `no_route`. 다른 봇이 이어받으려면 재구독. broker는 unregister 시 subscription도 제거.
- **9.11 봇 결과 schema의 kind (미해결)** — 봇이 `agora.bot_emit`으로 흘리는 결과 schema(`bot_reply` 등)의 `kind`가 모호하다. 워커가 받으면 conversation 성격, 다른 봇이 받으면 bot-task 성격. 현재는 `bot-task`로 두되 — 워커가 봇 결과를 받을 때는 `in_reply_to` 라우팅으로 받으므로(구독이 아님) kind 제약과 무관하다. 결과 schema를 *구독*하려는 봇이 생기면 재검토.
- **9.9 봇 redeploy deadlock (v4 신규)** — 봇 v1.1이 handler 입력에 필드를 추가하려고 코드 안 schema body를 고치면, 재시작 시 `register_bot`이 `schema_immutable`로 실패해 봇이 기동 자체를 못 한다. 운영자가 풀 길은 schema 이름 변경뿐이고, 그 순간 그 msgtype으로 dispatch하던 모든 caller가 `unknown_msgtype`/`no_route`로 깨진다. **v4 대응**: (1) `register_bot` schema diff preflight(§3.3)가 deadlock을 기동 전에 `schema_immutable`로 명시 표면화, (2) §7의 BACKWARD-compatible additive evolution을 후속 우선순위로 상향. day-1은 (1)까지, 자동 버저닝은 §7.
- **9.10 msgtype property 누락 schema (v4 신규, 해소됨)** — `additionalProperties: false`인 schema body가 `msgtype` property를 빠뜨리면 `msgtype` 필수 규칙과 충돌해 모든 메시지가 거부된다. 결정 20이 `SchemaRegistry.register`의 등록 시 검증(`schema_missing_msgtype`)으로 닫는다.
