"""대시보드 서버 헬스 메트릭 수집기.

읽기만 하는 collector — 외부 상태(서버 시작 시각, DB 경로, persistence,
sweeper)를 참조해 snapshot dict를 만든다. 어느 메트릭이든 수집 실패 시
None으로 폴백 (전체 snapshot이 깨지지 않도록).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class _HasQueueDepth(Protocol):
    def write_queue_depth(self) -> int: ...


@runtime_checkable
class _HasSweeperStats(Protocol):
    dead_session_sweep_runs_total: int
    dead_session_sweep_last_run_at: float | None


@dataclass
class HealthCollector:
    started_at: float
    db_path: Path
    persistence: _HasQueueDepth
    sweeper: _HasSweeperStats

    def snapshot(self) -> dict:
        return {
            "uptime_seconds": self._uptime(),
            "db_size_bytes": self._db_size(),
            "write_queue_depth": self._queue_depth(),
            "sweeper_runs_total": self._sweeper_runs(),
            "sweeper_last_run_at": self._sweeper_last(),
        }

    def _uptime(self) -> int | None:
        try:
            return int(time.time() - self.started_at)
        except Exception:
            return None

    def _db_size(self) -> int | None:
        try:
            return self.db_path.stat().st_size
        except (OSError, FileNotFoundError):
            return None

    def _queue_depth(self) -> int | None:
        try:
            return int(self.persistence.write_queue_depth())
        except Exception:
            return None

    def _sweeper_runs(self) -> int | None:
        try:
            return int(self.sweeper.dead_session_sweep_runs_total)
        except Exception:
            return None

    def _sweeper_last(self) -> float | None:
        try:
            return self.sweeper.dead_session_sweep_last_run_at
        except Exception:
            return None
