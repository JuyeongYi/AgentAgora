@echo off
REM AgentAgora broker for the channel-mode test harness.
REM --no-tls (local HTTP) + --no-timeout (workers wait) + AGORA_ADMIN_TOKEN
REM (so comm-matrix presets can be applied). Data goes under .agentagora/ here.
setlocal
set AGORA_ADMIN_TOKEN=test-admin-token
cd /d "%~dp0"
"%~dp0../.venv/Scripts/python.exe" -m agent_agora --port 8420 --no-tls --no-timeout --dir . %*
