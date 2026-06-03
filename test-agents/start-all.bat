@echo off
REM Full bring-up wrapper -> PowerShell master script (start-all.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
