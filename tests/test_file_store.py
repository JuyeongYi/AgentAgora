"""FileStore — 파일 스토어 저장/조회/GC."""
from __future__ import annotations

import datetime

import pytest

from agent_agora.errors import AgoraError
from agent_agora.file_store import FileStore
from agent_agora.persistence import Persistence
from agent_agora.schemas import FILE_SHARE_NAME, FILE_SHARE_BODY


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
