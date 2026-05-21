"""v3 envelope dataclass + validators. Replaces v1's implicit schema.py:_BUILTIN_SCHEMAS.commands."""
from __future__ import annotations

import dataclasses
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
    delivered_as: Literal["primary", "cc", "subscribed"]
    dispatch_kind: Literal["direct", "broadcast"]
    in_reply_to: str | None
    conversation_id: str
    closing: bool
    priority: Literal["low", "normal", "high"]
    deadline_ts: str | None
    wait_age_ms: int = 0
    reply_only: bool = False


def validate_payload_size(payload: Any) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload_too_large: {len(encoded)} bytes > {_MAX_PAYLOAD_BYTES}")
    return encoded


def validate_priority(priority: str) -> int:
    if priority not in _PRIORITY_RANK:
        raise ValueError(f"invalid_priority: {priority!r} (must be one of {sorted(_PRIORITY_RANK)})")
    return _PRIORITY_RANK[priority]


def validate_deadline_ts(deadline_ts: str | None) -> None:
    """advisory ISO 8601 string. None passes. Bad format raises ValueError."""
    if deadline_ts is None:
        return
    try:
        import datetime as _dt
        _dt.datetime.fromisoformat(deadline_ts)
    except (TypeError, ValueError) as e:
        raise ValueError(f"invalid_deadline_ts: {deadline_ts!r} ({e})") from e


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
    delivered_as: Literal["primary", "cc", "subscribed"] = "primary",
    dispatch_kind: Literal["direct", "broadcast"] = "direct",
    in_reply_to: str | None = None,
    closing: bool = False,
    priority: Literal["low", "normal", "high"] = "normal",
    deadline_ts: str | None = None,
    reply_only: bool = False,
) -> Envelope:
    validate_priority(priority)
    validate_deadline_ts(deadline_ts)
    return Envelope(
        id=cmd_id, source=source, target=target, payload=payload, created_at=created_at,
        expect_result=expect_result, reply_to=reply_to, cc=cc,
        delivered_as=delivered_as, dispatch_kind=dispatch_kind, in_reply_to=in_reply_to,
        conversation_id=conversation_id, closing=closing, priority=priority,
        deadline_ts=deadline_ts, reply_only=reply_only,
    )


def envelope_to_dict(env: Envelope) -> dict[str, Any]:
    """Envelope를 직렬화 가능한 dict로 변환한다.
    모든 dataclass 필드를 자동으로 포함한다 — 새 필드 추가 시 수동 갱신 불필요."""
    return dataclasses.asdict(env)


def envelope_from_dict(data: dict[str, Any]) -> Envelope:
    """dict에서 Envelope를 복원한다. reply_only 누락 시 False로 기본값 처리."""
    return Envelope(
        id=data["id"],
        source=data["source"],
        target=data["target"],
        payload=data["payload"],
        created_at=data["created_at"],
        expect_result=data["expect_result"],
        reply_to=data.get("reply_to"),
        cc=data.get("cc"),
        delivered_as=data["delivered_as"],
        dispatch_kind=data["dispatch_kind"],
        in_reply_to=data.get("in_reply_to"),
        conversation_id=data["conversation_id"],
        closing=data["closing"],
        priority=data["priority"],
        deadline_ts=data.get("deadline_ts"),
        wait_age_ms=data.get("wait_age_ms", 0),
        reply_only=data.get("reply_only", False),
    )
