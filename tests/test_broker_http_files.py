import httpx
from agent_agora import _broker_http


async def test_upload_file_posts_bytes_with_headers(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"file_id": "fid", "name": "a.txt", "size": 3, "sha256": "x"}

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, headers=None):
            captured.update(url=url, content=content, headers=headers)
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    handle = await _broker_http.upload_file(
        "http://h:8420/mcp", instance_id="W1", name="a.txt", data=b"abc")
    assert handle["file_id"] == "fid"
    assert captured["url"].endswith("/files")
    assert captured["headers"]["X-Agora-Instance-Id"] == "W1"
    assert captured["headers"]["X-Agora-File-Name"] == "a.txt"
    assert captured["content"] == b"abc"


async def test_download_file_returns_bytes_and_name(monkeypatch):
    class FakeResp:
        status_code = 200
        content = b"hello"
        headers = {"content-disposition": 'attachment; filename="report.pdf"'}
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    data, name = await _broker_http.download_file(
        "http://h:8420/mcp", instance_id="W1", file_id="fid")
    assert data == b"hello"
    assert name == "report.pdf"
