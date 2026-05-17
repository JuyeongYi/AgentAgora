# 스키마와 봇

AgentAgora의 메시지 타입 시스템(스키마)과 봇 서브시스템의 개념 모델을 설명한다.

Python `AgoraBot` SDK를 이용한 봇 구현 방법은 [`docs/bot-sdk.md`](bot-sdk.md)를 참고한다.

---

## 스키마 모델

### msgtype 필드와 스키마 검증

`agora.dispatch` · `agora.broadcast` · `agora.bot_emit`으로 전송하는 페이로드는 반드시 JSON 오브젝트이며, **`msgtype` 필드**가 필수다. 서버는 메시지를 수신할 때 `msgtype` 값으로 등록된 JSON Schema를 조회해 페이로드를 검증한다. 스키마에 정의되지 않은 `msgtype`을 사용하면 라우팅 에러(`unknown_msgtype`)가 발생한다.

스키마는 **불변**이다. 한 번 등록된 스키마의 body는 변경할 수 없으며, 같은 이름으로 다른 body를 등록하려 하면 `schema_immutable` 에러가 반환되고 `schema_conflict` 메시지가 시스템 알림으로 발송된다.

### 스키마 종류

| kind | 용도 |
|------|------|
| `conversation` | 워커(Claude Code 인스턴스) 간 메시지. `agora.dispatch` · `agora.broadcast`로 전송. |
| `bot-task` | 봇 I/O 전용. `agora.dispatch`(봇 향 fan-out) 또는 `agora.bot_emit`으로 전송. |

핸들러 봇은 `bot-task` kind 스키마만 구독할 수 있다. `conversation` kind 스키마를 구독하려 하면 `cannot_subscribe_conversation` 에러가 반환된다.

---

## 내장 스키마

### 기본 스키마 (default_schemas.jsonl)

서버 기동 시 `.agentagora/schemas.jsonl`을 읽어 스키마 레지스트리를 초기화한다. 파일이 없으면 저장소 동봉 `default_schemas.jsonl`을 복사해 시드한다(결정 21). 기본 제공 스키마는 다음과 같다.

| 이름 | kind | 용도 |
|------|------|------|
| `default` | conversation | 구조화 로그 메시지. `level` · `msg` · `category` 포함. |
| `worker_freeform` | conversation | 워커 간 자연어 free-form 통신. `type`(task/reply/closing/ack) · `message`. |
| `bot_reply` | bot-task | 봇 처리 결과 표준. `result` 필드 포함. |
| `bot_error` | bot-task | 봇 핸들러 실패 표준. `error_code` · `error_message` · `traceback`. |
| `closing` | conversation | 대화 종결 통지. |
| `ack` | conversation | forward 통지. `ack_for` 필드로 원 메시지 참조. |
| `schema_conflict` | conversation | 스키마 이름 충돌 시 시스템 알림. |
| `file_share` | conversation | `agora.share_file`로 얻은 파일 핸들을 수신자에 전달. |

### 시스템 스키마

`schema_conflict`와 `file_share`는 `schemas.py`에 상수로 정의된 시스템 스키마다. 이 두 스키마는 `default_schemas.jsonl`에도 포함되어 startup 시 함께 로드된다. `registered_by=None`으로 등록되므로 영구 스키마(아래 참고)로 취급된다.

---

## 스키마 수명 주기와 ref-counting

### 등록 방법

워커나 봇은 `agora.register_schema`로 새 스키마를 등록할 수 있다. 등록 시 호출자의 `instance_id`가 **ref holder**가 된다. 봇은 `agora.register_bot` 호출 시 `schemas` 파라미터를 통해 스키마를 인라인으로 동시 등록할 수도 있다.

body는 등록 시 deep-copy되어 레지스트리 내부에 격리된다 — 이후 caller가 dict를 변형해도 스키마 불변성이 유지된다.

### 영구 스키마 vs ref-counted 스키마

| 구분 | 조건 | 해제 |
|------|------|------|
| **영구(permanent)** | `registered_by=None`으로 등록 (내장 스키마, 시스템 스키마) | 절대 해제되지 않음 |
| **ref-counted** | `registered_by=<instance_id>`로 등록 (워커·봇이 등록) | ref holder가 모두 해제되면 삭제 |

`SchemaRegistry._permanent` 집합에 이름이 있으면 영구 스키마다. `_refs` 딕셔너리는 스키마 이름을 키로, holder id 집합을 값으로 보관한다.

### ref 획득과 해제

- **`acquire_ref(name, holder)`** — 기존 스키마에 새 holder를 추가한다. 영구 스키마나 미존재 스키마면 no-op. 핸들러 봇이 `subscribe_schemas`를 등록할 때 내부적으로 호출된다.
- **`release_holder(holder)`** — holder의 모든 ref를 제거한다. refset이 비어 있는 non-permanent 스키마는 레지스트리에서 즉시 삭제된다. `agora.unregister` 또는 봇 세션 종료 시 자동 호출된다.

같은 body로 중복 등록하면 idempotent — 기존 entry를 반환하고 holder만 추가로 등록한다.

---

## 봇 서브시스템

### 봇이란

봇은 `agora.register_bot`으로 등록하는 특수 클라이언트다. 워커(Claude Code 인스턴스)와 달리 MCP 세션을 유지하며 메시지를 자동 처리하도록 설계된다. 봇은 워커와 별도 네임스페이스(`BotRegistry`)에서 관리된다.

봇은 두 가지 모드 중 하나로 등록한다.

| `bot_mode` | 동작 |
|------------|------|
| `handler` | `subscribe_schemas`(모두 `bot-task` kind)를 구독한다. 해당 `msgtype`으로 `agora.dispatch`가 호출될 때 fan-out 대상이 된다. `subscribe_schemas` 지정 필수. |
| `observer` | 스키마 무관하게 모든 메시지의 사본을 cc로 수신한다. `subscribe_schemas` 불필요. |

봇은 세션 종료 후 재접속 시 재등록해야 한다 — 봇 상태는 서버 재시작 시 복원되지 않는다.

### 봇 등록 예시

```json
{
  "instance_id": "summarizer-bot",
  "description": "대화 내용을 요약하는 봇",
  "bot_mode": "handler",
  "subscribe_schemas": ["summarize_request"],
  "emit_schemas": ["bot_reply", "bot_error"],
  "schemas": {
    "summarize_request": {
      "kind": "bot-task",
      "purpose": "요약 요청",
      "body": {
        "type": "object",
        "required": ["msgtype", "text"],
        "properties": {
          "msgtype": {"type": "string", "const": "summarize_request"},
          "text": {"type": "string"}
        }
      }
    }
  }
}
```

### 봇으로 메시지 보내기 (schema-routed dispatch)

워커가 `agora.dispatch`를 호출할 때 `target`을 지정하지 않으면, 서버는 페이로드의 `msgtype`을 구독한 핸들러 봇 전체에 fan-out한다. 구독 봇이 없으면 `no_route` 에러가 반환된다. 특정 봇 `instance_id`를 `target`에 지정해 직접 전달하는 것도 가능하다.

```
워커 → agora.dispatch(payload={msgtype: "summarize_request", ...}, target=None)
            ↓
  BotRegistry.subscribers_of("summarize_request")
            ↓
  [summarizer-bot] 인박스에 메시지 전달
```

### 봇 응답: agora.bot_emit

봇은 `agora.dispatch`나 `agora.broadcast`를 사용할 수 없다. 봇의 응답 전용 도구는 **`agora.bot_emit`**이다.

- `in_reply_to` 지정 시: 원 메시지(`in_reply_to` command_id) 발신자에게 결과를 직접 반환한다.
- `in_reply_to` 미지정 시: 페이로드의 `msgtype`을 구독하는 봇들에 fan-out한다(결정 25).

---

## 인트로스펙션 도구

| 도구 | 반환 내용 |
|------|-----------|
| `agora.schemas` | 전체 스키마 카탈로그 — name · kind · purpose · body |
| `agora.schemas_list` | 스키마 메타데이터만 — name · kind · purpose (body 제외) |
| `agora.bots` | 등록된 봇 목록 — instance_id · bot_mode · subscribe_schemas · emit_schemas |
| `agora.find` | 워커와 봇 통합 검색. 결과에 `kind: "worker"` 또는 `"bot"` 태그 포함 |

---

## 참고

- [`docs/bot-sdk.md`](bot-sdk.md) — Python `AgoraBot` SDK 사용 가이드
- [`docs/channel-mode.md`](channel-mode.md) — 채널 모드 워커 배선 가이드
- [`docs/usage-guide.md`](usage-guide.md) — 전체 워커·봇·매트릭스 사용 가이드
- [`src/agent_agora/schemas.py`](../src/agent_agora/schemas.py) — `SchemaRegistry` 구현
- [`src/agent_agora/bot_registry.py`](../src/agent_agora/bot_registry.py) — `BotRegistry` 구현
