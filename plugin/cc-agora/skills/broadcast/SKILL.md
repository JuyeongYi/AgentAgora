---
description: Broadcast a task or closing announcement to all registered cc-agora instances — auto-fills payload, separates envelope flags like priority and conversation_id.
---

# /cc-agora:broadcast

모든 등록 인스턴스에 fan-out 한다. spec §4.6.

## 인자

- `"<message>"` (필수): 자연어 본문. 따옴표로 감싼다.
- `--closing` (선택): announcement 패턴. 회의 종료·시스템 셧다운 등 한 방향 종결 신호. 일상 fan-out에는 쓰지 않는다.
- `--priority=low|normal|high` (선택): 큐 정렬용 메타. 디폴트 `normal`. 실제 정렬은 수신자가 `agora.flush(sort="priority")`로 켤 때만 활성.
- `--conv=<id>` (선택): `conversation_id`. 기존 스레드에 묶을 때 사용.
- `--expect` (선택): `expect_result=true`. 워커 페르소나에 응답을 요구하는 신호.

## 동작

### payload 자동 채움 (§5.3)

`scripts/payload.py::make_payload`를 따른다:

- `--closing`이 **없으면** `type="task"` + `message=<arg>` + `from=<자기 instance_id>` + `ts=<ISO 8601 UTC>`.
- `--closing`이 **있으면** `type="closing"` + `from` + `ts` (message·reason 없이 announcement).

자기 instance_id는 등록 시점 또는 `agora.instances()` 결과에서 자기 항목으로 알아낸다.

### envelope vs payload 분리 (§5.3 명시 규약)

`closing`, `priority`, `conversation_id`, `expect_result`, `reply_to`, `in_reply_to`, `deadline_ts`는 도구 인자로 직접 전달한다 — **payload 안에 박지 않는다.**

### MCP 호출

```
agora.broadcast(
  payload=<위 payload>,
  closing=<--closing bool>,
  priority=<--priority or "normal">,
  conversation_id=<--conv or None>,
  expect_result=<--expect bool>,
)
```

응답을 그대로 사용자에 출력한다. `inbox_full` 에러는 §5.6 한국어 표준 메시지로 안내한다.

## 예시

```
/cc-agora:broadcast "오늘 18:00에 코드 리뷰 회의 시작합니다." --priority=high
```

모든 등록 워커에 `{type:"task", from, ts, message}` payload가 priority=high envelope과 함께 전달된다.

```
/cc-agora:broadcast "세션 종료 — 다음 회의는 내일." --closing
```

`type="closing"` announcement가 모두에게 즉시 전달되고 관련 대화가 close된다.
