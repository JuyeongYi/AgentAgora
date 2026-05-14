# tests/test_store.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_agora.schema import SchemaRegistry
from agent_agora.store import AgoraStore


@pytest.fixture
def registry(agora_dir_with_schemas: Path) -> SchemaRegistry:
    return SchemaRegistry.load(agora_dir_with_schemas)


@pytest.fixture
def store(agora_dir_with_schemas: Path, registry: SchemaRegistry) -> AgoraStore:
    return AgoraStore(agora_dir_with_schemas, registry)


class TestStoreSetGet:
    def test_set_and_get(self, store: AgoraStore) -> None:
        store.set("finding", "f1", {"file": "a.py", "line": 1, "severity": "low"})
        result = store.get("finding", "f1")
        assert result == {"file": "a.py", "line": 1, "severity": "low"}

    def test_get_missing_key(self, store: AgoraStore) -> None:
        result = store.get("finding", "nonexistent")
        assert result is None

    def test_set_overwrites(self, store: AgoraStore) -> None:
        store.set("status", "review", "pending")
        store.set("status", "review", "complete")
        assert store.get("status", "review") == "complete"

    def test_set_unknown_schema_raises(self, store: AgoraStore) -> None:
        with pytest.raises(KeyError):
            store.set("unknown", "k", "v")

    def test_set_invalid_value_raises(self, store: AgoraStore) -> None:
        with pytest.raises(ValueError):
            store.set("finding", "f1", {"file": "a.py"})  # missing required

    def test_get_unknown_schema_raises(self, store: AgoraStore) -> None:
        with pytest.raises(KeyError):
            store.get("unknown", "k")


class TestStoreAppend:
    def test_append_creates_list(self, agora_dir: Path) -> None:
        schemas = {
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
            }
        }
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        s.append("items", "list1", {"n": 1})
        assert s.get("items", "list1") == [{"n": 1}]

    def test_append_adds_to_existing(self, agora_dir: Path) -> None:
        schemas = {
            "items": {
                "type": "array",
                "items": {"type": "integer"},
            }
        }
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        s.append("items", "nums", 1)
        s.append("items", "nums", 2)
        assert s.get("items", "nums") == [1, 2]

    def test_append_non_array_raises(self, store: AgoraStore) -> None:
        store.set("status", "review", "pending")
        with pytest.raises(TypeError):
            store.append("status", "review", "more")

    def test_append_invalid_item_raises(self, agora_dir: Path) -> None:
        schemas = {
            "items": {
                "type": "array",
                "items": {"type": "integer"},
            }
        }
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        with pytest.raises(ValueError):
            s.append("items", "nums", "not_an_int")


class TestStoreDelete:
    def test_delete_existing(self, store: AgoraStore) -> None:
        store.set("status", "review", "pending")
        store.delete("status", "review")
        assert store.get("status", "review") is None

    def test_delete_missing_key_no_error(self, store: AgoraStore) -> None:
        store.delete("status", "nonexistent")


class TestStoreList:
    def test_list_schemas(self, store: AgoraStore) -> None:
        result = store.list_schemas()
        assert {"finding", "status"}.issubset(result)

    def test_list_keys_empty(self, store: AgoraStore) -> None:
        assert store.list_keys("finding") == []

    def test_list_keys_with_data(self, store: AgoraStore) -> None:
        store.set("finding", "a", {"file": "a.py", "line": 1, "severity": "low"})
        store.set("finding", "b", {"file": "b.py", "line": 2, "severity": "high"})
        assert sorted(store.list_keys("finding")) == ["a", "b"]


class TestStorePersistence:
    def test_set_writes_file(self, agora_dir_with_schemas: Path, store: AgoraStore) -> None:
        store.set("status", "review", "pending")
        data_file = agora_dir_with_schemas / "status.json"
        assert data_file.exists()
        data = json.loads(data_file.read_text())
        assert data == {"review": "pending"}

    def test_restore_from_files(self, agora_dir_with_schemas: Path, registry: SchemaRegistry) -> None:
        data = {"f1": {"file": "a.py", "line": 1, "severity": "low"}}
        (agora_dir_with_schemas / "finding.json").write_text(json.dumps(data))
        store2 = AgoraStore(agora_dir_with_schemas, registry)
        assert store2.get("finding", "f1") == {"file": "a.py", "line": 1, "severity": "low"}

    def test_delete_updates_file(self, agora_dir_with_schemas: Path, store: AgoraStore) -> None:
        store.set("status", "a", "pending")
        store.set("status", "b", "complete")
        store.delete("status", "a")
        data = json.loads((agora_dir_with_schemas / "status.json").read_text())
        assert data == {"b": "complete"}
