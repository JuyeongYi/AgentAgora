# src/agent_agora/schema.py
from __future__ import annotations

import json
from pathlib import Path

import jsonschema


class SchemaRegistry:
    _RESERVED_NAMES = frozenset({"schemas"})

    def __init__(self, schemas: dict[str, dict]) -> None:
        self._schemas = schemas

    @classmethod
    def load(cls, agora_dir: Path) -> SchemaRegistry:
        schemas_path = agora_dir / "schemas.json"
        if not schemas_path.exists():
            raise FileNotFoundError(f"schemas.json not found in {agora_dir}")

        schemas = json.loads(schemas_path.read_text(encoding="utf-8"))

        if not schemas:
            raise ValueError("schemas.json is empty")

        for name in schemas:
            if name in cls._RESERVED_NAMES:
                raise ValueError(f"Schema name '{name}' is reserved")

        return cls(schemas)

    def names(self) -> set[str]:
        return set(self._schemas.keys())

    def has(self, name: str) -> bool:
        return name in self._schemas

    def get_schema(self, name: str) -> dict:
        if name not in self._schemas:
            raise KeyError(f"Unknown schema: '{name}'")
        return self._schemas[name]

    def validate(self, schema_name: str, value: object) -> None:
        schema = self.get_schema(schema_name)
        try:
            jsonschema.validate(instance=value, schema=schema)
        except jsonschema.ValidationError as e:
            raise ValueError(str(e.message)) from e

    def validate_item(self, schema_name: str, item: object) -> None:
        schema = self.get_schema(schema_name)
        if schema.get("type") != "array":
            raise TypeError(f"Schema '{schema_name}' is not an array schema")
        items_schema = schema.get("items", {})
        try:
            jsonschema.validate(instance=item, schema=items_schema)
        except jsonschema.ValidationError as e:
            raise ValueError(str(e.message)) from e
