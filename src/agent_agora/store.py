# src/agent_agora/store.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import Enum
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


class _Op(Enum):
    SET = "set"
    APPEND = "append"
    DELETE = "delete"


@dataclass
class _WriteRequest:
    op: _Op
    schema_name: str
    key: str
    value: Any = None
    future: asyncio.Future | None = None


class AsyncWriteQueue:
    """비동기 쓰기 큐. 모든 쓰기를 순차 처리한다."""

    def __init__(self, store: AgoraStore) -> None:
        self._store = store
        self._queue: asyncio.Queue[_WriteRequest | None] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def __aenter__(self) -> AsyncWriteQueue:
        self._worker_task = asyncio.create_task(self._worker())
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._queue.put(None)
        if self._worker_task is not None:
            await self._worker_task

    async def _worker(self) -> None:
        while True:
            req = await self._queue.get()
            if req is None:
                break
            try:
                if req.op == _Op.SET:
                    self._store.set(req.schema_name, req.key, req.value)
                elif req.op == _Op.APPEND:
                    self._store.append(req.schema_name, req.key, req.value)
                elif req.op == _Op.DELETE:
                    self._store.delete(req.schema_name, req.key)
                if req.future is not None:
                    req.future.set_result(None)
            except Exception as e:
                if req.future is not None:
                    req.future.set_exception(e)

    async def _submit(self, op: _Op, schema_name: str, key: str, value: Any, wait: bool) -> None:
        loop = asyncio.get_running_loop()
        future = loop.create_future() if wait else None
        await self._queue.put(_WriteRequest(op, schema_name, key, value, future))
        if future is not None:
            await future

    async def submit_set(self, schema_name: str, key: str, value: Any, *, wait: bool = True) -> None:
        await self._submit(_Op.SET, schema_name, key, value, wait)

    async def submit_append(self, schema_name: str, key: str, item: Any, *, wait: bool = False) -> None:
        await self._submit(_Op.APPEND, schema_name, key, item, wait)

    async def submit_delete(self, schema_name: str, key: str, *, wait: bool = True) -> None:
        await self._submit(_Op.DELETE, schema_name, key, None, wait)
