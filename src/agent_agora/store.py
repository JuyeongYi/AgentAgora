# src/agent_agora/store.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_agora.schema import SchemaRegistry


class AgoraStore:
    def __init__(self, agora_dir: Path, registry: SchemaRegistry) -> None:
        self._dir = agora_dir
        self._registry = registry
        self._data: dict[str, dict[str, Any]] = {name: {} for name in registry.names()}
        self._restore()

    def _restore(self) -> None:
        for name in self._registry.names():
            path = self._dir / f"{name}.json"
            if path.exists():
                self._data[name] = json.loads(path.read_text(encoding="utf-8"))

    def _persist(self, schema_name: str) -> None:
        path = self._dir / f"{schema_name}.json"
        path.write_text(json.dumps(self._data[schema_name], ensure_ascii=False, indent=2), encoding="utf-8")

    def _require_schema(self, schema_name: str) -> None:
        if not self._registry.has(schema_name):
            raise KeyError(f"Unknown schema: '{schema_name}'")

    def set(self, schema_name: str, key: str, value: Any) -> None:
        self._require_schema(schema_name)
        self._registry.validate(schema_name, value)
        self._data[schema_name][key] = value
        self._persist(schema_name)

    def get(self, schema_name: str, key: str) -> Any | None:
        self._require_schema(schema_name)
        return self._data[schema_name].get(key)

    def append(self, schema_name: str, key: str, item: Any) -> None:
        self._require_schema(schema_name)
        self._registry.validate_item(schema_name, item)
        bucket = self._data[schema_name]
        if key not in bucket:
            bucket[key] = [item]
        else:
            existing = bucket[key]
            if not isinstance(existing, list):
                raise TypeError(f"Value for '{schema_name}/{key}' is not a list")
            existing.append(item)
        self._persist(schema_name)

    def delete(self, schema_name: str, key: str) -> None:
        self._require_schema(schema_name)
        self._data[schema_name].pop(key, None)
        self._persist(schema_name)

    def list_schemas(self) -> set[str]:
        return self._registry.names()

    def list_keys(self, schema_name: str) -> list[str]:
        self._require_schema(schema_name)
        return list(self._data[schema_name].keys())
