#!/usr/bin/env bash
# superpowers runtime file installer (Unix/macOS).
#
# Copies comm-matrix.csv and delegation_request schema from the routing-bot
# directory into the AgentAgora deployment's .agentagora/ data directory.
# Run this once before starting the AgentAgora server for a superpowers deployment.
#
# Usage:
#   ./setup.sh --dir <deployment-folder>
#   ./setup.sh           # uses current directory as deployment folder
#
# Example:
#   cd /my-deployment
#   /path/to/AgentAgora/plugin/superpowers/setup.sh --dir .
set -euo pipefail

# Resolve the script's own directory — routing-bot/ is a sibling of this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$SCRIPT_DIR/routing-bot"
COMM_MATRIX="$BOT_DIR/comm-matrix.csv"
SCHEMA_FILE="$BOT_DIR/delegation_request.schema.jsonl"

# Parse arguments.
DEPLOY_DIR="$(pwd)"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            DEPLOY_DIR="$2"
            shift 2
            ;;
        --dir=*)
            DEPLOY_DIR="${1#--dir=}"
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# Resolve deployment directory to an absolute path.
DEPLOY_DIR="$(cd "$DEPLOY_DIR" && pwd)"
AGORA_DIR="$DEPLOY_DIR/.agentagora"
DEST_MATRIX="$AGORA_DIR/comm-matrix.csv"
DEST_SCHEMAS="$AGORA_DIR/schemas.jsonl"

# --- Validate source files exist ---
if [ ! -f "$COMM_MATRIX" ]; then
    echo "ERROR: source not found: $COMM_MATRIX" >&2
    exit 1
fi
if [ ! -f "$SCHEMA_FILE" ]; then
    echo "ERROR: source not found: $SCHEMA_FILE" >&2
    exit 1
fi

# --- Create .agentagora/ if absent ---
if [ ! -d "$AGORA_DIR" ]; then
    mkdir -p "$AGORA_DIR"
    echo "  [created] $AGORA_DIR"
fi

# --- Copy comm-matrix.csv ---
cp "$COMM_MATRIX" "$DEST_MATRIX"
echo "  [copied]  comm-matrix.csv -> $DEST_MATRIX"

# --- Append delegation_request schema (skip if already present) ---
if [ -f "$DEST_SCHEMAS" ] && grep -q '"name"[[:space:]]*:[[:space:]]*"delegation_request"' "$DEST_SCHEMAS"; then
    echo "  [skipped] delegation_request schema already in $DEST_SCHEMAS"
else
    # cat appends the schema line; touch ensures file exists first.
    touch "$DEST_SCHEMAS"
    # Append without a trailing blank line — strip trailing newline from source.
    printf '%s\n' "$(cat "$SCHEMA_FILE")" >> "$DEST_SCHEMAS"
    echo "  [appended] delegation_request schema -> $DEST_SCHEMAS"
fi

echo ""
echo "Runtime files installed. Next step:"
echo "  Start the routing bot before launching persona workers:"
echo "    $BOT_DIR/run-bot.sh"
