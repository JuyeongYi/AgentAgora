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


async def test_download_file_parses_rfc5987_filename(monkeypatch):
    # Starlette FileResponse emits only filename*=utf-8''<pct> for non-ASCII names.
    class FakeResp:
        status_code = 200
        content = b"hello"
        headers = {
            "content-disposition":
                "attachment; filename*=utf-8''%EB%B3%B4%EA%B3%A0%EC%84%9C.txt"}
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
    assert name == "보고서.txt"


async def test_upload_file_propagates_broker_error_body(monkeypatch):
    class FakeResp:
        status_code = 403
        text = "forbidden"
        def raise_for_status(self): raise AssertionError("should not be reached")
        def json(self): return {"error": "file_upload_denied: W1는 'x.txt'을 공유할 수 없습니다"}

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, headers=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    try:
        await _broker_http.upload_file(
            "http://h:8420/mcp", instance_id="W1", name="x.txt", data=b"abc")
        assert False, "expected exception"
    except Exception as e:
        assert "file_upload_denied" in str(e)


async def test_download_file_propagates_broker_error_body(monkeypatch):
    class FakeResp:
        status_code = 404
        text = "not found"
        headers = {}
        def raise_for_status(self): raise AssertionError("should not be reached")
        def json(self): return {"error": "unknown_file: file_id 'fid'를 찾을 수 없습니다."}

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    try:
        await _broker_http.download_file(
            "http://h:8420/mcp", instance_id="W1", file_id="fid")
        assert False, "expected exception"
    except Exception as e:
        assert "unknown_file" in str(e)
