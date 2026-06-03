@echo off
REM Channel-mode worker launcher. agora-channel is a self-made channel not on
REM the official allowlist, so --dangerously-load-development-channels is needed.
REM Lower autoCompact threshold to 60 percent so the worker compacts early.
set CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60
REM Worker name = basename of this folder (matches the instance_id).
for %%I in ("%~dp0.") do set "AGORA_NAME=%%~nxI"
claude --name "%AGORA_NAME%" --dangerously-skip-permissions %* --dangerously-load-development-channels server:agora-channel
