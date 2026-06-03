#!/usr/bin/env bash
# AgentAgora server launcher. Run: ./run-server.sh   (Ctrl+C to stop)
cd "$(dirname "$0")"
if command -v agent-agora >/dev/null 2>&1; then
  exec agent-agora --dir "." --port {{PORT}} --no-tls {{BIND_OPT}}
else
  exec python3 -m agent_agora --dir "." --port {{PORT}} --no-tls {{BIND_OPT}}
fi
