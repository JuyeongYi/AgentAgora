"""대시보드 로그 패널 백엔드 — RingBufferLogHandler 단위 테스트.

agent_agora.* 로거의 WARNING+ 레코드를 in-memory ring buffer에 보관해
GET /dashboard/logs가 최근 운영 이벤트(타임아웃·드롭·예외)를 노출하게 한다.
"""
import logging

from agent_agora.dashboard.logbuffer import RingBufferLogHandler


def _rec(name, level, msg):
    return logging.LogRecord(name, level, __file__, 0, msg, None, None)


def test_captures_records_as_dicts():
    h = RingBufferLogHandler(capacity=10, level=logging.WARNING)
    log = logging.getLogger("test.logbuffer.capture")
    log.setLevel(logging.WARNING)
    log.addHandler(h)
    try:
        log.warning("hello %s", "world")
        log.error("boom")
    finally:
        log.removeHandler(h)
    recs = h.records()
    assert len(recs) == 2
    assert recs[0]["message"] == "hello world"
    assert recs[0]["level"] == "WARNING"
    assert recs[1]["level"] == "ERROR"
    assert recs[0]["logger"] == "test.logbuffer.capture"
    assert "time" in recs[0] and recs[0]["time"]


def test_ring_buffer_evicts_oldest():
    h = RingBufferLogHandler(capacity=3, level=logging.WARNING)
    for i in range(5):
        h.emit(_rec("n", logging.WARNING, "m%d" % i))
    assert [r["message"] for r in h.records()] == ["m2", "m3", "m4"]


def test_below_handler_level_is_dropped():
    h = RingBufferLogHandler(capacity=10, level=logging.WARNING)
    log = logging.getLogger("test.logbuffer.level")
    log.setLevel(logging.DEBUG)
    log.addHandler(h)
    try:
        log.info("ignored")
        log.warning("kept")
    finally:
        log.removeHandler(h)
    assert [r["message"] for r in h.records()] == ["kept"]


def test_records_min_level_filter_and_limit():
    h = RingBufferLogHandler(capacity=10, level=logging.WARNING)
    for i in range(3):
        h.emit(_rec("n", logging.WARNING, "w%d" % i))
    h.emit(_rec("n", logging.ERROR, "e0"))
    assert [r["message"] for r in h.records(min_level="ERROR")] == ["e0"]
    assert len(h.records(limit=2)) == 2
    # min_level은 numeric level number도 받는다
    assert [r["message"] for r in h.records(min_level=logging.ERROR)] == ["e0"]


def test_emit_never_raises_on_bad_format():
    """포맷 인자 불일치 같은 깨진 레코드가 와도 핸들러가 예외를 전파하지 않는다."""
    h = RingBufferLogHandler(capacity=10, level=logging.WARNING)
    bad = logging.LogRecord("n", logging.WARNING, __file__, 0, "x %d", ("not-int",), None)
    h.emit(bad)  # raises 아니면 통과; 메시지 누락은 허용
