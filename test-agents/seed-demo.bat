@echo off
REM Populate the dashboard with demo traffic (no real Claude workers needed).
REM Broker must be running (start-broker.bat). Then open http://127.0.0.1:8420/dashboard
setlocal
"%~dp0../.venv/Scripts/python.exe" "%~dp0seed-demo.py" %*
