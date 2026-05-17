@echo off
REM echo 봇에게 메시지 하나를 보내고 회신을 받는다.
REM 사전: 서버 + bot.py 가 모두 실행 중이어야 한다.
REM 사용: run-send.bat "보낼 메시지"
"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0send.py" %*
