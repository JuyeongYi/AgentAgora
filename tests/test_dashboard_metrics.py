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


def test_collector_prunes_workers_that_left_the_roster():
    """unregister된 워커(peek에서 사라진)는 snapshot에서 제거되고 내부 dict도 정리된다
    (ghost 워커·무한 증가 방지)."""
    d = _FakeDispatcher()
    d._depths["W1"] = 2
    d._depths["W2"] = 1
    clk = _Clock()
    c = MetricsCollector(dispatcher=d, instance_registry=None, now_fn=clk)
    c.sample()
    assert set(c.snapshot()["workers"]) == {"W1", "W2"}
    # W1 unregister → 더 이상 peek에 안 나옴
    del d._depths["W1"]
    clk.t = 10
    c.sample()
    snap = c.snapshot()
    assert "W1" not in snap["workers"]
    assert "W2" in snap["workers"]


def test_collector_reregistered_worker_starts_fresh_baseline():
    """같은 instance_id가 unregister 후 재등록되면 첫 rate가 0(스테일 baseline 재사용 안 함)."""
    d = _FakeDispatcher()
    clk = _Clock()
    c = MetricsCollector(dispatcher=d, instance_registry=None, now_fn=clk)
    c.attach_to_dispatcher()
    d._depths["W1"] = 0
    c.sample()                       # W1 등장
    for _ in range(3):
        d.fire("W1")                 # 도착 누적
    clk.t = 10
    c.sample()
    del d._depths["W1"]              # W1 unregister → prune
    clk.t = 20
    c.sample()
    d._depths["W1"] = 0              # 재등록
    clk.t = 30
    c.sample()
    # 재등록 직후 첫 샘플의 per-worker rate는 0(이전 도착 카운트 재사용 안 함)
    assert c.snapshot()["workers"]["W1"]["dispatch_rate_per_min"][-1] == 0.0


def test_logbuffer_counts_monotonic():
    buf = RingBufferLogHandler(capacity=2, level=logging.WARNING)
    for _ in range(5):
        buf.emit(logging.LogRecord("n", logging.WARNING, __file__, 0, "m", None, None))
    buf.emit(logging.LogRecord("n", logging.ERROR, __file__, 0, "e", None, None))
    counts = buf.counts()
    assert counts["emitted"] == 6  # capacity evict와 무관하게 누적
    assert counts["errors"] == 1
