@echo off
REM AgentAgora broker - runs the uv-tool-installed 'agent-agora' (same install
REM version as the worker channel adapter 'agora-channel'). --no-tls --no-timeout
REM + AGORA_ADMIN_TOKEN. Data goes under .agentagora/ here.
setlocal
set AGORA_ADMIN_TOKEN=test-admin-token
cd /d "%~dp0"
agent-agora --port 8420 --no-tls --no-timeout --dir . %*
