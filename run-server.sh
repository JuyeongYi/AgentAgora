#!/usr/bin/env bash
# AgentAgora server launcher (Unix).
#
# Usage: cd into your deployment folder, then run this script.
#   cd /path/to/deployment
#   /path/to/AgentAgora/run-server.sh
#
# It checks the current folder for AgentAgora deployment data (.agentagora/)
# and passes that folder to the server via --dir. Press Ctrl+C to stop.
set -euo pipefail

PORT=8420

# Deployment folder = the current working directory this script was run from.
DEPLOY_DIR="$(pwd)"
AGORA_DIR="$DEPLOY_DIR/.agentagora"

if [ ! -d "$AGORA_DIR" ]; then
    echo "No .agentagora/ in current folder: $DEPLOY_DIR" >&2
    echo "This is not an AgentAgora deployment folder. cd into a deployment" >&2
    echo "folder and retry, or run /cc-agora-ops:agora-setup to initialize it." >&2
    exit 1
fi

# Report deployment config files (the server falls back to defaults if missing).
for name in server-info.json schemas.jsonl comm-matrix.csv file-policy.json; do
    if [ -f "$AGORA_DIR/$name" ]; then
        echo "  [ok]      .agentagora/$name"
    else
        echo "  [missing] .agentagora/$name"
    fi
done

echo "Starting AgentAgora server -- dir: $DEPLOY_DIR  port: $PORT"

if command -v agent-agora >/dev/null 2>&1; then
    exec agent-agora --dir "$DEPLOY_DIR" --port "$PORT" --no-tls
else
    echo "agent-agora CLI not found -- falling back to 'python -m agent_agora'." >&2
    echo "(To install the server, see FOR_AGENT.md.)" >&2
    exec python -m agent_agora --dir "$DEPLOY_DIR" --port "$PORT" --no-tls
fi
