"""파일 HTTP 엔드포인트 테스트."""
from __future__ import annotations

import json as _json

from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.files import FilePolicy, FileStore, register
from agent_agora.storage.persistence import Persistence


def _client(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    store = FileStore(tmp_path, p)
    policy = FilePolicy()
    app = Starlette()
    register(app, file_store=store, file_policy=policy)
    return TestClient(app), store, policy


def test_upload_then_download(tmp_path):
    client, _, _ = _client(tmp_path)
    r = client.post("/files", content=b"hello bytes",
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "doc.md"})
    assert r.status_code == 200
    fid = r.json()["file_id"]
    r2 = client.get(f"/files/{fid}", headers={"X-Agora-Instance-Id": "Reviewer1"})
    assert r2.status_code == 200
    assert r2.content == b"hello bytes"


def test_download_includes_filename_disposition(tmp_path):
    # 어댑터가 ./agora-inbox/<원래이름>에 저장하려면 원래 파일명을 알아야 한다.
    client, _, _ = _client(tmp_path)
    r = client.post("/files", content=b"contents",
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "r.txt"})
    assert r.status_code == 200
    fid = r.json()["file_id"]
    r2 = client.get(f"/files/{fid}", headers={"X-Agora-Instance-Id": "Reviewer1"})
    assert r2.status_code == 200
    disposition = r2.headers.get("content-disposition", "")
    assert "filename" in disposition
    assert "r.txt" in disposition


def test_download_unknown_404(tmp_path):
    client, _, _ = _client(tmp_path)
    r = client.get("/files/nope", headers={"X-Agora-Instance-Id": "X"})
    assert r.status_code == 404


def test_upload_denied_403(tmp_path):
    client, _, policy = _client(tmp_path)
    policy.load_json(_json.dumps({"workers": {"Coder1": {"r": ["*"], "w": ["*.md"]}}}))
    r = client.post("/files", content=b"x",
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "evil.exe"})
    assert r.status_code == 403


def test_download_denied_403(tmp_path):
    client, store, policy = _client(tmp_path)
    # store a file directly (bypasses policy)
    handle = store.store_bytes(b"secret data", "secret.bin", "Uploader")
    file_id = handle["file_id"]
    # load a policy where Reviewer1 can only read *.md, not *.bin
    policy.load_json(_json.dumps({"workers": {"Reviewer1": {"r": ["*.md"], "w": []}}}))
    r = client.get(f"/files/{file_id}",
                   headers={"X-Agora-Instance-Id": "Reviewer1"})
    assert r.status_code == 403


def _client_max(tmp_path, max_bytes):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    store = FileStore(tmp_path, p, max_bytes=max_bytes)
    policy = FilePolicy()
    app = Starlette()
    register(app, file_store=store, file_policy=policy)
    return TestClient(app)


def test_upload_rejected_when_content_length_exceeds_max(tmp_path):
    # Content-Length guard: 413 before the body is read into memory.
    client = _client_max(tmp_path, 10)
    r = client.post("/files", content=b"x" * 20,
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "big.bin"})
    assert r.status_code == 413


def test_upload_rejected_when_streamed_body_exceeds_max(tmp_path):
    # No Content-Length (chunked): the streaming accumulation cap must still 413.
    client = _client_max(tmp_path, 10)

    def gen():
        yield b"x" * 20

    r = client.post("/files", content=gen(),
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "big.bin"})
    assert r.status_code == 413


def test_upload_within_limit_succeeds(tmp_path):
    client = _client_max(tmp_path, 1000)
    r = client.post("/files", content=b"small payload",
                    headers={"X-Agora-Instance-Id": "Coder1",
                             "X-Agora-File-Name": "ok.md"})
    assert r.status_code == 200
    assert "file_id" in r.json()
