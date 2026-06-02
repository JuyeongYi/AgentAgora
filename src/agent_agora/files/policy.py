"""파일 공유 권한 — 워커별 r/w gitignore 패턴. .agentagora/file-policy.json.

워커 키는 정규식 패턴 — 인스턴스 id를 re.fullmatch로 대조한다.
비활성(파일 없음) 시 전원 무제한. CommMatrix와 같은 거버넌스 패턴.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pathspec

from agent_agora.errors import AgoraError


class FilePolicy:
    """워커별 파일 업/다운로드 권한. 워커 키는 정규식, r/w는 gitignore식 패턴."""

    def __init__(self) -> None:
        self._workers: dict[str, dict[str, Any]] = {}
        self._compiled: dict[str, re.Pattern[str]] = {}
        self.active: bool = False

    def load_json(self, text: str) -> None:
        """file-policy.json 텍스트를 파싱해 *제자리 교체*. 잘못된 구조는 AgoraError.
        워커 키는 정규식으로 컴파일된다. 폐지된 'fallback' 필드가 있으면 거부."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AgoraError("file_policy_invalid", detail=str(e)) from None
        if not isinstance(data, dict):
            raise AgoraError("file_policy_invalid", detail="최상위는 JSON 객체여야 함")
        if "fallback" in data:
            raise AgoraError(
                "file_policy_invalid",
                detail="'fallback' 필드는 폐지됨 — workers의 '.*' 키로 이전하라")
        workers = data.get("workers", {})
        if not isinstance(workers, dict):
            raise AgoraError("file_policy_invalid", detail="'workers'는 객체여야 함")
        compiled: dict[str, re.Pattern[str]] = {}
        for key in workers:
            try:
                compiled[key] = re.compile(key)
            except re.error as e:
                raise AgoraError(
                    "file_policy_invalid",
                    detail=f"worker 키 '{key}'는 정규식이 아님: {e}") from None
        self._workers = workers
        self._compiled = compiled
        self.active = True

    def _matching(self, worker_id: str) -> list[dict[str, Any]]:
        """worker_id에 fullmatch되는 모든 정책 항목. 비활성이면 빈 리스트."""
        if not self.active:
            return []
        return [entry for key, entry in self._workers.items()
                if self._compiled[key].fullmatch(worker_id) is not None]

    @staticmethod
    def _match(patterns: list[str], file_name: str) -> bool:
        spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        return spec.match_file(file_name)

    def can_upload(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 업로드할 수 있는가.
        매칭 항목 중 하나라도 허용하면 허용. 매칭 항목 없으면 무제한."""
        entries = self._matching(worker_id)
        if not entries:
            return True
        return any(self._match(e.get("w", []), file_name) for e in entries)

    def can_download(self, worker_id: str, file_name: str) -> bool:
        """worker_id가 file_name(basename)을 다운로드할 수 있는가.
        매칭 항목 중 하나라도 허용하면 허용. 매칭 항목 없으면 무제한."""
        entries = self._matching(worker_id)
        if not entries:
            return True
        return any(self._match(e.get("r", ["*"]), file_name) for e in entries)

    def snapshot(self) -> dict[str, Any]:
        """현재 정책 조회용 (admin GET)."""
        if not self.active:
            return {}
        return {"workers": dict(self._workers)}


def load_file_policy(path: Path) -> FilePolicy:
    """path의 file-policy.json을 로드. 파일이 없으면 비활성 FilePolicy(무제한)."""
    fp = FilePolicy()
    if path.exists():
        fp.load_json(path.read_text("utf-8"))
    return fp
