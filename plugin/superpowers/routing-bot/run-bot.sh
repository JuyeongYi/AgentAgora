#!/usr/bin/env bash
# superpowers 라우팅 봇 실행 (Unix/macOS).
# 사전: AgentAgora 서버가 http://127.0.0.1:8420 에 떠 있어야 한다.
#   python -m agent_agora --port 8420 --no-tls --no-timeout
# AGORA_URL 환경변수로 서버 주소를 덮어쓸 수 있다.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
exec "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/routing_bot.py" "$@"
