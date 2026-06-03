@echo off
REM Apply the review-gated comm matrix (coder cannot dispatch to writer; reviewer gate).
REM Broker must run with AGORA_ADMIN_TOKEN=test-admin-token (start-broker.bat).
setlocal
set AGORA_ADMIN_TOKEN=test-admin-token
"%~dp0../.venv/Scripts/python.exe" "%~dp0../plugin/cc-agora-ops/scripts/comm_matrix.py" "%~dp0../plugin/cc-agora-ops/presets/review-gated.csv"
