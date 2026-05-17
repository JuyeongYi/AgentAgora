---
description: Spawn one cc-agora worker — creates a thin CLAUDE.md, .mcp.json, run.bat, and .claude/settings.local.json that enables the worker's persona plugin.
argument-hint: <id> <role> "<description>" [--dir --force --server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-spawn

Set up one cc-agora channel-mode worker directory (spec §4.2).

## Arguments

- `<id>`: Worker instance_id — alphanumeric, hyphens, underscores; 1–32 chars.
- `<role>`: Role name; looked up in `config/roles.json`. Undefined roles are
  accepted with a warning and fall back to the `cc-agora-general` persona plugin.
- `"<description>"`: One-line description of the worker's responsibility. Wrap in
  quotes to preserve spaces.
- `--dir=<path>` (optional): Explicit parent directory for the worker folder.
- `--force` (optional): Overwrite managed files inside an existing `<id>/`.
- `--server-url=<url>` (optional): MCP server URL. Default `http://127.0.0.1:8420/mcp`.

## Behavior

1. The plugin root is `<repo>/plugin/cc-agora-ops/`. Run via the Bash tool:
   `python <plugin-root>/scripts/spawn.py $ARGUMENTS`. Build the absolute path to
   the script at call time.
2. The script looks up `config/roles.json` to determine the persona plugin name.
   Undefined roles fall back to `cc-agora-general` with a stderr warning.
3. Target directory cascade (spec §4.2 step 2): `--dir` → `AGORA_HOME` env var →
   if cwd is a worker directory (contains `.mcp.json`) use its parent → otherwise cwd
   (with a warning).
4. Four files are created inside `<id>/`:
   - `CLAUDE.md` — thin identity + persona/comm instructions (no persona body stamped).
   - `.mcp.json` — two-server config: HTTP AgentAgora + agora-channel stdio adapter.
   - `run.bat` — channel-mode launcher (`--dangerously-load-development-channels`).
   - `.claude/settings.local.json` — enables the worker's persona plugin from the
     local AgentAgora marketplace.
5. Registration is automatic — when the worker runs `run.bat` the `.mcp.json` headers
   trigger `auto_register` on the server. Do not call `agora.register` manually.
6. Forward stdout/stderr to the user as-is.

## Example

```
/cc-agora-ops:agora-spawn Coder1 coder "Front-end React component and hook design."
```

Creates `<parent>/Coder1/` with all four files. The worker starts in channel mode
by running `run.bat`, which auto-registers it via the `.mcp.json` headers.
