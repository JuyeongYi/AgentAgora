"""레지스트리 서브패키지 — 공통 베이스 + 워커(instance)·봇 레지스트리 (Plan E).

평면 registry.py·bot_registry.py에서 이전. 외부는 `from agent_agora.registry import ...`로
공개 표면에 접근한다(내부 모듈명 변경에도 안정)."""
from agent_agora.registry.core import (
    OPERATOR_PREFIX,
    InstanceInfo,
    InstanceRegistry,
    NotRegisteredError,
    _BidirectionalRegistry,
    is_operator,
    operator_id,
    strip_operator_prefix,
)
from agent_agora.registry.bot import BotInfo, BotMode, BotRegistry

__all__ = [
    "NotRegisteredError", "OPERATOR_PREFIX", "is_operator", "operator_id",
    "strip_operator_prefix", "InstanceInfo", "InstanceRegistry",
    "BotInfo", "BotMode", "BotRegistry", "_BidirectionalRegistry",
]
