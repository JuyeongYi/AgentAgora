@echo off
REM review-gated 통신 매트릭스 적용 (coder↛writer — 리뷰어 게이트).
REM 브로커가 AGORA_ADMIN_TOKEN=test-admin-token 으로 떠 있어야 한다(start-broker.bat).
REM comm_matrix.py는 stdlib만 쓰므로 어떤 python으로도 동작한다.
setlocal
set AGORA_ADMIN_TOKEN=test-admin-token
"%~dp0..\.venv\Scripts\python.exe" "%~dp0..\plugin\cc-agora-ops\scripts\comm_matrix.py" "%~dp0..\plugin\cc-agora-ops\presets\review-gated.csv"
