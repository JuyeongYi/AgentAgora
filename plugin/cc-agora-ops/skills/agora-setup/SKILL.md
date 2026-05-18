---
description: Bootstrap a whole AgentAgora deployment with the operator — server launch script, message schemas, communication and file permissions, and the worker roster.
argument-hint: [--dir]
disable-model-invocation: true
---

# /cc-agora-ops:agora-setup

Walk the operator through standing up a complete AgentAgora deployment in one
pass: server launch configuration, message schemas, communication and file
permissions, and the creation of every planned worker. End-to-end — for each
planned agent this skill runs the `agora-design-worker` flow.

## Arguments

- `--dir=<path>` (optional) — deployment root. Default: the current working
  directory (`$CWD`). The `.agentagora/` data directory, the `run-cc-agora`
  launch script, and the worker directories are all created under it.

## Behavior

Run these steps in order. Ask questions one at a time.

### 1. Server configuration

Ask the operator: server port (default `8420`); TLS on or off; wait timeout in
milliseconds or no timeout; whether to restore undelivered messages on restart
(`--restore`); whether to set an `AGORA_ADMIN_TOKEN`.

Write the server launch script to the deployment root, matching the host OS —
`run-cc-agora.ps1` on Windows, `run-cc-agora.sh` on Unix. It launches the
AgentAgora server with the chosen flags. It is server-only — it does not launch
workers.

Windows `run-cc-agora.ps1`:

```powershell
# AgentAgora server launcher — run this BEFORE starting any worker. Ctrl+C to stop.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:AGORA_ADMIN_TOKEN = "<token>"   # include this line only if a token was chosen
if (Get-Command agent-agora -ErrorAction SilentlyContinue) {
    agent-agora --dir "." --port <port> <flags>
} else {
    python -m agent_agora --dir "." --port <port> <flags>
}
```

Unix `run-cc-agora.sh`:

```bash
#!/usr/bin/env bash
# AgentAgora server launcher — run this BEFORE starting any worker. Ctrl+C to stop.
set -e
cd "$(dirname "$0")"
export AGORA_ADMIN_TOKEN="<token>"   # include this line only if a token was chosen
if command -v agent-agora >/dev/null 2>&1; then
    exec agent-agora --dir "." --port <port> <flags>
else
    exec python -m agent_agora --dir "." --port <port> <flags>
fi
```

`<flags>` is the chosen combination of `--no-tls`, `--no-timeout` or
`--default-wait-timeout-ms <ms>`, and `--restore`.

Then record the chosen server configuration to
`<dir>/.agentagora/server-info.json` (create the `.agentagora/` directory if it
does not exist yet). This file is an operator/worker reference — the server does
not read it. It exists so later setup steps and other sessions can look up the
connection details without re-deriving them from the launch script. Write these
keys:

```json
{
  "host": "127.0.0.1",
  "port": <chosen port>,
  "tls": <true if TLS on, false if --no-tls>,
  "url": "<http if --no-tls, else https>://127.0.0.1:<port>/mcp",
  "wait_timeout_ms": <chosen ms, or null when --no-timeout>,
  "restore": <true if --restore was chosen, else false>,
  "admin_token_required": <true if an AGORA_ADMIN_TOKEN was set, else false>
}
```

`url` is the exact value workers put in their `.mcp.json`. Never write the admin
token value itself — only the boolean `admin_token_required`.

### 2. Agent roster

Ask the operator for the list of agents to create — each as an `id` plus a
one-line responsibility. This roster is the input to steps 3–5.

### 3. Schemas

Ask the operator how deep to go on message schemas, and act on the choice:

- **Lightweight** — ask only for each schema's name, purpose, and main fields;
  generate a minimal JSON Schema body.
- **Full** — design each message type's field types, required flags, and
  constraints in detail.
- **File only** — note the built-in schemas (`schema_conflict`, `file_share`)
  and prepare an empty schema file; custom schemas are registered at runtime by
  workers and bots.

Write the result to `<dir>/.agentagora/schemas.jsonl` — one JSON object per
line, each with the four keys the server requires: `name`, `kind`, `purpose`,
`body` (the `body` is the JSON Schema). `kind` is typically `conversation`.

### 4. Permissions

Using the roster from step 2:

- **Communication matrix** — pick a topology with the operator (hub-and-spoke /
  all-allow / custom) and write an `(N+1)×(N+1)` CSV with a `.*` catch-all row
  and column to `<dir>/.agentagora/comm-matrix.csv`. Cells are non-negative
  integers — `0` forbids the edge, `>0` allows it. Follow the
  `agora-make-comm-matrix` skill's CSV rules.
- **File policy** — for each agent, ask for read and write gitignore-pattern
  globs, and write `<dir>/.agentagora/file-policy.json` as
  `{"<id>": {"r": [...], "w": [...]}}`. A missing `r` means read-all; a missing
  `w` means write-none.

### 5. Create agents

For each roster entry, run the `agora-design-worker` flow — pass the `id`, use
the one-line responsibility, then conduct the persona dialogue (mission, role
label, working style, handoff) and scaffold the worker directory under `<dir>`.

## Closing

Tell the operator the launch order: first run `run-cc-agora` to start the server
and confirm it is up, then run each worker's `run.ps1`/`run.sh` from inside its
directory. The server must be up before any worker connects — a worker registers
with the server when its MCP client connects at session start, and Claude Code
connects MCP servers before it runs any `SessionStart` hook, so a hook cannot
bring the server up in time. A standalone launch script run first is the only
reliable ordering.

## Output

| Artifact | Location |
| --- | --- |
| `run-cc-agora.ps1` / `run-cc-agora.sh` | `<dir>/` |
| `server-info.json`, `schemas.jsonl`, `comm-matrix.csv`, `file-policy.json` | `<dir>/.agentagora/` |
| Worker directories | `<dir>/<id>/` |
