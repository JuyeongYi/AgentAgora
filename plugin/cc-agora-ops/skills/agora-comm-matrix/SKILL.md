---
description: Manage the AgentAgora communication matrix via the token-gated /admin/comm-matrix endpoint — push a new CSV or read the current matrix.
argument-hint: [<csv-path>] [--server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-comm-matrix

Manage the communication matrix on a running AgentAgora server through the
operator-only `/admin/comm-matrix` endpoint.

## Arguments

- `<csv-path>` (optional) — a comm-matrix CSV file to POST (replaces the
  in-memory matrix without a restart). Omit it to GET the current matrix.
- `--server-url` (optional) — server base URL. Default `http://127.0.0.1:8420`.

## Behavior

1. The server must run with the `AGORA_ADMIN_TOKEN` environment variable set.
   Export the same token in this session before invoking.
2. Run `python <plugin-root>/scripts/comm_matrix.py $ARGUMENTS` via the Bash tool.
3. The script sends `Authorization: Bearer <token>`. With a CSV path it POSTs;
   without one it GETs.
4. Print the server response. On 401 (token mismatch) or 400 (bad CSV) the
   script reports a Korean diagnostic.
