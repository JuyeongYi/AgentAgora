---
description: Explicitly close an agora conversation thread — dispatches closing payloads to other primary participants and transitions status to closed.
argument-hint: <conversation-id> [--reason="<text>"]
---

# /cc-agora:agora-close

Explicitly close a conversation you are participating in. spec §4.9.

## Arguments

- `<conversation-id>` (required, positional): The conversation_id to close.
- `--reason="<text>"` (optional): Reason included in the closing payload. Empty string if omitted.

## Behavior

1. Call the `agora.close_thread(conversation_id=<arg>, reason=<--reason or "">)` MCP tool (`src/agent_agora/server.py:247`).
2. The server automatically dispatches `{type:"closing", from, reason, ts}` payload to each other primary participant — payload §5.3 standard.
3. Print the response (status + closed_by etc.) directly to the user.
4. Error handling (§5.6):
   - `unknown_conversation` → `[cc-agora] Conversation <conv> not found.`
   - `not_a_participant` → `[cc-agora] You are not a participant in conversation <conv>.`
   - `inbox_full` → `[cc-agora] Recipient <id> inbox is full (N messages pending). The receiver is not keeping up with its inbox.`

## Example

```
/cc-agora:agora-close conv_2026_05_15_abc --reason="Task complete, moving to next sprint."
```

Closing messages are delivered to all other participants in the specified conversation, and conversation status transitions to `closed` — reflected in `agora.conversation_status`.
