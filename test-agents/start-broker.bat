@echo off
REM AgentAgora 브로커 — 채널 모드 테스트 하니스용.
REM --no-tls(로컬 HTTP) + --no-timeout(워커 무기한 대기) + AGORA_ADMIN_TOKEN
REM (comm-matrix 프리셋 적용용). 데이터(.agentagora/)는 이 폴더 하위에 생성된다.
setlocal
set AGORA_ADMIN_TOKEN=test-admin-token
cd /d "%~dp0"
"%~dp0..\.venv\Scripts\python.exe" -m agent_agora --port 8420 --no-tls --no-timeout --dir . %*
