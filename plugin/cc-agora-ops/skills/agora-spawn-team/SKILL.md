---
description: Spawn a whole cc-agora worker team from a manifest JSON — batch directory setup with optional Windows Terminal auto-launch.
argument-hint: <manifest.json> [--dir --launch=off/manual/auto --force --server-url]
disable-model-invocation: true
---

# /cc-agora-ops:agora-spawn-team

Spawn multiple cc-agora workers in one shot from a manifest file (spec §4.8).

## Arguments

- `<manifest.json>`: Path to the team manifest file. See
  `templates/team.json.example` for the schema — `{version:1, team:[{id, role, description}, ...]}`.
- `--dir=<path>` (optional): Common parent directory for all worker folders.
  Defaults to the same §4.2 cascade as `/cc-agora-ops:agora-spawn`.
- `--launch` (optional): Controls post-spawn window behaviour.
  - `off` (default) — no extra action.
  - `manual` — print `cd <id> && run.bat` start instructions per worker.
  - `auto` — open a Windows Terminal tab per worker via `wt.exe -w 0 new-tab`.
    Falls back to `manual` if `wt.exe` is absent.
- `--force` (optional): Pass `--force` through to each individual spawn.
- `--server-url=<url>` (optional): MCP server URL. Default `http://127.0.0.1:8420/mcp`.

## Behavior

1. The plugin root is `<repo>/plugin/cc-agora-ops/`. Run via the Bash tool:
   `python <plugin-root>/scripts/spawn_team.py $ARGUMENTS`.
2. Validates the manifest upfront (schema, id format, duplicate ids). On failure,
   abort with a per-entry stderr message — no directories are created.
3. On success, call `do_spawn` sequentially for each entry. Partial failure policy:
   if one entry fails, already-created directories are kept (no rollback) and the
   failing entry plus remaining skipped entries are reported.
4. Undefined roles per entry fall back to `cc-agora-general` with a warning; they
   do not abort the whole manifest.
5. On completion, print a summary: N succeeded / M failed; how to start each worker.

## Example

```
/cc-agora-ops:agora-spawn-team C:/AgoraTeam/team.json --dir=C:/AgoraTeam --launch=auto
```

All worker directories are created under `C:/AgoraTeam/<id>/`. If `wt.exe` is
installed, each worker opens automatically in a new Windows Terminal tab.
