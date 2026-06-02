"""대시보드 서브패키지 — HTTP 라우트·SSE 이벤트·인증·헬스 + 정적 에셋.

평면 dashboard_routes/events/auth/health에서 이전. 데이터 파일(dashboard.html,
dashboard_static/)도 이 패키지에 동거 — routes.py가 Path(__file__).with_name으로
로드한다. 외부는 이 패키지 표면을 통해 import한다 (private 심볼은 .routes 등
서브모듈에서 직접 import)."""
from agent_agora.dashboard.auth import DashboardAuthMiddleware, parse_tokens
from agent_agora.dashboard.events import EventBroker
from agent_agora.dashboard.health import HealthCollector
from agent_agora.dashboard.routes import (
    DASHBOARD_PROTECTED_PATHS,
    DASHBOARD_QUERY_PARAM_PATHS,
    build_dashboard_data,
    register,
)

__all__ = [
    "DashboardAuthMiddleware",
    "parse_tokens",
    "EventBroker",
    "HealthCollector",
    "register",
    "build_dashboard_data",
    "DASHBOARD_PROTECTED_PATHS",
    "DASHBOARD_QUERY_PARAM_PATHS",
]
