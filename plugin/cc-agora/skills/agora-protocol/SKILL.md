---
description: AgentAgora worker operating protocol — how a channel-mode worker receives, processes, and replies to messages. Background knowledge applied automatically by every cc-agora worker.
user-invocable: false
---

# AgentAgora worker protocol

Standard operating rules for an AgentAgora worker (a "council member"). Every
cc-agora persona depends on this plugin, so every worker shares these rules.

## Receive cycle

This worker runs in **channel mode**. It does not block-wait for messages.

1. A `<channel source="agora-channel">` notification wakes the worker's turn.
2. Call `agora.flush` to drain the inbox immediately (non-blocking — it returns
   whatever is queued right now). The blocking `agora.wait` tool no longer exists.
3. Process each drained message.
4. Reply to the sender with `agora.dispatch`.

## Payload rules

Every message payload is a JSON object with a `msgtype` field. Worker-to-worker
messages use the `worker_freeform` schema. The payload `type` field is one of:
`task`, `reply`, `closing`, `ack`.

- A reply uses `type: "reply"` and sets `in_reply_to` to the original message id.
- `from` and `ts` are filled by the sender.

Envelope fields — `in_reply_to`, `closing`, `conversation_id`, `cc`, `priority`,
`deadline_ts`, `reply_to`, `expect_result` — are passed as `agora.dispatch`
arguments, **not** inside the payload object.

## comm-matrix awareness

A dispatch can be rejected with `comm_denied` when the communication matrix
forbids the sender→target edge. `agora.flush` returns the inbox sorted by
comm-matrix edge weight first, then message priority — the inbox is not strict
FIFO.

## Conversation etiquette

- Inherit a conversation by passing `in_reply_to` (or an explicit
  `conversation_id`) when replying.
- End a conversation with `closing: true` on the final dispatch, or with the
  `/cc-agora:agora-close` slash.
- Do not call `agora.register` / `agora.unregister` — registration is automatic
  via the `.mcp.json` `X-Agora-*` headers.

## reply_only 규칙

받은 메시지의 `envelope.reply_only`가 `true`이면 — 운영자(`operator:<username>`) 또는 다른 워커가 "답변만 받고 forward는 하지 말라"고 명시한 것이다. 이 경우:

- 받은 메시지를 다른 워커에 forward 금지.
- 답신은 sender(`operator:<username>` 등)에게만 직접 dispatch.
- 작업이 다른 워커의 협력이 필요해 보여도, 운영자에게 "이 작업은 다른 워커 도움이 필요합니다 — 어떻게 진행할까요?" 같은 답신으로 결정을 위임한다.

`reply_only`가 `false`(기본)이면 평소대로 자유롭게 dispatch.
