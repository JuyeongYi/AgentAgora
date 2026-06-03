"""기능3 — MetricsCollector(시계열 in-memory ring buffer) 단위 테스트.

now_fn 주입 + fake dispatcher로 결정적 검증(wall-clock 비의존)."""
import logging

from agent_agora.dashboard.metrics import MetricsCollector
from agent_agora.dashboard.logbuffer import RingBufferLogHandler


class _FakeDispatcher:
    def __init__(self):
        self._depths = {}
        self.hooks = []

    def register_dispatch_hook(self, cb):
        self.hooks.append(cb)

    def peek(self, targets):
        return {iid: {"queue_depth": d} for iid, d in self._depths.items()}

    def fire(self, target):
        env = type("E", (), {"target": target})()
        for cb in self.hooks:
            cb(env)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_collector_records_inbox_depth_per_worker():
    d = _FakeDispatcher()
    d._depths["W1"] = 3
    clk = _Clock()
    c = MetricsCollector(dispatcher=d, instance_registry=None, now_fn=clk)
    c.sample()
    d._depths["W1"] = 5
    clk.t = 10
    c.sample()
    snap = c.snapshot()
    assert snap["workers"]["W1"]["inbox_depth"] == [3, 5]


def test_collector_dispatch_rate_from_hook_delta():
    d = _FakeDispatcher()
    clk = _Clock()
    c = MetricsCollector(dispatcher=d, instance_registry=None, now_fn=clk)
    c.attach_to_dispatcher()
    c.sample()  # t0 — 직전 없음, rate 0
    for _ in range(6):
        d.fire("W2")
    clk.t = 60.0
    c.sample()
    assert abs(c.snapshot()["global"]["dispatch_rate_per_min"][-1] - 6.0) < 0.01


def test_collector_error_rate_from_log_buffer_counter():
    d = _FakeDispatcher()
    clk = _Clock()
    buf = RingBufferLogHandler(capacity=10, level=logging.WARNING)
    c = MetricsCollector(dispatcher=d, instance_registry=None, log_buffer=buf, now_fn=clk)
    c.sample()
    buf.emit(logging.LogRecord("n", logging.ERROR, __file__, 0, "x", None, None))
    buf.emit(logging.LogRecord("n", logging.ERROR, __file__, 0, "y", None, None))
    clk.t = 60.0
    c.sample()
    assert abs(c.snapshot()["global"]["error_rate_per_min"][-1] - 2.0) < 0.01


def test_collector_ring_buffer_caps_at_capacity():
    d = _FakeDispatcher()
    clk = _Clock()
    c = MetricsCollector(dispatcher=d, instance_registry=None, capacity=5, now_fn=clk)
    for i in range(8):
        clk.t = float(i)
        c.sample()
    assert len(c.snapshot()["global"]["ts"]) == 5


def test_logbuffer_counts_monotonic():
    buf = RingBufferLogHandler(capacity=2, level=logging.WARNING)
    for _ in range(5):
        buf.emit(logging.LogRecord("n", logging.WARNING, __file__, 0, "m", None, None))
    buf.emit(logging.LogRecord("n", logging.ERROR, __file__, 0, "e", None, None))
    counts = buf.counts()
    assert counts["emitted"] == 6  # capacity evict와 무관하게 누적
    assert counts["errors"] == 1
