@echo off
REM 테스트용 Agora echo 봇 실행.
REM 사전 조건: AgentAgora 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
REM   python -m agent_agora --port 8420 --no-tls --no-timeout
py -3.13 "%~dp0bot.py"
