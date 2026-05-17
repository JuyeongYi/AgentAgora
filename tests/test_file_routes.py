"""파일 HTTP 엔드포인트 테스트."""
from __future__ import annotations

import json as _json

from starlette.applications import Starlette
from starlette.testclient import TestClient

from agent_agora.file_policy import FilePolicy
from agent_agora.file_routes import register
from agent_agora.file_store import FileStore
from agent_agora.persistence import Persistence


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
