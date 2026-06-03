"""대시보드 시계열 메트릭 — in-memory ring-buffer 수집기.

서버는 시계열을 영속하지 않는다(RingBufferLogHandler/EventBroker와 동일한 ephemeral
정책). MetricsCollector는 (a) dispatch hook으로 dispatch·per-target 도착 카운터를
누적하고, (b) log_buffer의 누적 에러 카운터를 읽으며, (c) 주기 sample()이 호출될 때마다
dispatcher.peek로 per-worker inbox depth를 찍고 직전 샘플 대비 델타로 분당 rate를
계산해 고정 길이 deque에 push한다. __main__이 _metrics_sample_loop_10s로 구동.
"""
from __future__ import annotations

import datetime
import time
from collections import defaultdict, deque
from typing import Callable


def _iso(epoch: float) -> str:
    try:
        return datetime.datetime.fromtimestamp(
            epoch, datetime.timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return str(epoch)


class MetricsCollector:
    def __init__(self, *, dispatcher, instance_registry=None,
                 log_buffer=None, capacity: int = 360,
                 now_fn: Callable[[], float] = time.time) -> None:
        self._dispatcher = dispatcher
        self._instance_registry = instance_registry  # API 패리티(peek(None)로 대체 가능)
        self._log_buffer = log_buffer
        self._capacity = capacity
        self._now_fn = now_fn
        # dispatch hook 누적 카운터 (핫패스 — O(1))
        self._dispatch_count = 0
        self._arrivals: dict[str, int] = defaultdict(int)
        # 시계열 ring buffer
        self._global: deque[dict] = deque(maxlen=capacity)
        self._workers: dict[str, deque] = {}
        # 직전 샘플 상태 (rate 델타용)
        self._last_t: float | None = None
        self._last_dispatch = 0
        self._last_err = 0
        self._last_arrivals: dict[str, int] = {}

    def attach_to_dispatcher(self) -> None:
        self._dispatcher.register_dispatch_hook(self._on_dispatch)

    def _on_dispatch(self, envelope) -> None:
        # 핫패스 — O(1), exception-safe (증가만, IO 금지).
        try:
            self._dispatch_count += 1
            target = getattr(envelope, "target", None)
            if target is not None:
                self._arrivals[target] += 1
        except Exception:  # noqa: BLE001 — 메트릭이 라우팅을 깨면 안 됨
            pass

    def _rate(self, cur: float, prev: float, elapsed: float | None) -> float:
        if elapsed and elapsed > 0:
            return (cur - prev) / elapsed * 60.0
        return 0.0

    def sample(self) -> dict:
        """한 틱 — depth 스냅샷 + 누적 델타 rate를 deque에 push하고 push된 dict 반환."""
        now = self._now_fn()
        elapsed = None if self._last_t is None else (now - self._last_t)
        peek = self._dispatcher.peek(None)
        err_total = self._log_buffer.counts()["errors"] if self._log_buffer else 0
        total_depth = sum((p.get("queue_depth") or 0) for p in peek.values())

        g = {
            "ts": _iso(now),
            "dispatch_rate_per_min": self._rate(self._dispatch_count, self._last_dispatch, elapsed),
            "error_rate_per_min": self._rate(err_total, self._last_err, elapsed),
            "total_inbox_depth": total_depth,
        }
        self._global.append(g)

        for iid, p in peek.items():
            depth = p.get("queue_depth") or 0
            arr = self._arrivals.get(iid, 0)
            prev_arr = self._last_arrivals.get(iid, 0)
            self._workers.setdefault(iid, deque(maxlen=self._capacity)).append({
                "ts": _iso(now),
                "inbox_depth": depth,
                "dispatch_rate_per_min": self._rate(arr, prev_arr, elapsed),
            })

        self._last_t = now
        self._last_dispatch = self._dispatch_count
        self._last_err = err_total
        self._last_arrivals = dict(self._arrivals)
        return g

    def snapshot(self) -> dict:
        """시계열을 컬럼 배열로 직렬화한다 (JSON 직렬화 가능)."""
        def cols(samples, keys):
            return {k: [s[k] for s in samples] for k in keys}

        gkeys = ("ts", "dispatch_rate_per_min", "error_rate_per_min", "total_inbox_depth")
        wkeys = ("ts", "inbox_depth", "dispatch_rate_per_min")
        return {
            "sampled_at": _iso(self._last_t) if self._last_t is not None else None,
            "window_samples": self._capacity,
            "global": cols(list(self._global), gkeys),
            "workers": {iid: cols(list(dq), wkeys) for iid, dq in self._workers.items()},
        }
