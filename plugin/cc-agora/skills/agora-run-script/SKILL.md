---
description: Generate the OS-appropriate channel-mode run script for a worker directory — run.ps1 on Windows, run.sh on Unix.
argument-hint: [<dir>]
disable-model-invocation: true
---

# /cc-agora:agora-run-script

Write the channel-mode launch script for an AgentAgora worker directory. A worker
is started by opening an interactive Claude Code session with the worker
directory as the working directory; the launch script does exactly that. Because
the script is run from inside the worker directory, the working directory is
correct by construction and the worker picks up its own `.mcp.json`, `CLAUDE.md`,
and `.claude/`.

## Arguments

- `<dir>` (optional) — directory to write the script into. Default: the current
  working directory.

## Behavior

1. Determine the host OS.

2. Write the run script into `<dir>`, UTF-8 with LF newlines:

   - **Windows** → `<dir>/run.ps1`:

     ```
     # AgentAgora channel-mode worker launcher. Run from inside this directory.
     claude --dangerously-load-development-channels server:agora-channel @args
     ```

   - **Unix (macOS/Linux)** → `<dir>/run.sh`:

     ```
     #!/usr/bin/env bash
     # AgentAgora channel-mode worker launcher. Run from inside this directory.
     claude --dangerously-load-development-channels server:agora-channel "$@"
     ```

3. On Unix, tell the operator to mark it executable: `chmod +x <dir>/run.sh`.

4. Report the written path. The worker is started by running this script from
   inside `<dir>` — `cd <dir>` then `./run.ps1` (Windows; if PowerShell execution
   policy blocks it, `powershell -ExecutionPolicy Bypass -File .\run.ps1`) or
   `./run.sh` (Unix).

## Notes

- `agora-channel` is a self-made development channel not on the official
  allowlist, so the `--dangerously-load-development-channels` flag is required.
- This skill writes only the launch script. The worker directory itself
  (`.mcp.json`, `CLAUDE.md`, `.claude/`) is created by `/cc-agora-ops:agora-spawn`
  or `/cc-agora-ops:agora-design-worker`.
