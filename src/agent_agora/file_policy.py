"""파일 공유 권한 — 워커별 r/w gitignore 패턴. .agentagora/file-policy.json.

비활성(파일 없음) 시 전원 무제한. CommMatrix와 같은 거버넌스 패턴.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pathspec

from agent_agora.errors import AgoraError


class FilePolicy:
    """워커별 파일 업/다운로드 권한. r/w는 gitignore식 패턴 목록."""

    def __init__(self) -> None:
        self._workers: dict[str, dict[str, Any]] = {}
        self._fallback: dict[str, Any] | None = None
        self.active: bool = False

    def load_json(self, text: str) -> None:
        """file-policy.json 텍스트를 파싱해 *제자리 교체*. 잘못된 구조는 AgoraError."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AgoraError("file_policy_invalid", detail=str(e)) from None
        if not isinstance(data, dict):
            raise AgoraError("file_policy_invalid", detail="최상위는 JSON 객체여야 함")
        workers = data.get("workers", {})
        if not isinstance(workers, dict):
            raise AgoraError("file_policy_invalid", detail="'workers'는 객체여야 함")
        self._workers = workers
        self._fallback = data.get("fallback")
        self.active = True

    def _entry(self, worker_id: str) -> dict[str, Any] | None:
        """워커 정책 항목. 비활성·미등재+fallback없음이면 None(무제한)."""
        if not self.active:
            return None
        return self._workers.get(worker_id, self._fallback)

    @staticmethod
    def _match(patterns: list[str], file_name: str) -> bool:
        spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
        return spec.match_file(file_name)

    def can_upload(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 업로드할 수 있는가."""
        entry = self._entry(worker_id)
        if entry is None:
            return True
        return self._match(entry.get("w", []), file_name)  # w 누락 → [] → 거부

    def can_download(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 다운로드할 수 있는가."""
        entry = self._entry(worker_id)
        if entry is None:
            return True
        return self._match(entry.get("r", ["*"]), file_name)  # r 누락 → ["*"] → 허용

    def snapshot(self) -> dict[str, Any]:
        """현재 정책 조회용 (admin GET)."""
        if not self.active:
            return {}
        return {"workers": dict(self._workers), "fallback": self._fallback}


def load_file_policy(path: Path) -> FilePolicy:
    """path의 file-policy.json을 로드. 파일이 없으면 비활성 FilePolicy(무제한)."""
    fp = FilePolicy()
    if path.exists():
        fp.load_json(path.read_text("utf-8"))
    return fp
