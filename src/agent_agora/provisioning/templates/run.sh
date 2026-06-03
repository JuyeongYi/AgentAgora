#!/usr/bin/env bash
# Channel-mode worker launcher. agora-channel is a self-made channel not on
# the official allowlist, so --dangerously-load-development-channels is needed.
# Lower autoCompact threshold to 60 percent so the worker compacts early.
export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60
# Worker name = basename of this folder (matches the instance_id).
AGORA_NAME="$(basename "$(cd "$(dirname "$0")" && pwd)")"
exec claude --name "$AGORA_NAME" --dangerously-skip-permissions "$@" --dangerously-load-development-channels server:agora-channel
