@echo off
REM 전체 기동 래퍼 — PowerShell 마스터 스크립트(start-all.ps1)를 호출한다.
REM 브로커 탭 → 헬스 대기 → comm-matrix 적용 → 워커 7개 탭.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
