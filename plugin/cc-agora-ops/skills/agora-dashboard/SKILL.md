---
description: Open the AgentAgora team dashboard in a browser — a live view of instances, bots, conversations, and the comm-matrix graph.
argument-hint: [--server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-dashboard

Open the AgentAgora team-status dashboard in the operator's default browser.

## Arguments

- `--server-url` (optional) — server base URL. Default `http://127.0.0.1:8420`.

## Behavior

1. Resolve the dashboard URL: `<server-url>/dashboard` (default
   `http://127.0.0.1:8420/dashboard`).
2. Open it in the default browser via the Bash tool, picking the platform's
   command:
   - Windows: `start "" "<url>"`
   - macOS: `open "<url>"`
   - Linux: `xdg-open "<url>"`
3. Always also print the URL plainly, so the operator can open it manually if
   the browser launch fails.

The dashboard is served by the AgentAgora server (the server must be running).
It polls live every few seconds — no refresh needed. It is read-only; to change
the comm-matrix use `/cc-agora-ops:agora-comm-matrix`.
