@echo off
REM team-manifest.json 으로 7개 워커 디렉토리를 (재)생성한다. --force로 덮어쓴다.
REM 머신을 옮겼거나 .mcp.json의 절대경로(X-Agora-Cwd)가 어긋났을 때 다시 돌린다.
setlocal
"%~dp0..\.venv\Scripts\python.exe" "%~dp0..\plugin\cc-agora-ops\scripts\spawn_team.py" "%~dp0team-manifest.json" --dir "%~dp0." --force
