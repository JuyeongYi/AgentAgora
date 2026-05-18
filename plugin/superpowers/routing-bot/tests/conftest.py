"""pytest가 routing_bot.py를 찾을 수 있도록 sys.path에 부모 디렉토리를 추가한다."""
import sys
from pathlib import Path

# plugin/superpowers/routing-bot/ 을 Python 경로에 추가
_BOT_DIR = Path(__file__).parent.parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))
