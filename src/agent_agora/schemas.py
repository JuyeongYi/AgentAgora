"""v4 Schema Registry — runtime-mutable JSON Schema catalog (bots design)."""
from __future__ import annotations

import copy
import datetime
import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
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
        self._refs: dict[str, set[str]] = {}      # name -> holder ids (ref-counted)
        self._permanent: set[str] = set()         # 해제 불가 스키마 이름
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
                if existing.body != body:
                    raise AgoraError("schema_immutable", name=name)
                # same body — idempotent. ref-counted 스키마면 holder 추가.
                if registered_by is not None and name not in self._permanent:
                    self._refs.setdefault(name, set()).add(registered_by)
                return existing
            validator = Draft202012Validator(body)
            entry = SchemaEntry(
                name=name, body=body, kind=kind, purpose=purpose,
                registered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                registered_by=registered_by,
            )
            self._entries[name] = entry
            self._validators[name] = validator
            if registered_by is None:
                self._permanent.add(name)
            else:
                self._refs[name] = {registered_by}
            return entry

    def get(self, name: str) -> SchemaEntry | None:
        with self._lock:
            return self._entries.get(name)

    def validator(self, name: str) -> Draft202012Validator | None:
        with self._lock:
            return self._validators.get(name)

    def list_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": e.name, "kind": e.kind, "purpose": e.purpose,
                    "registered_at": e.registered_at, "registered_by": e.registered_by,
                }
                for e in self._entries.values()
            ]

    def list_all(self) -> list[SchemaEntry]:
        with self._lock:
            return list(self._entries.values())

    def refs_of(self, name: str) -> set[str]:
        """name의 현재 ref holder 집합 (조회용). permanent/미존재면 빈 집합."""
        with self._lock:
            return set(self._refs.get(name, set()))

    def acquire_ref(self, name: str, holder: str) -> None:
        """구독자 ref 획득. name이 미존재거나 permanent면 no-op."""
        with self._lock:
            if name not in self._entries or name in self._permanent:
                return
            self._refs.setdefault(name, set()).add(holder)

    def release_holder(self, holder: str) -> list[str]:
        """holder의 모든 ref를 해제한다. refset이 빈 non-permanent 스키마를
        등록 해제하고, 해제된 스키마 이름 리스트를 반환한다."""
        released: list[str] = []
        with self._lock:
            for name in list(self._refs.keys()):
                refs = self._refs[name]
                refs.discard(holder)
                if not refs:
                    self._entries.pop(name, None)
                    self._validators.pop(name, None)
                    self._refs.pop(name, None)
                    released.append(name)
        return released


SCHEMA_CONFLICT_NAME = "schema_conflict"
SCHEMA_CONFLICT_BODY: dict[str, Any] = {
    "type": "object",
    "required": ["msgtype", "schema_name", "reason", "ts"],
    "properties": {
        "msgtype": {"type": "string", "const": "schema_conflict"},
        "schema_name": {"type": "string"},
        "reason": {"type": "string"},
        "attempted_by": {"type": "string"},
        "ts": {"type": "string", "format": "date-time"},
    },
    "additionalProperties": False,
}

BUNDLED_DEFAULT_SCHEMAS = Path(__file__).with_name("default_schemas.jsonl")


def parse_schema_lines(text: str) -> list[dict[str, Any]]:
    """jsonl 텍스트를 {name, kind, purpose, body} dict 리스트로 파싱. 빈 줄 무시."""
    out: list[dict[str, Any]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"schemas.jsonl line {lineno}: invalid JSON ({e})") from e
        for key in ("name", "kind", "purpose", "body"):
            if key not in obj:
                raise ValueError(f"schemas.jsonl line {lineno}: missing '{key}'")
        out.append(obj)
    return out


def ensure_schemas_file(target: Path) -> Path:
    """target이 없으면 repo 동봉 default_schemas.jsonl을 복사한다 (결정 21).
    이미 있으면 손대지 않는다 (사용자 편집 보존)."""
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUNDLED_DEFAULT_SCHEMAS, target)
    return target


def load_schemas_into(registry: SchemaRegistry, path: Path) -> int:
    """path의 jsonl을 registry에 등록한다. 등록된 schema 개수를 반환."""
    parsed = parse_schema_lines(path.read_text("utf-8"))
    for p in parsed:
        registry.register(p["name"], p["body"], kind=p["kind"], purpose=p["purpose"])
    return len(parsed)
