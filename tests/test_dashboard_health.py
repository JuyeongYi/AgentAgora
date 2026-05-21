"""dashboard_health 메트릭 수집 단위 테스트."""
from __future__ import annotations

import time

from agent_agora.dashboard_health import HealthCollector


class _FakePersistence:
    def __init__(self, depth: int) -> None:
        self._depth = depth

    def write_queue_depth(self) -> int:
        return self._depth


class _FakeSweeper:
    dead_session_sweep_runs_total = 5
    dead_session_sweep_last_run_at = 1700000000.0


def test_uptime_seconds_increases(tmp_path):
    db = tmp_path / "agora.db"
    db.write_bytes(b"x" * 1024)  # 1KB

    started_at = time.time() - 60.0
    health = HealthCollector(
        started_at=started_at, db_path=db,
        persistence=_FakePersistence(0), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["uptime_seconds"] >= 60
    assert snap["uptime_seconds"] < 70


def test_db_size_reflects_file_size(tmp_path):
    db = tmp_path / "agora.db"
    db.write_bytes(b"x" * 4096)

    health = HealthCollector(
        started_at=time.time(), db_path=db,
        persistence=_FakePersistence(0), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["db_size_bytes"] == 4096


def test_write_queue_and_sweeper_passthrough(tmp_path):
    db = tmp_path / "agora.db"
    db.write_bytes(b"")

    health = HealthCollector(
        started_at=time.time(), db_path=db,
        persistence=_FakePersistence(7), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["write_queue_depth"] == 7
    assert snap["sweeper_runs_total"] == 5
    assert snap["sweeper_last_run_at"] == 1700000000.0


def test_missing_db_file_returns_null(tmp_path):
    """DB 파일이 없으면 db_size_bytes는 None (collector는 raise 안 함)."""
    health = HealthCollector(
        started_at=time.time(), db_path=tmp_path / "missing.db",
        persistence=_FakePersistence(0), sweeper=_FakeSweeper(),
    )
    snap = health.snapshot()
    assert snap["db_size_bytes"] is None
