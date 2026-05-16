@echo off
REM 예제 echo 봇 실행. 저장소 .venv 의 python 으로 echo_bot.py 를 띄운다.
REM 사전: AgentAgora 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
REM   python -m agent_agora --port 8420 --no-tls --no-timeout
"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0echo_bot.py" %*
