# tests/test_schema.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_agora.schema import SchemaRegistry


class TestSchemaRegistryLoad:
    def test_load_from_valid_dir(self, agora_dir_with_schemas: Path) -> None:
        reg = SchemaRegistry.load(agora_dir_with_schemas)
        assert {"finding", "status"}.issubset(reg.names())

    def test_missing_schemas_json(self, agora_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            SchemaRegistry.load(agora_dir)

    def test_empty_schemas_json(self, agora_dir: Path) -> None:
        (agora_dir / "schemas.json").write_text("{}")
        with pytest.raises(ValueError, match="empty"):
            SchemaRegistry.load(agora_dir)

    def test_reserved_name_schemas(self, agora_dir: Path) -> None:
        schemas = {"schemas": {"type": "string"}}
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        with pytest.raises(ValueError, match="reserved"):
            SchemaRegistry.load(agora_dir)


class TestSchemaRegistryValidation:
    def test_validate_valid_value(self, agora_dir_with_schemas: Path) -> None:
        reg = SchemaRegistry.load(agora_dir_with_schemas)
        reg.validate("finding", {"file": "a.py", "line": 1, "severity": "high"})

    def test_validate_invalid_value(self, agora_dir_with_schemas: Path) -> None:
        reg = SchemaRegistry.load(agora_dir_with_schemas)
        with pytest.raises(ValueError):
            reg.validate("finding", {"file": "a.py"})

    def test_validate_unknown_schema(self, agora_dir_with_schemas: Path) -> None:
        reg = SchemaRegistry.load(agora_dir_with_schemas)
        with pytest.raises(KeyError):
            reg.validate("nonexistent", "value")

    def test_has_schema(self, agora_dir_with_schemas: Path) -> None:
        reg = SchemaRegistry.load(agora_dir_with_schemas)
        assert reg.has("finding") is True
        assert reg.has("nonexistent") is False

    def test_validate_items_for_array_schema(self, agora_dir: Path) -> None:
        schemas = {
            "findings_list": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"file": {"type": "string"}},
                    "required": ["file"],
                },
            }
        }
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        reg.validate_item("findings_list", {"file": "a.py"})

    def test_validate_item_non_array_schema(self, agora_dir_with_schemas: Path) -> None:
        reg = SchemaRegistry.load(agora_dir_with_schemas)
        with pytest.raises(TypeError, match="not an array"):
            reg.validate_item("status", "value")


def test_builtin_schemas_auto_registered(agora_dir_with_schemas):
    from agent_agora.schema import SchemaRegistry
    registry = SchemaRegistry.load(agora_dir_with_schemas)
    assert "instances" in registry.names()
    assert "commands" in registry.names()
    assert "results" in registry.names()


def test_user_cannot_override_builtin_schema(agora_dir, sample_schemas):
    import json
    from agent_agora.schema import SchemaRegistry
    bad = dict(sample_schemas)
    bad["commands"] = {"type": "string"}
    (agora_dir / "schemas.json").write_text(json.dumps(bad))
    import pytest
    with pytest.raises(ValueError, match="reserved"):
        SchemaRegistry.load(agora_dir)


def test_builtin_commands_validates_correct_payload():
    from agent_agora.schema import SchemaRegistry
    reg = SchemaRegistry({})
    reg._inject_builtins()
    reg.validate_item("commands", {
        "id": "cmd-1",
        "source": "A",
        "target": "B",
        "payload": {"action": "noop"},
        "created_at": "2026-05-14T10:00:00Z",
    })
