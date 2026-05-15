"""v4 Schema Registry — runtime-mutable JSON Schema catalog (bots design)."""
from __future__ import annotations

import copy
import datetime
import threading
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from agent_agora.errors import AgoraError

SchemaKind = Literal["conversation", "bot-task"]


@dataclass(frozen=True)
class SchemaEntry:
    name: str
    body: dict[str, Any]
    kind: SchemaKind
    purpose: str
    registered_at: str
    registered_by: str | None = None


def _has_msgtype_property(body: Any) -> bool:
    props = body.get("properties") if isinstance(body, dict) else None
    return isinstance(props, dict) and "msgtype" in props


class SchemaRegistry:
    """name -> SchemaEntry. Thread-safe. Compiled validators cached per schema."""

    def __init__(self) -> None:
        self._entries: dict[str, SchemaEntry] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        body: dict[str, Any],
        kind: SchemaKind,
        purpose: str,
        registered_by: str | None = None,
    ) -> SchemaEntry:
        """결정 20: body에 msgtype property 필수. body는 유효한 JSON Schema여야 한다.
        동일 이름 + 다른 body → schema_immutable. 동일 이름 + 동일 body → idempotent.

        body는 등록 시 deep-copy해 격리한다 — caller가 이후 dict를 변형해도
        registry의 불변성 계약이 깨지지 않는다."""
        if not _has_msgtype_property(body):
            raise AgoraError("schema_missing_msgtype", name=name)
        body = copy.deepcopy(body)
        try:
            Draft202012Validator.check_schema(body)
        except SchemaError as e:
            raise AgoraError(
                "schema_violation",
                detail=f"schema '{name}' body가 유효한 JSON Schema가 아닙니다: {e.message}",
            ) from e
        with self._lock:
            existing = self._entries.get(name)
            if existing is not None:
                if existing.body == body:
                    return existing
                raise AgoraError("schema_immutable", name=name)
            validator = Draft202012Validator(body)
            entry = SchemaEntry(
                name=name, body=body, kind=kind, purpose=purpose,
                registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                registered_by=registered_by,
            )
            self._entries[name] = entry
            self._validators[name] = validator
            return entry

    def get(self, name: str) -> SchemaEntry | None:
        with self._lock:
            return self._entries.get(name)

    def validator(self, name: str) -> Draft202012Validator | None:
        with self._lock:
            return self._validators.get(name)
