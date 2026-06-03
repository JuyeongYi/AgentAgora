@echo off
REM Full bring-up wrapper -> PowerShell master (start-all.ps1). Forwards args (e.g. -c).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*
