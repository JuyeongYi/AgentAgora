"""Payload standard for cc-agora slashes (spec §5.3).

Envelope arguments (``in_reply_to``, ``closing``, ``conversation_id``, ``cc``,
``priority``, ``deadline_ts``, ``reply_to``) are passed to the MCP tool call as
*server metadata*, NOT inside the payload — keep this module focused on the
free-form payload body only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

PayloadType = Literal["task", "reply", "closing", "ack"]

_ALLOWED_TYPES: tuple[PayloadType, ...] = ("task", "reply", "closing", "ack")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_payload(
    type: PayloadType,
    from_: str,
    *,
    message: str | None = None,
    reason: str | None = None,
    ack_for: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """Build a payload dict matching spec §5.3.

    Per-type field rules:

    * ``task``    — requires ``message``; ``reason``/``ack_for`` rejected.
    * ``reply``   — requires ``message``; ``reason``/``ack_for`` rejected.
    * ``closing`` — ``reason`` allowed, ``message``/``ack_for`` rejected.
    * ``ack``     — requires ``ack_for``; ``message``/``reason`` rejected.
    """
    if type not in _ALLOWED_TYPES:
        raise ValueError(f"unknown payload type: {type!r} (allowed: {_ALLOWED_TYPES})")
    if not from_:
        raise ValueError("'from_' is required")

    payload: dict[str, Any] = {
        "type": type,
        "from": from_,
        "ts": ts if ts is not None else _now_iso(),
    }

    if type in ("task", "reply"):
        if message is None:
            raise ValueError(f"payload type={type!r} requires 'message'")
        if reason is not None or ack_for is not None:
            raise ValueError(f"payload type={type!r} rejects 'reason'/'ack_for'")
        payload["message"] = message
    elif type == "closing":
        if message is not None or ack_for is not None:
            raise ValueError("payload type='closing' rejects 'message'/'ack_for'")
        if reason is not None:
            payload["reason"] = reason
    elif type == "ack":
        if ack_for is None:
            raise ValueError("payload type='ack' requires 'ack_for'")
        if message is not None or reason is not None:
            raise ValueError("payload type='ack' rejects 'message'/'reason'")
        payload["ack_for"] = ack_for

    return payload
