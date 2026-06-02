"""dashboard_events pub/sub — SSE broker 단위 테스트."""
from __future__ import annotations

import asyncio
import datetime
import pytest

from agent_agora.dashboard import EventBroker
from agent_agora.envelope import make_envelope


@pytest.mark.asyncio
async def test_subscriber_receives_broadcast():
    broker = EventBroker(max_queue=100)
    sub = broker.subscribe(operator_user="alice")
    broker.publish({"type": "data_snapshot", "payload": {"x": 1}})
    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert evt == {"type": "data_snapshot", "payload": {"x": 1}}


@pytest.mark.asyncio
async def test_two_subscribers_each_receive():
    broker = EventBroker(max_queue=100)
    a = broker.subscribe(operator_user="alice")
    b = broker.subscribe(operator_user="bob")
    broker.publish({"type": "instance_registered", "instance_id": "W1"})
    ea = await asyncio.wait_for(a.get(), timeout=1.0)
    eb = await asyncio.wait_for(b.get(), timeout=1.0)
    assert ea == eb


@pytest.mark.asyncio
async def test_operator_inbox_event_routes_to_target_only():
    """operator_inbox_message는 target_operator 매칭 구독자에게만 전달."""
    broker = EventBroker(max_queue=100)
    a = broker.subscribe(operator_user="alice")
    b = broker.subscribe(operator_user="bob")
    broker.publish({
        "type": "operator_inbox_message",
        "target_operator": "alice",
        "envelope_preview": {"sender": "W1"},
    })
    # alice 받음
    ea = await asyncio.wait_for(a.get(), timeout=1.0)
    assert ea["target_operator"] == "alice"
    # bob에겐 안 옴 (1초 timeout으로 빈 큐 확인)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(b.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    broker = EventBroker(max_queue=100)
    sub = broker.subscribe(operator_user="alice")
    broker.unsubscribe(sub)
    broker.publish({"type": "data_snapshot"})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_queue_overflow_drops_oldest():
    broker = EventBroker(max_queue=3)
    sub = broker.subscribe(operator_user="alice")
    for i in range(5):
        broker.publish({"type": "data_snapshot", "i": i})
    # queue 최대 3개 보유 + 가장 오래된 것 drop
    items = []
    for _ in range(3):
        items.append(await asyncio.wait_for(sub.get(), timeout=0.2))
    indices = [item["i"] for item in items]
    assert indices == [2, 3, 4]  # 0, 1 dropped
    # 더 이상 항목 없음
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_attach_to_dispatcher_hooks():
    """attach_to_dispatcher가 dispatch/register/unregister hook을 등록."""
    class FakeDispatcher:
        def __init__(self) -> None:
            self.d_hooks = []
            self.r_hooks = []
            self.u_hooks = []
            self.dl_hooks = []
        def register_dispatch_hook(self, cb): self.d_hooks.append(cb)
        def register_register_hook(self, cb): self.r_hooks.append(cb)
        def register_unregister_hook(self, cb): self.u_hooks.append(cb)
        def register_deadline_hook(self, cb): self.dl_hooks.append(cb)

    d = FakeDispatcher()
    broker = EventBroker(max_queue=100)
    broker.attach_to_dispatcher(d)
    assert len(d.d_hooks) == 1
    assert len(d.r_hooks) == 1
    assert len(d.u_hooks) == 1
    assert len(d.dl_hooks) == 1


@pytest.mark.asyncio
async def test_on_deadline_publishes_deadline_expired():
    """deadline 만료 entry가 deadline_expired SSE 이벤트로 publish된다."""
    broker = EventBroker(max_queue=100)
    sub = broker.subscribe(operator_user="alice")
    broker._on_deadline({"command_id": "c1", "source": "Inst1", "target": "Inst2"})
    evt = await asyncio.wait_for(sub.get(), timeout=0.5)
    assert evt["type"] == "deadline_expired"
    assert evt["command_id"] == "c1"
    assert evt["source"] == "Inst1"
    assert evt["target"] == "Inst2"


@pytest.mark.asyncio
async def test_on_dispatch_publishes_message_dispatched():
    """Envelope→event 필드 매핑 검증.

    Envelope에는 'schema' 필드가 없다 — schema는 payload['msgtype']에서 가져온다.
    이 테스트는 'schema'가 silently None이 되는 버그를 잡는다."""
    broker = EventBroker()
    sub = broker.subscribe(operator_user="alice")
    env = make_envelope(
        cmd_id="cmd-1",
        source="W1",
        target="W2",
        payload={"msgtype": "delegation_request", "data": "x"},
        created_at="2026-01-01T00:00:00Z",
        conversation_id="c1",
    )
    broker._on_dispatch(env)
    evt = await asyncio.wait_for(sub.get(), timeout=0.5)
    assert evt["type"] == "message_dispatched"
    assert evt["from"] == "W1"
    assert evt["to"] == "W2"
    assert evt["schema"] == "delegation_request"
    assert evt["conversation_id"] == "c1"
    assert evt["timestamp"] == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_on_dispatch_to_operator_publishes_operator_inbox_message():
    """operator: 접두사 target은 operator_inbox_message 이벤트도 발화 — schema는 msgtype."""
    broker = EventBroker()
    sub = broker.subscribe(operator_user="alice")
    env = make_envelope(
        cmd_id="cmd-2",
        source="W1",
        target="operator:alice",
        payload={"msgtype": "status_report"},
        created_at="2026-01-01T00:00:01Z",
        conversation_id="c2",
    )
    broker._on_dispatch(env)
    # 두 개의 이벤트가 같은 큐에 들어간다: message_dispatched + operator_inbox_message
    evts = []
    for _ in range(2):
        evts.append(await asyncio.wait_for(sub.get(), timeout=0.5))
    by_type = {e["type"]: e for e in evts}
    assert by_type["message_dispatched"]["schema"] == "status_report"
    assert by_type["operator_inbox_message"]["target_operator"] == "alice"
    assert by_type["operator_inbox_message"]["schema"] == "status_report"
    assert by_type["operator_inbox_message"]["sender"] == "W1"


@pytest.mark.asyncio
async def test_auto_register_middleware_fires_register_hook():
    """AutoRegisterMiddleware가 등록 시 dispatcher.register hook을 발화한다.

    Fix 2 회귀 가드: 이 hook이 wired 되지 않으면 SSE에 instance_registered 이벤트가
    영원히 안 나간다."""
    from agent_agora.http.auto_register import AutoRegisterMiddleware
    from agent_agora.registry import InstanceRegistry

    class FakeDispatcher:
        def __init__(self) -> None:
            self.fired: list = []
        def notify_registered(self, info) -> None:
            self.fired.append(info)

    async def _noop_app(scope, receive, send): pass
    async def _send(_msg): pass
    async def _receive(): return {"type": "http.request"}

    reg = InstanceRegistry()
    disp = FakeDispatcher()
    mw = AutoRegisterMiddleware(app=_noop_app, registry=reg, dispatcher=disp)
    scope = {
        "type": "http",
        "headers": [
            (b"mcp-session-id", b"sess-rh"),
            (b"x-agora-instance-id", b"Worker-RH"),
            (b"x-agora-role", b"worker"),
        ],
    }
    await mw(scope, _receive, _send)
    assert len(disp.fired) == 1
    assert disp.fired[0].instance_id == "Worker-RH"
    assert disp.fired[0].role == "worker"


@pytest.mark.asyncio
async def test_sweeper_dead_session_fires_unregister_hook(tmp_path):
    """dead_session_sweep이 unregister hook을 발화한다 — wiring 회귀 가드."""
    from agent_agora.registry import BotRegistry
    from agent_agora.conversation_store import ConversationStore
    from agent_agora.storage.persistence import Persistence
    from agent_agora.registry import InstanceRegistry
    from agent_agora.storage.schemas import SchemaRegistry
    from agent_agora.sweeper import Sweeper

    class FakeDispatcher:
        def __init__(self) -> None:
            self.fired: list[str] = []
        def notify_unregistered(self, iid: str) -> None:
            self.fired.append(iid)

    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    inst_reg = InstanceRegistry()
    inst_reg.register("sess-dead", "DeadWorker", role="worker")
    # last_seen_at을 과거로 설정 — cutoff 보다 오래된 시각
    past = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=2)).isoformat()
    # touch_last_seen을 직접 못 쓰니 register dataclass 우회 — replace 사용
    from dataclasses import replace
    info = inst_reg.resolve_instance_id("DeadWorker")
    stale = replace(info, last_seen_at=past)
    inst_reg._by_instance["DeadWorker"] = stale  # type: ignore[attr-defined]
    inst_reg._by_session["sess-dead"] = stale  # type: ignore[attr-defined]

    disp = FakeDispatcher()
    sweeper = Sweeper(
        ConversationStore(persistence),
        inst_reg,
        BotRegistry(),
        SchemaRegistry(),
        persistence,
        close_timeout_ms=300_000,
        dead_session_timeout_ms=60_000,  # 1분 — 2시간 전 stale 인스턴스는 sweep 대상
        gc_retention_days=90,
        dispatcher=disp,
    )
    removed = sweeper.dead_session_sweep()
    assert "DeadWorker" in removed
    assert disp.fired == ["DeadWorker"]
