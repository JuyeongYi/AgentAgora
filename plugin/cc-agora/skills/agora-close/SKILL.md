---
description: Explicitly close an agora conversation thread — dispatches closing payloads to other primary participants and transitions status to closed.
---

# /cc-agora:agora-close

자기가 참여한 conversation을 명시적으로 종결한다. spec §4.9.

## 인자

- `<conversation-id>` (필수, positional): 종결할 conversation_id.
- `--reason="<text>"` (선택): closing payload에 포함될 사유. 미명시 시 빈 문자열.

## 동작

1. `agora.close_thread(conversation_id=<arg>, reason=<--reason or "">)` MCP 도구를 호출한다(`src/agent_agora/server.py:247`).
2. 서버가 다른 primary participant 각각에 `{type:"closing", from, reason, ts}` payload를 자동 dispatch한다 — payload §5.3 표준.
3. 응답(status + closed_by 등)을 그대로 사용자에 출력한다.
4. 에러 처리(§5.6):
   - `unknown_conversation` → `[cc-agora] 대화 <conv>를 찾을 수 없습니다.`
   - `not_a_participant` → `[cc-agora] 본인은 대화 <conv>의 참여자가 아닙니다.`
   - `inbox_full` → `[cc-agora] 수신자 <id> 받은편지함이 가득 찼습니다 (N개 대기). 수신자가 wait를 못 따라가는 중입니다.`

## 예시

```
/cc-agora:agora-close conv_2026_05_15_abc --reason="작업 완료, 다음 스프린트로 이동."
```

지정 대화의 다른 참여자들에 closing 메시지가 전달되고, 대화 상태는 `closed`로 transition되며 `agora.conversation_status`가 이를 반영한다.
