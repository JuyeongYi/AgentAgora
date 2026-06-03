#!/usr/bin/env bash
# AgentAgora run-all: start the server, wait for its port, then launch each worker.
# Worker = a subdirectory that contains .mcp.json; runs its run.sh.
# Multiplexer: pass tmux|zellij|bg as arg1, or auto-detect (tmux > zellij > bg).
set -u
root="$(cd "$(dirname "$0")" && pwd)"
port=8420
mux="${1:-auto}"
if [ "$mux" = "auto" ]; then
  if command -v tmux >/dev/null 2>&1; then mux=tmux
  elif command -v zellij >/dev/null 2>&1; then mux=zellij
  else mux=bg; fi
fi

# 1) server
case "$mux" in
  tmux) tmux new-session -d -s agora -n server "agent-agora --dir '$root' --port $port --no-tls" ;;
  *)    nohup agent-agora --dir "$root" --port "$port" --no-tls >"$root/server.log" 2>&1 & ;;
esac

# 2) wait for the server port to open
for _ in $(seq 1 60); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then exec 3>&- 3<&-; break; fi
  sleep 0.5
done

# 3) launch each worker (subdir with .mcp.json)
for d in "$root"/*/; do
  [ -f "${d}.mcp.json" ] || continue
  [ -f "${d}run.sh" ] || continue
  name="$(basename "$d")"
  case "$mux" in
    tmux) tmux new-window -t agora -n "$name" "cd '$d' && ./run.sh" ;;
    *)    ( cd "$d" && nohup ./run.sh >"${d}worker.log" 2>&1 & ) ;;
  esac
done

[ "$mux" = tmux ] && exec tmux attach -t agora
