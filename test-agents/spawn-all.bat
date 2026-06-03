@echo off
REM (Re)create the 7 worker directories from team-manifest.json. --force overwrites.
REM Worker name = folder basename, auto-used as --name and instance id at launch.
setlocal
"%~dp0../.venv/Scripts/python.exe" "%~dp0../plugin/cc-agora-ops/scripts/spawn_team.py" "%~dp0team-manifest.json" --dir "%~dp0." --force
