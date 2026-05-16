@echo off
REM comm-matrix ACL demo.
REM Seeds comm-matrix.csv into a temp data dir, starts the server,
REM runs demo.py, then stops the server.

setlocal

set DEMO_DIR=%TEMP%\agora-comm-demo
set AGORA_DIR=%DEMO_DIR%\.agentagora

REM Create the data dir and plant the comm-matrix CSV
if not exist "%AGORA_DIR%" mkdir "%AGORA_DIR%"
copy /Y "%~dp0comm-matrix.csv" "%AGORA_DIR%\comm-matrix.csv" >nul

REM Start the server in the background
start /B "agora-server" "%~dp0..\..\.venv\Scripts\python.exe" -m agent_agora --dir "%DEMO_DIR%" --port 8420 --no-tls --no-timeout

REM Wait for server to be ready
timeout /T 3 /NOBREAK >nul

REM Run the demo
"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0demo.py" %*
set DEMO_EXIT=%ERRORLEVEL%

REM Stop the server
taskkill /FI "WINDOWTITLE eq agora-server" /F >nul 2>&1

endlocal
exit /B %DEMO_EXIT%
