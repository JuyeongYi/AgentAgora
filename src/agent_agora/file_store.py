"""파일 스토어 — .agentagora/files/ 바이트 저장 + files 메타 테이블 관리."""
from __future__ import annotations

import datetime
import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from agent_agora.errors import AgoraError
from agent_agora.persistence import Persistence

_DEFAULT_MAX_BYTES = 104_857_600  # 100 MB


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class FileStore:
    """공유 파일 바이트는 agora_dir/files/<file_id>에, 메타는 SQLite files 테이블에."""

    def __init__(self, agora_dir: Path, persistence: Persistence, *,
                 max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._dir = agora_dir / "files"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._persistence = persistence
        self._max_bytes = max_bytes

    def _record(self, file_id, name, size, sha, ctype, registered_by) -> dict:
        self._persistence.save_file(file_id, name, size, sha, ctype,
                                    registered_by, _now_iso())
        return {"file_id": file_id, "name": name, "size": size, "sha256": sha}

    def store_path(self, src: Path, name: str, registered_by: str | None) -> dict:
        """로컬 파일 src를 스토어에 *복사*(원본 보존)하고 핸들을 반환한다."""
        size = src.stat().st_size
        if size > self._max_bytes:
            raise AgoraError("file_too_large", size=size, limit=self._max_bytes)
        file_id = str(uuid.uuid4())
        dest = self._dir / file_id
        shutil.copyfile(src, dest)
        return self._record(file_id, name, size, _sha256_file(dest),
                            mimetypes.guess_type(name)[0], registered_by)

    def store_bytes(self, data: bytes, name: str, registered_by: str | None) -> dict:
        """바이트를 스토어에 저장하고 핸들을 반환한다 (HTTP 업로드용)."""
        if len(data) > self._max_bytes:
            raise AgoraError("file_too_large", size=len(data), limit=self._max_bytes)
        file_id = str(uuid.uuid4())
        (self._dir / file_id).write_bytes(data)
        return self._record(file_id, name, len(data), hashlib.sha256(data).hexdigest(),
                            mimetypes.guess_type(name)[0], registered_by)

    def meta(self, file_id: str) -> dict | None:
        return self._persistence.get_file(file_id)

    def path_of(self, file_id: str) -> Path | None:
        """스토어 내 파일 경로. 메타·바이트 둘 다 있어야 반환, 아니면 None."""
        if self._persistence.get_file(file_id) is None:
            return None
        p = self._dir / file_id
        return p if p.is_file() else None

    def gc(self, cutoff_iso: str) -> int:
        """created_at < cutoff_iso 인 파일을 바이트·메타 모두 삭제. 삭제 수 반환."""
        victims = self._persistence.files_before(cutoff_iso)
        for fid in victims:
            (self._dir / fid).unlink(missing_ok=True)
            self._persistence.delete_file(fid)
        return len(victims)
