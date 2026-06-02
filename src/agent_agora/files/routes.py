"""파일 공유 HTTP 엔드포인트 — POST /files (업로드), GET /files/<id> (다운로드).

원격 워커용. localhost 전용·토큰 없음 — 서버 127.0.0.1 바인딩에 의존.
요청자 식별은 X-Agora-Instance-Id 헤더(auto-register와 동일).
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from agent_agora.errors import AgoraError


def register(app: Starlette, *, file_store, file_policy) -> None:
    """app에 파일 업로드·다운로드 라우트를 등록한다."""

    max_bytes = file_store.max_bytes

    def _too_large(size: int) -> JSONResponse:
        return JSONResponse(
            {"error": str(AgoraError("file_too_large", size=size, limit=max_bytes))},
            status_code=413)

    async def upload(request: Request) -> JSONResponse:
        worker = request.headers.get("X-Agora-Instance-Id", "")
        name = request.headers.get("X-Agora-File-Name", "upload.bin")
        if not file_policy.can_upload(worker, name):
            return JSONResponse(
                {"error": str(AgoraError("file_upload_denied", worker=worker, name=name))},
                status_code=403)
        # Content-Length guard: reject before reading the body into memory.
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > max_bytes:
                    return _too_large(int(cl))
            except ValueError:
                pass
        # Stream with a cumulative cap — covers missing/chunked/forged Content-Length.
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > max_bytes:
                return _too_large(total)
            chunks.append(chunk)
        data = b"".join(chunks)
        try:
            handle = file_store.store_bytes(data, name, worker or None)
        except AgoraError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(handle)

    async def download(request: Request) -> Response:
        file_id = request.path_params["file_id"]
        worker = request.headers.get("X-Agora-Instance-Id", "")
        meta = file_store.meta(file_id)
        if meta is None:
            return JSONResponse(
                {"error": str(AgoraError("unknown_file", file_id=file_id))},
                status_code=404)
        if not file_policy.can_download(worker, meta["name"]):
            return JSONResponse(
                {"error": str(AgoraError("file_download_denied", worker=worker,
                                         name=meta["name"]))},
                status_code=403)
        path = file_store.path_of(file_id)
        if path is None:
            return JSONResponse(
                {"error": str(AgoraError("unknown_file", file_id=file_id))},
                status_code=404)
        return FileResponse(path, media_type=meta["content_type"]
                            or "application/octet-stream")

    app.router.routes.append(Route("/files", upload, methods=["POST"]))
    app.router.routes.append(Route("/files/{file_id}", download, methods=["GET"]))
