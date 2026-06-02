"""대시보드 로그 패널 백엔드 — in-memory ring buffer 로그 핸들러.

agent_agora.* 로거에 부착해 WARNING+ 레코드를 고정 크기 deque에 보관한다.
GET /dashboard/logs가 records()로 최근 운영 이벤트(타임아웃 sweep·인박스 드롭·
예외 등)를 운영자에게 노출한다. 파일/외부 sink 없이 프로세스 메모리에만 — 재시작 시
초기화된다(영속 로그는 별도 sink가 담당).
"""
from __future__ import annotations

import datetime
import logging
from collections import deque


class RingBufferLogHandler(logging.Handler):
    """최근 N개의 로그 레코드를 dict 형태로 보관하는 logging.Handler.

    capacity 초과 시 가장 오래된 레코드를 evict(deque maxlen). emit()은 어떤
    레코드에도 예외를 전파하지 않는다(로깅 경로가 깨지면 안 됨).
    """

    def __init__(self, *, capacity: int = 500, level: int = logging.WARNING) -> None:
        super().__init__(level=level)
        self._records: deque[dict] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.datetime.fromtimestamp(
                record.created, datetime.timezone.utc).isoformat()
            try:
                message = record.getMessage()
            except Exception:  # noqa: BLE001 — 포맷 인자 불일치 등; 메시지 누락 허용
                message = record.msg if isinstance(record.msg, str) else repr(record.msg)
            self._records.append({
                "time": ts,
                "level": record.levelname,
                "levelno": record.levelno,
                "logger": record.name,
                "message": message,
            })
        except Exception:  # noqa: BLE001 — 핸들러는 로깅을 깨면 안 됨
            self.handleError(record)

    def records(self, *, limit: int | None = None,
                min_level: int | str | None = None) -> list[dict]:
        """보관된 레코드를 오래된→최신 순으로 반환.

        min_level: numeric level 또는 이름("ERROR") — 이상만 필터.
        limit: 최신 N개만 반환.
        """
        items = list(self._records)
        if min_level is not None:
            if isinstance(min_level, str):
                threshold = logging.getLevelNamesMapping().get(min_level.upper(), 0)
            else:
                threshold = min_level
            items = [r for r in items if r["levelno"] >= threshold]
        if limit is not None:
            items = items[-limit:]
        return items
