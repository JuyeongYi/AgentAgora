@echo off
REM AgentAgora server launcher.
REM Run by double-clicking, or from a terminal: run-server.bat
REM Stop the server with Ctrl+C in the spawned window.
setlocal
cd /d "%~dp0"
REM --dir points to the PARENT of .agentagora (the server appends ".agentagora").
REM --no-tls: plain HTTP for localhost testing.
where agent-agora >nul 2>nul
if %ERRORLEVEL%==0 (
    agent-agora --dir "%~dp0." --port 8420 --no-tls
) else (
    py -3.13 -m agent_agora --dir "%~dp0." --port 8420 --no-tls
)
echo.
echo Server stopped. Press any key to close.
pause >nul
endlocal
