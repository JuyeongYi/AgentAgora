"""FileStore — 파일 스토어 저장/조회/GC."""
from __future__ import annotations

import datetime

import pytest

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.conversation_store import ConversationStore
from agent_agora.errors import AgoraError
from agent_agora.files import FileStore
from agent_agora.storage.persistence import Persistence
from agent_agora.registry import InstanceRegistry
from agent_agora.storage.schemas import FILE_SHARE_NAME, FILE_SHARE_BODY
from agent_agora.sweeper import Sweeper
from _helpers import make_schema_registry


def test_file_share_schema_constant():
    assert FILE_SHARE_NAME == "file_share"
    props = FILE_SHARE_BODY["properties"]
    assert props["msgtype"]["const"] == "file_share"
    for k in ("file_id", "name", "size", "sha256", "from", "ts"):
        assert k in props


def _store(tmp_path, max_bytes=104_857_600):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    return FileStore(tmp_path, p, max_bytes=max_bytes), p


def test_store_path_copies_and_records(tmp_path):
    store, _ = _store(tmp_path)
    src = tmp_path / "report.md"
    src.write_text("hello", encoding="utf-8")
    h = store.store_path(src, "report.md", "Coder1")
    assert set(h) == {"file_id", "name", "size", "sha256"}
    assert h["name"] == "report.md" and h["size"] == 5
    assert src.read_text(encoding="utf-8") == "hello"  # 원본 보존
    meta = store.meta(h["file_id"])
    assert meta["registered_by"] == "Coder1" and meta["sha256"] == h["sha256"]
    assert store.path_of(h["file_id"]).read_bytes() == b"hello"


def test_store_bytes(tmp_path):
    store, _ = _store(tmp_path)
    h = store.store_bytes(b"abc", "x.txt", "Bot1")
    assert h["size"] == 3
    assert store.path_of(h["file_id"]).read_bytes() == b"abc"


def test_list_returns_all_metadata_newest_first(tmp_path):
    """FileStore.list() — 저장된 모든 파일의 메타를 created_at 내림차순으로."""
    store, _ = _store(tmp_path)
    h1 = store.store_bytes(b"a", "first.txt", "Coder1")
    h2 = store.store_bytes(b"bb", "second.txt", "Bot1")
    rows = store.list()
    assert {r["file_id"] for r in rows} == {h1["file_id"], h2["file_id"]}
    # 메타 컬럼 전부 노출 (바이트는 제외)
    r = next(r for r in rows if r["file_id"] == h2["file_id"])
    assert r["name"] == "second.txt" and r["size"] == 2
    assert r["registered_by"] == "Bot1" and r["sha256"] == h2["sha256"]
    assert "created_at" in r
    # created_at 내림차순 (동률이면 안정성만 요구) — 최신이 앞
    assert [r["created_at"] for r in rows] == sorted(
        [r["created_at"] for r in rows], reverse=True)


def test_list_empty_when_no_files(tmp_path):
    store, _ = _store(tmp_path)
    assert store.list() == []


def test_too_large_rejected(tmp_path):
    store, _ = _store(tmp_path, max_bytes=4)
    src = tmp_path / "big.bin"
    src.write_bytes(b"12345")
    with pytest.raises(AgoraError) as ei:
        store.store_path(src, "big.bin", "Coder1")
    assert ei.value.code == "file_too_large"


def test_meta_and_path_unknown(tmp_path):
    store, _ = _store(tmp_path)
    assert store.meta("nope") is None
    assert store.path_of("nope") is None


def test_gc_removes_old(tmp_path):
    store, p = _store(tmp_path)
    h = store.store_bytes(b"old", "old.txt", "Coder1")
    future = (datetime.datetime.now(datetime.timezone.utc)
              + datetime.timedelta(days=1)).isoformat()
    removed = store.gc(future)
    assert removed == 1
    assert store.meta(h["file_id"]) is None
    assert store.path_of(h["file_id"]) is None


def test_file_gc_sweep_removes_expired(tmp_path):
    store, p = _store(tmp_path)
    h = store.store_bytes(b"old", "old.txt", "Coder1")
    instance_registry = InstanceRegistry()
    bot_registry = BotRegistry()
    schema_registry = make_schema_registry()
    conv_store = ConversationStore(p)
    sw = Sweeper(
        conv_store, instance_registry, bot_registry, schema_registry, p,
        close_timeout_ms=300_000, dead_session_timeout_ms=1_800_000,
        gc_retention_days=90,
        file_store=store, file_retention_days=0,
    )
    removed = sw.file_gc_sweep()
    assert removed == 1
    assert store.meta(h["file_id"]) is None
