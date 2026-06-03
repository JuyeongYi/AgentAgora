#!/usr/bin/env bash
# AgentAgora run-all (zellij): open the server and each worker in a zellij tab.
# Works inside OR outside a zellij session:
#   - outside: start a new zellij session (via a temp layout) and re-run this inside it.
#   - inside:  add tabs to the current session with `zellij action new-tab`.
# Worker = a subdirectory that contains .mcp.json; runs its run.sh.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
self="$here/run-all.sh"
root="$here"
port={{PORT}}

if ! command -v zellij >/dev/null 2>&1; then
  echo "zellij not found. Install zellij first." >&2
  exit 1
fi

# Outside a zellij session: start one (temp layout) and re-run this script inside it.
if [ -z "${ZELLIJ:-}" ]; then
  layout="$(mktemp --suffix .kdl 2>/dev/null || echo "${TMPDIR:-/tmp}/agora-run-all.kdl")"
  printf 'layout {\n    pane command="bash" {\n        args "%s"\n    }\n}\n' "$self" > "$layout"
  exec zellij --layout "$layout"
fi

# Inside a session: start server (only if this script manages it)
{{SERVER_BLOCK}}

# wait for the server port to open
for _ in $(seq 1 60); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then exec 3>&- 3<&-; break; fi
  sleep 0.5
done

# one tab per worker (subdir with .mcp.json)
for d in "$root"/*/; do
  [ -f "${d}.mcp.json" ] || continue
  [ -f "${d}run.sh" ] || continue
  zellij action new-tab --name "$(basename "$d")" --cwd "$d" -- bash run.sh
done
