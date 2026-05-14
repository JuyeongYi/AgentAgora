"""v3 envelope dataclass + validators. Replaces v1's implicit schema.py:_BUILTIN_SCHEMAS.commands."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal


_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}
_MAX_PAYLOAD_BYTES: int = 1_048_576


@dataclass(frozen=True)
class Envelope:
    id: str
    source: str
    target: str
    payload: Any
    created_at: str
    expect_result: bool
    reply_to: str | None
    cc: list[str] | None
    delivered_as: Literal["primary", "cc"]
    dispatch_kind: Literal["direct", "broadcast"]
    in_reply_to: str | None
    conversation_id: str
    closing: bool
    priority: Literal["low", "normal", "high"]
    deadline_ts: str | None
    wait_age_ms: int = 0


def validate_payload_size(payload: Any) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload_too_large: {len(encoded)} bytes > {_MAX_PAYLOAD_BYTES}")
    return encoded


def validate_priority(priority: str) -> int:
    if priority not in _PRIORITY_RANK:
        raise ValueError(f"invalid_priority: {priority!r} (must be one of {sorted(_PRIORITY_RANK)})")
    return _PRIORITY_RANK[priority]


def make_envelope(
    cmd_id: str,
    source: str,
    target: str,
    payload: Any,
    created_at: str,
    conversation_id: str,
    expect_result: bool = False,
    reply_to: str | None = None,
    cc: list[str] | None = None,
    delivered_as: Literal["primary", "cc"] = "primary",
    dispatch_kind: Literal["direct", "broadcast"] = "direct",
    in_reply_to: str | None = None,
    closing: bool = False,
    priority: Literal["low", "normal", "high"] = "normal",
    deadline_ts: str | None = None,
) -> Envelope:
    validate_priority(priority)
    return Envelope(
        id=cmd_id, source=source, target=target, payload=payload, created_at=created_at,
        expect_result=expect_result, reply_to=reply_to, cc=cc,
        delivered_as=delivered_as, dispatch_kind=dispatch_kind, in_reply_to=in_reply_to,
        conversation_id=conversation_id, closing=closing, priority=priority,
        deadline_ts=deadline_ts,
    )
