@echo off
REM superpowers 라우팅 봇 실행.
REM 사전: AgentAgora 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
REM   python -m agent_agora --port 8420 --no-tls --no-timeout
REM AGORA_URL 환경변수로 서버 주소를 덮어쓸 수 있다.
"%~dp0..\..\..\..\.venv\Scripts\python.exe" "%~dp0routing_bot.py" %*
