---
description: Co-author a custom worker persona with the operator and scaffold the worker directory — for roles not covered by the seven preset persona plugins.
argument-hint: [<id>] [--dir --force --server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-design-worker

Set up one channel-mode AgentAgora worker with a **custom persona** authored
together with the operator. Unlike `/cc-agora-ops:agora-spawn` — which enables one
of the seven preset persona plugins — this skill builds a persona from a short
dialogue and stamps it into the worker directory's `.claude/CLAUDE.md`.

## Arguments

- `<id>` (optional) — worker instance_id (alphanumeric, hyphens, underscores;
  1–32 chars). If omitted, ask for it as the first dialogue question.
- `--dir=<path>` (optional) — explicit parent directory for the worker folder.
- `--force` (optional) — overwrite managed files inside an existing `<id>/`.
- `--server-url=<url>` (optional) — MCP server URL. Default
  `http://127.0.0.1:8420/mcp`.

## Behavior

### 1. Persona dialogue

Ask the operator the following **one question at a time** — do not batch them:

1. **Worker id** — only if `<id>` was not passed as an argument.
2. **Mission** — one or two sentences: what does this worker turn its inputs
   into? Its core responsibility.
3. **Role label** — a short single-word role for the `.mcp.json` headers
   (e.g. `db-migrator`).
4. **Working style & role-specific knowledge** — concrete operating rules for
   this role.
5. **Handoff specifics** — does this worker forward out-of-domain work? Is there
   a default delegate?

### 2. Compose the persona

Build the persona body with this exact structure. The **Mission** and
**Role-specific knowledge** sections come from the dialogue; the **Response
conventions** and **Finding other members** sections are fixed boilerplate —
stamp them verbatim:

```markdown
# <role label> persona

## Mission

<dialogue answer 2, with the handoff answer from 5 folded in>

## Response conventions

### Forward convention

You are not obligated to reply only to the original sender. When a task is better
suited to another member, use `/invoke <other> "<task>"` to forward it. Sending
the originator a one-line ack ("delegated to X") is recommended — not mandatory.

### Flush entry convention

When woken by a channel notification (`<channel source="agora-channel">`), drain
your inbox with `agora.flush`. See the `agora-protocol` skill for full
channel-mode messaging rules.

### cc message convention

Do not reply to messages with `envelope.delivered_as='cc'`. Treat them as
observer signals — absorb as context only.

### Payload standard

All outgoing payloads use the `{type, from, ts, message?}` format. The `type`
enum has four values: `task | reply | closing | ack`. Use `type=reply` for task
responses, `type=ack` for delegation notices, `type=closing` for finalization.

## Role-specific knowledge

<dialogue answer 4, as a bullet list>

## Finding other members

Discover currently registered workers dynamically via `agora.instances` or
`agora.find`. Do not hard-code instance mappings in the persona.
```

### 3. Confirm

Show the operator the fully composed persona and ask for confirmation. Revise on
request. Do not scaffold until the operator approves.

### 4. Scaffold the worker directory

1. Write the approved persona body to a temporary file in the current working
   directory, e.g. `.agora-design-worker-persona.tmp`.
2. The plugin root is `<repo>/plugin/cc-agora-ops/`. Run via the Bash tool:
   `python <plugin-root>/scripts/spawn.py <id> <role-label> "<responsibility>" --persona-file <tmpfile>` plus any of `--dir`, `--force`, `--server-url` the
   operator passed. `<responsibility>` is a single sentence drawn from the
   Mission. Custom mode creates `CLAUDE.md`, `.claude/CLAUDE.md` (the persona),
   `.mcp.json`, and `.claude/settings.local.json` (enables `cc-agora`); it writes
   no run script.
3. Delete the temporary file.
4. Invoke the `agora-run-script` skill with the worker directory as its `<dir>`
   argument to write the channel-mode launch script (`run.ps1`/`run.sh`).

### 5. Report

Forward `spawn.py` stdout/stderr to the operator as-is, then tell them the worker
starts by running the launch script from inside the worker directory.

## Example

```
/cc-agora-ops:agora-design-worker Db1
```

Walks the operator through the persona dialogue, then creates `<parent>/Db1/`
with a custom persona in `.claude/CLAUDE.md` and a channel-mode launch script.
