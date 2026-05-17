---
description: Broadcast a task or closing announcement to all registered cc-agora instances — auto-fills payload, separates envelope flags like priority and conversation_id.
argument-hint: "<message>" [--closing --priority --conv --expect]
---

# /cc-agora:broadcast

Fan-out to all registered instances. spec §4.6.

## Arguments

- `"<message>"` (required): Natural-language body. Wrap in quotes.
- `--closing` (optional): Announcement pattern. One-directional closing signal for end-of-meeting, system shutdown, etc. Do not use for regular fan-outs.
- `--priority=low|normal|high` (optional): Queue sorting metadata. Default `normal`. Actual sorting is only active when the receiver calls `agora.flush(sort="priority")`.
- `--conv=<id>` (optional): `conversation_id`. Use to attach to an existing thread.
- `--expect` (optional): `expect_result=true`. Signals worker personas that a reply is required.

## Behavior

### Payload auto-fill (§5.3)

Follows `scripts/payload.py::make_payload`:

- Without `--closing`: `type="task"` + `message=<arg>` + `from=<own instance_id>` + `ts=<ISO 8601 UTC>`.
- With `--closing`: `type="closing"` + `from` + `ts` (no message or reason — announcement only).

Own instance_id is obtained at registration time or from the self-entry in `agora.instances()` results.

### Envelope vs payload separation (§5.3 explicit rule)

`closing`, `priority`, `conversation_id`, `expect_result`, `reply_to`, `in_reply_to`, `deadline_ts` are passed directly as tool arguments — **not** embedded inside the payload object.

### MCP call

```
agora.broadcast(
  payload=<payload above>,
  closing=<--closing bool>,
  priority=<--priority or "normal">,
  conversation_id=<--conv or None>,
  expect_result=<--expect bool>,
)
```

Print the response directly to the user. `inbox_full` errors are reported with the §5.6 standard message.

## Examples

```
/cc-agora:broadcast "Code review meeting starts at 18:00 today." --priority=high
```

Delivers `{type:"task", from, ts, message}` payload to all registered workers with a priority=high envelope.

```
/cc-agora:broadcast "Session ending — next meeting is tomorrow." --closing
```

Delivers a `type="closing"` announcement to all immediately, closing any associated conversations.
