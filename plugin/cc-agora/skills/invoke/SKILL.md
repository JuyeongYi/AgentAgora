---
description: Dispatch a task to one cc-agora worker — auto-fills payload, supports reply chaining, cc observers, closing, priority, and deadline envelope flags.
argument-hint: <instance> "<message>" [--reply-to --conv --expect --cc --closing --priority --deadline]
---

# /cc-agora:invoke

Dispatch a task to one worker. spec §4.7.

## Arguments

- `<instance>` (required, positional): Recipient instance_id.
- `"<message>"` (required): Natural-language body. Wrap in quotes.
- `--reply-to=<cmd_id>` (optional): `in_reply_to`. Used to release the server's in-flight tracking for the original message.
- `--conv=<id>` (optional): `conversation_id`. Binds this message to an ongoing thread.
- `--expect` (optional): `expect_result=true`. Signals the worker persona that a reply is required.
- `--cc=<id1,id2>` (optional): Observer instance_ids, comma-separated. Delivered with `delivered_as='cc'`; no reply obligation.
- `--closing` (optional): `closing=true`. One-sided close of a direct conversation.
- `--priority=low|normal|high` (optional): Queue sorting metadata. Default `normal`.
- `--deadline=<iso>` (optional): ISO 8601 advisory deadline. The server validates only — not enforced.

## Behavior

### Payload auto-fill (§5.3)

Follows `scripts/payload.py::make_payload`:

- Default: `type="task"` + `message=<arg>` + `from=<own instance_id>` + `ts=<ISO 8601 UTC>`.
- With `--closing`: `type="closing"` + `from` + `ts` (no message or reason).

Own instance_id is obtained at registration time or from the self-entry in `agora.instances()` results.

### Envelope vs payload separation (§5.3 explicit rule)

`in_reply_to`, `closing`, `conversation_id`, `cc`, `priority`, `deadline_ts`, `reply_to`, `expect_result` are passed directly as tool arguments — **not** embedded inside the payload object. Envelope takes precedence on conflict.

### MCP call

```
agora.dispatch(
  target=<instance>,
  payload=<payload above>,
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

Print the response (status + assigned cmd_id etc.) directly to the user.

### Error handling (§5.6)

- `inbox_full: <target> has <N> pending` → `[cc-agora] Recipient <id> inbox is full (N messages pending). The receiver is not keeping up with its inbox.` + one supplemental line: "Check the receiver's terminal or drain it directly with `agora.flush`."
- `NotRegisteredError` → `[cc-agora] Target <id> is not currently registered. Check with agora.instances.`

## Example

```
/cc-agora:invoke Coder1 "Write a login form as a React component" --expect --priority=high --cc=Reviewer1
```

Dispatches `{type:"task", from, ts, message}` to Coder1 with expect_result=true + priority=high envelope metadata. Reviewer1 receives a `delivered_as='cc'` copy and has no reply obligation — observation only.
