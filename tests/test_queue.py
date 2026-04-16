# tests/test_queue.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_agora.schema import SchemaRegistry
from agent_agora.store import AgoraStore, AsyncWriteQueue


@pytest.fixture
def registry(agora_dir_with_schemas: Path) -> SchemaRegistry:
    return SchemaRegistry.load(agora_dir_with_schemas)


@pytest.fixture
def store(agora_dir_with_schemas: Path, registry: SchemaRegistry) -> AgoraStore:
    return AgoraStore(agora_dir_with_schemas, registry)


class TestAsyncWriteQueue:
    async def test_set_via_queue(self, store: AgoraStore) -> None:
        queue = AsyncWriteQueue(store)
        async with queue:
            await queue.submit_set("status", "review", "pending", wait=True)
        assert store.get("status", "review") == "pending"

    async def test_append_via_queue(self, agora_dir: Path) -> None:
        schemas = {"nums": {"type": "array", "items": {"type": "integer"}}}
        (agora_dir / "schemas.json").write_text(json.dumps(schemas))
        reg = SchemaRegistry.load(agora_dir)
        s = AgoraStore(agora_dir, reg)
        queue = AsyncWriteQueue(s)
        async with queue:
            await queue.submit_append("nums", "list1", 1, wait=True)
            await queue.submit_append("nums", "list1", 2, wait=True)
        assert s.get("nums", "list1") == [1, 2]

    async def test_delete_via_queue(self, store: AgoraStore) -> None:
        store.set("status", "review", "pending")
        queue = AsyncWriteQueue(store)
        async with queue:
            await queue.submit_delete("status", "review", wait=True)
        assert store.get("status", "review") is None

    async def test_no_wait_returns_immediately(self, store: AgoraStore) -> None:
        queue = AsyncWriteQueue(store)
        async with queue:
            await queue.submit_set("status", "review", "pending", wait=False)
            await asyncio.sleep(0.05)
        assert store.get("status", "review") == "pending"

    async def test_sequential_ordering(self, store: AgoraStore) -> None:
        queue = AsyncWriteQueue(store)
        async with queue:
            await queue.submit_set("status", "review", "pending", wait=True)
            await queue.submit_set("status", "review", "in_progress", wait=True)
            await queue.submit_set("status", "review", "complete", wait=True)
        assert store.get("status", "review") == "complete"

    async def test_validation_error_propagated(self, store: AgoraStore) -> None:
        queue = AsyncWriteQueue(store)
        async with queue:
            with pytest.raises(ValueError):
                await queue.submit_set("finding", "f1", {"file": "a.py"}, wait=True)
