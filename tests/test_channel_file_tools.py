import json
from pathlib import Path
from agent_agora import channel_adapter as ca


async def test_file_put_uploads_and_returns_handle(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_bytes(b"abc")

    async def fake_upload(broker, *, instance_id, name, data):
        assert data == b"abc" and name == "a.txt" and instance_id == "W1"
        return {"file_id": "fid", "name": "a.txt", "size": 3}

    monkeypatch.setattr(ca._broker_http, "upload_file", fake_upload)
    call = ca._make_file_call_tool("http://h:8420/mcp", "W1")
    result = await call("file.put", {"path": str(src)})
    data = json.loads(result[0].text)
    assert data["file_id"] == "fid"


async def test_file_get_downloads_to_inbox(tmp_path, monkeypatch):
    async def fake_download(broker, *, instance_id, file_id):
        return b"hello", "report.txt"

    monkeypatch.setattr(ca._broker_http, "download_file", fake_download)
    monkeypatch.chdir(tmp_path)
    call = ca._make_file_call_tool("http://h:8420/mcp", "W1")
    result = await call("file.get", {"file_id": "fid"})
    data = json.loads(result[0].text)
    saved = Path(data["path"])
    assert saved.read_bytes() == b"hello"
    assert saved == tmp_path / "agora-inbox" / "report.txt"


async def test_file_get_existing_dest_errors(tmp_path, monkeypatch):
    async def fake_download(broker, *, instance_id, file_id):
        return b"hello", "report.txt"

    monkeypatch.setattr(ca._broker_http, "download_file", fake_download)
    inbox = tmp_path / "agora-inbox"
    inbox.mkdir()
    (inbox / "report.txt").write_bytes(b"old")
    monkeypatch.chdir(tmp_path)
    call = ca._make_file_call_tool("http://h:8420/mcp", "W1")
    result = await call("file.get", {"file_id": "fid"})
    data = json.loads(result[0].text)
    assert "file_exists" in data["error"]
    assert (inbox / "report.txt").read_bytes() == b"old"
