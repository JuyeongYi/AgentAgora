@echo off
REM comm-matrix demo: seed comm-matrix.csv into a temp data dir, start the
REM server with the matrix loaded, run demo.py, then stop the server.
setlocal
set DEMO_DIR=%TEMP%\agora-comm-demo
set SCRIPT_DIR=%~dp0
set PYTHON=%SCRIPT_DIR%..\..\.venv\Scripts\python.exe

if exist "%DEMO_DIR%" rmdir /S /Q "%DEMO_DIR%"
mkdir "%DEMO_DIR%\.agentagora"
copy /Y "%SCRIPT_DIR%comm-matrix.csv" "%DEMO_DIR%\.agentagora\comm-matrix.csv" >nul

REM Start the server, capture its PID via PowerShell Start-Process -PassThru.
for /f %%P in ('powershell -NoProfile -Command "(Start-Process -FilePath \"%PYTHON%\" -ArgumentList '-m','agent_agora','--dir','%DEMO_DIR%','--port','8420','--no-tls','--no-timeout' -PassThru -WindowStyle Hidden).Id"') do set AGORA_PID=%%P

REM Wait for the server to be ready.
timeout /t 3 /nobreak >nul

REM Run the demo.
"%PYTHON%" "%SCRIPT_DIR%demo.py" %*
set DEMO_RC=%ERRORLEVEL%

REM Stop the server (PID-based -- reliable; /T kills child processes too).
taskkill /PID %AGORA_PID% /T /F >nul 2>&1

endlocal
exit /b %DEMO_RC%
