#!/usr/bin/env bash
# AgentAgora run-all (zellij): open the server and each worker in a new zellij tab.
# Run this INSIDE a zellij session (it uses `zellij action new-tab`).
# Worker = a subdirectory that contains .mcp.json; runs its run.sh.
set -u
root="$(cd "$(dirname "$0")" && pwd)"
port={{PORT}}

if ! command -v zellij >/dev/null 2>&1; then
  echo "zellij not found. Install zellij, then run this inside a zellij session." >&2
  exit 1
fi
if [ -z "${ZELLIJ:-}" ]; then
  echo "Run this inside a zellij session: start 'zellij' first, then ./run-all.sh" >&2
  exit 1
fi

# 1) server tab
zellij action new-tab --name server --cwd "$root" -- agent-agora --dir "$root" --port "$port" --no-tls {{BIND_OPT}}

# 2) wait for the server port to open
for _ in $(seq 1 60); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then exec 3>&- 3<&-; break; fi
  sleep 0.5
done

# 3) one tab per worker (subdir with .mcp.json)
for d in "$root"/*/; do
  [ -f "${d}.mcp.json" ] || continue
  [ -f "${d}run.sh" ] || continue
  name="$(basename "$d")"
  zellij action new-tab --name "$name" --cwd "$d" -- bash run.sh
done
