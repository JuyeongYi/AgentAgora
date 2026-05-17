"""Console log/color helpers for the dispatcher — pure, no shared state."""
from __future__ import annotations

import hashlib
import json
from typing import Any

# (아래 5개는 dispatcher.py의 현재 정의를 그대로 옮긴 것 — 본문 변경 금지)


def _fmt_payload(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return repr(payload)


_COLOR_PALETTE = (
    "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[35m", "\033[36m",
    "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m",
)
_RESET = "\033[0m"


def _color_for(instance_id: str) -> str:
    h = hashlib.md5(instance_id.encode("utf-8")).digest()[0]
    return _COLOR_PALETTE[h % len(_COLOR_PALETTE)]


def _colored(instance_id: str) -> str:
    return f"{_color_for(instance_id)}{instance_id}{_RESET}"
