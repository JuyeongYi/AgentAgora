---
description: Dispatch a task to one cc-agora worker — auto-fills payload, supports reply chaining, cc observers, closing, priority, and deadline envelope flags.
---

# /cc-agora:invoke

한 워커에 작업을 dispatch 한다. spec §4.7.

## 인자

- `<instance>` (필수, positional): 수신자 instance_id.
- `"<message>"` (필수): 자연어 본문. 따옴표로 감싼다.
- `--reply-to=<cmd_id>` (선택): `in_reply_to`. 서버의 in_flight tracking 해제 연결용.
- `--conv=<id>` (선택): `conversation_id`. 계속 이어지는 스레드에 묶는다.
- `--expect` (선택): `expect_result=true`. 워커 페르소나에 응답을 요구한다.
- `--cc=<id1,id2>` (선택): 관찰자 instance_id 콤마 분리. `delivered_as='cc'`로 전달되며 응답 의무 없다.
- `--closing` (선택): `closing=true`. 직접 대화 한쪽 종결.
- `--priority=low|normal|high` (선택): 큐 정렬 메타. 디폴트 `normal`.
- `--deadline=<iso>` (선택): ISO 8601 advisory deadline. 서버는 검증만, 강제 X.

## 동작

### payload 자동 채움 (§5.3)

`scripts/payload.py::make_payload`를 따른다:

- 기본: `type="task"` + `message=<arg>` + `from=<자기 instance_id>` + `ts=<ISO 8601 UTC>`.
- `--closing`이 있으면: `type="closing"` + `from` + `ts` (message·reason 없이).

자기 instance_id는 등록 시점 또는 `agora.instances()` 결과의 자기 항목에서 얻는다.

### envelope vs payload 분리 (§5.3 명시 규약)

`in_reply_to`, `closing`, `conversation_id`, `cc`, `priority`, `deadline_ts`, `reply_to`, `expect_result`는 도구 인자로 직접 전달한다 — **payload 안에 박지 않는다.** 중복 시 envelope 우선.

### MCP 호출

```
agora.dispatch(
  target=<instance>,
  payload=<위 payload>,
  in_reply_to=<--reply-to or None>,
  conversation_id=<--conv or None>,
  expect_result=<--expect bool>,
  cc=<--cc split or None>,
  closing=<--closing bool>,
  priority=<--priority or "normal">,
  deadline_ts=<--deadline or None>,
  reply_to=None,
)
```

응답(status + assigned cmd_id 등)을 그대로 사용자에 출력한다.

### 에러 처리 (§5.6)

- `inbox_full: <target> has <N> pending` → `[cc-agora] 수신자 <id> 받은편지함이 가득 찼습니다 (N개 대기). 수신자가 메시지를 못 따라가는 중입니다.` + 보조 한 줄 "수신자 터미널을 확인하거나 `agora.flush`로 직접 드레인하세요."
- `NotRegisteredError` → `[cc-agora] 대상 <id>는 현재 등록되어 있지 않습니다. agora.instances로 확인하세요.`

## 예시

```
/cc-agora:invoke Coder1 "React 컴포넌트로 로그인 폼 작성" --expect --priority=high --cc=Reviewer1
```

Coder1에 `{type:"task", from, ts, message}`가 dispatch 되고, expect_result=true + priority=high envelope 메타가 붙으며, Reviewer1은 `delivered_as='cc'` 사본을 받아 응답 의무 없이 관찰만 한다.
