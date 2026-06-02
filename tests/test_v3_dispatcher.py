import pytest
import asyncio

from agent_agora.registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry
from agent_agora.persistence import Persistence, AsyncWriteQueue
from _helpers import make_schema_registry, tany


@pytest.fixture
async def setup(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 9):
        registry.register(f"sess-{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                bot_registry=BotRegistry(),
                                comm_matrix=CommMatrix(),
                                default_timeout_ms=500)
        yield registry, persistence, dispatcher


@pytest.mark.asyncio
async def test_dispatch_wait_unchanged_when_new_optional_fields_omitted(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(m="hi"))
    drained = await dispatcher.flush("Inst3")
    assert len(drained) == 1
    assert drained[0]["payload"] == tany(m="hi")
    assert drained[0]["id"] == res["command_id"]
    assert drained[0]["conversation_id"] == res["conversation_id"]


@pytest.mark.asyncio
async def test_self_dispatch_target_equals_source_allowed(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst1", payload=tany(nudge=True))
    drained = await dispatcher.flush("Inst1")
    assert len(drained) == 1
    assert drained[0]["payload"] == tany(nudge=True)


@pytest.mark.asyncio
async def test_conversation_id_inherited_across_multi_hop_chain(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(a=1))
    m1 = (await dispatcher.flush("Inst2"))[0]
    await dispatcher.dispatch(source="Inst2", target="Inst3", payload=tany(b=2), in_reply_to=m1["id"])
    m2 = (await dispatcher.flush("Inst3"))[0]
    await dispatcher.dispatch(source="Inst3", target="Inst1", payload=tany(c=3), in_reply_to=m2["id"])
    m3 = (await dispatcher.flush("Inst1"))[0]
    assert m1["conversation_id"] == m2["conversation_id"] == m3["conversation_id"]


@pytest.mark.asyncio
async def test_crossing_dispatch_without_conv_id_creates_distinct_ids(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1))
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(m=2))
    a = (await dispatcher.flush("Inst1"))[0]
    b = (await dispatcher.flush("Inst2"))[0]
    assert a["conversation_id"] != b["conversation_id"]


@pytest.mark.asyncio
async def test_explicit_same_conversation_id_merges_crossing_threads(setup):
    _, _, dispatcher = setup
    conv = "conv-shared-x"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1), conversation_id=conv)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(m=2), conversation_id=conv)
    a = (await dispatcher.flush("Inst1"))[0]
    b = (await dispatcher.flush("Inst2"))[0]
    assert a["conversation_id"] == conv == b["conversation_id"]


@pytest.mark.asyncio
async def test_closing_both_primary_sides_closes_conversation(setup):
    _, persistence, dispatcher = setup
    conv = "conv-close-1"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(bye=1), conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(bye=2), conversation_id=conv, closing=True)
    assert dispatcher.conversation_status(conv)["status"] == "closed"


@pytest.mark.asyncio
async def test_cc_participants_excluded_from_closed_by_count(setup):
    _, persistence, dispatcher = setup
    conv = "conv-cc-close"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(x=1), cc=["Inst3"], conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(x=2), conversation_id=conv, closing=True)
    assert dispatcher.conversation_status(conv)["status"] == "closed"


@pytest.mark.asyncio
async def test_last_message_at_updated_on_every_dispatch(setup):
    _, _, dispatcher = setup
    conv = "conv-msg-at"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1), conversation_id=conv)
    first = dispatcher.conversation_status(conv)["last_message_at"]
    await asyncio.sleep(0.02)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(m=2), conversation_id=conv)
    second = dispatcher.conversation_status(conv)["last_message_at"]
    assert second > first


@pytest.mark.asyncio
async def test_dispatch_to_closed_conversation_id_substituted_with_new_uuid(setup):
    _, _, dispatcher = setup
    conv = "conv-doomed"
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1), conversation_id=conv, closing=True)
    await dispatcher.dispatch(source="Inst2", target="Inst1", payload=tany(m=2), conversation_id=conv, closing=True)
    res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(m=3), conversation_id=conv)
    assert res["conversation_id"] != conv
    assert res["conversation_id_substituted"] is True


@pytest.mark.asyncio
async def test_broadcast_fans_out_to_all_others_with_single_conversation_id(setup):
    _, _, dispatcher = setup
    res = await dispatcher.broadcast(source="Inst1", payload=tany(announcement="hi"))
    received = []
    for i in range(2, 9):
        msgs = await dispatcher.flush(f"Inst{i}")
        if msgs:
            received.append(msgs[0]["conversation_id"])
    assert len(set(received)) == 1
    assert all(c == res["conversation_id"] for c in received)


@pytest.mark.asyncio
async def test_broadcast_announcement_closing_true_immediately_closes_conversation(setup):
    _, _, dispatcher = setup
    res = await dispatcher.broadcast(source="Inst1", payload=tany(end=True), closing=True)
    assert dispatcher.conversation_status(res["conversation_id"])["status"] == "closed"


@pytest.mark.asyncio
async def test_broadcast_message_count_increments_by_one_not_n(setup):
    _, _, dispatcher = setup
    res = await dispatcher.broadcast(source="Inst1", payload=tany(m=1))
    assert dispatcher.conversation_status(res["conversation_id"])["message_count"] == 1


@pytest.mark.asyncio
async def test_priority_string_enum_orders_high_before_normal_before_low(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(p="low"), priority="low")
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(p="normal"), priority="normal")
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(p="high"), priority="high")
    drained = await dispatcher.flush("Inst3", sort="priority")
    assert [c["payload"]["p"] for c in drained] == ["high", "normal", "low"]


@pytest.mark.asyncio
async def test_max_inbox_depth_dispatch_rejected_when_full(tmp_path):
    registry = InstanceRegistry()
    registry.register("s1", "Inst1")
    registry.register("s2", "Inst2")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                bot_registry=BotRegistry(),
                                comm_matrix=CommMatrix(),
                                default_timeout_ms=500, max_inbox_depth=3)
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(i=1))
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(i=2))
        await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(i=3))
        with pytest.raises(ValueError, match="inbox_full"):
            await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(i=4))


@pytest.mark.asyncio
async def test_cc_inbox_full_marked_skipped_full(tmp_path):
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"s{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                bot_registry=BotRegistry(),
                                comm_matrix=CommMatrix(),
                                default_timeout_ms=500, max_inbox_depth=2)
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(x=1))
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(x=2))
        res = await dispatcher.dispatch(
            source="Inst1", target="Inst2", payload=tany(x="primary"),
            cc=["Inst3", "Inst4"],
        )
        assert "Inst3" in res["skipped_full"]
        assert "Inst4" not in res["skipped_full"]
        assert any(d["instance_id"] == "Inst2" for d in res["dispatched_to"])


@pytest.mark.asyncio
async def test_in_flight_increments_on_expect_result_decrements_on_reply(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(a=1), expect_result=True)
    assert dispatcher.in_flight_count("Inst3") == 1
    msg = (await dispatcher.flush("Inst3"))[0]
    await dispatcher.dispatch(source="Inst3", target="Inst1", payload=tany(r=1), in_reply_to=msg["id"])
    assert dispatcher.in_flight_count("Inst3") == 0


@pytest.mark.asyncio
async def test_cc_recipients_excluded_from_in_flight_count(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(
        source="Inst1", target="Inst2", payload=tany(a=1),
        cc=["Inst3"], expect_result=True,
    )
    assert dispatcher.in_flight_count("Inst2") == 1
    assert dispatcher.in_flight_count("Inst3") == 0


@pytest.mark.asyncio
async def test_peek_returns_accurate_queue_depth_and_in_flight_count(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(a=1))
    await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(b=2), expect_result=True)
    meta = dispatcher.peek(["Inst3"])
    assert meta["Inst3"]["queue_depth"] == 2
    assert meta["Inst3"]["in_flight"] == 1


@pytest.mark.asyncio
async def test_peek_unregistered_target_returns_registered_false(setup):
    _, _, dispatcher = setup
    meta = dispatcher.peek(["Inst99"])
    assert meta["Inst99"]["registered"] is False
    assert meta["Inst99"]["queue_depth"] is None


@pytest.mark.asyncio
async def test_conversation_status_returns_participants_with_roles(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(
        source="Inst1", target="Inst2", payload=tany(m=1), cc=["Inst3"],
    )
    status = dispatcher.conversation_status(res["conversation_id"])
    parts = {p["instance_id"]: p["role"] for p in status["participants"]}
    assert parts["Inst1"] == "primary"
    assert parts["Inst2"] == "primary"
    assert parts["Inst3"] == "cc"
    assert status["kind"] == "direct"
    assert status["status"] == "open"


def test_conversation_status_returns_unknown_error_for_missing_id(tmp_path):
    import asyncio as _aio
    registry = InstanceRegistry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    # build dispatcher without async queue running (sync method test only)
    dispatcher = Dispatcher(registry, persistence, queue,
                            schema_registry=make_schema_registry(),
                            bot_registry=BotRegistry(),
                            comm_matrix=CommMatrix())
    status = dispatcher.conversation_status("conv-does-not-exist")
    assert status.get("error") == "unknown_conversation"


@pytest.mark.asyncio
async def test_conversations_list_filters_by_participant_and_status(setup):
    _, _, dispatcher = setup
    r1 = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(a=1))
    r2 = await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(b=2))
    listed = dispatcher.conversations_list(participant="Inst3", status="open")
    ids = {c["conversation_id"] for c in listed}
    assert r2["conversation_id"] in ids
    assert r1["conversation_id"] not in ids


@pytest.mark.asyncio
async def test_close_thread_idempotent_returns_already_closed_on_repeat(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1))
    first = await dispatcher.close_thread("Inst1", res["conversation_id"], reason="end")
    assert first["status"] in ("half_closed", "closed")
    second = await dispatcher.close_thread("Inst1", res["conversation_id"], reason="end")
    assert second["status"] in ("already_closed", first["status"])


@pytest.mark.asyncio
async def test_close_thread_caller_not_in_participants_raises(setup):
    _, _, dispatcher = setup
    res = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1))
    with pytest.raises(ValueError, match="not_a_participant"):
        await dispatcher.close_thread("Inst5", res["conversation_id"])


# ----------------------- M3 §15.4 boundary cases -----------------------

@pytest.mark.asyncio
async def test_broadcast_partial_inbox_full_dispatches_to_remaining_with_skipped_full_list(tmp_path):
    """Inst5 I2 — broadcast 일부 target만 full이면 나머지에는 정상, skipped_full에 명시."""
    registry = InstanceRegistry()
    for i in range(1, 5):
        registry.register(f"s{i}", f"Inst{i}")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                bot_registry=BotRegistry(),
                                comm_matrix=CommMatrix(),
                                max_inbox_depth=2)
        # fill Inst3's queue
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(x=1))
        await dispatcher.dispatch(source="Inst1", target="Inst3", payload=tany(x=2))
        res = await dispatcher.broadcast(source="Inst1", payload=tany(hi=True))
        # Inst3 was full → skipped; Inst2 and Inst4 received
        assert "Inst3" in res["skipped_full"]
        delivered = {d["instance_id"] for d in res["dispatched_to"]}
        assert "Inst2" in delivered
        assert "Inst4" in delivered
        assert "Inst3" not in delivered


@pytest.mark.asyncio
async def test_target_inbox_depth_after_reflects_actual_queue_state_post_dispatch(setup):
    _, _, dispatcher = setup
    res1 = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(i=1))
    assert res1["target_inbox_depth_after"]["Inst2"] == 1
    res2 = await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(i=2))
    assert res2["target_inbox_depth_after"]["Inst2"] == 2


@pytest.mark.asyncio
async def test_wait_age_ms_calculation_matches_now_minus_created_at(setup):
    _, _, dispatcher = setup
    await dispatcher.dispatch(source="Inst1", target="Inst2", payload=tany(m=1))
    await asyncio.sleep(0.05)  # let some time pass
    msgs = await dispatcher.flush("Inst2")
    assert len(msgs) == 1
    # wait_age_ms must be >= 50 (we slept 50ms) and within a generous upper bound
    assert msgs[0]["wait_age_ms"] >= 40
    assert msgs[0]["wait_age_ms"] < 2000


@pytest.mark.asyncio
async def test_broadcast_with_zero_other_registered_instances_returns_empty_dispatched_to(tmp_path):
    """Spec §12 — broadcast 호출자만 등록되어 있어도 에러 없이 빈 결과."""
    registry = InstanceRegistry()
    registry.register("s1", "Inst1")
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        dispatcher = Dispatcher(registry, persistence, queue,
                                schema_registry=make_schema_registry(),
                                bot_registry=BotRegistry(),
                                comm_matrix=CommMatrix())
        res = await dispatcher.broadcast(source="Inst1", payload=tany(hi=True))
        assert res["dispatched_to"] == []
        assert "conversation_id" in res


def _make_dispatcher(registry, persistence, queue):
    return Dispatcher(
        registry, persistence, queue,
        schema_registry=make_schema_registry(),
        bot_registry=BotRegistry(),
        comm_matrix=CommMatrix(),
    )


@pytest.mark.asyncio
async def test_drop_inflight_on_restart_marks_all_undrained_and_restore_finds_nothing(tmp_path):
    """drop_inflight_on_restart() 후 동일 DB로 restore_from_persistence()를 해도
    _queues에 복원될 메시지가 없어야 한다 — 클린 스타트 검증."""
    db_path = tmp_path / "agora.db"
    registry = InstanceRegistry()
    registry.register("s1", "Inst1")
    registry.register("s2", "Inst2")

    # ── 1. 최초 Dispatcher: 메시지 dispatch → undrained 행 생성 ──────────────
    persistence1 = Persistence(db_path)
    persistence1.migrate()
    queue1 = AsyncWriteQueue(persistence1)
    async with queue1:
        dispatcher1 = _make_dispatcher(registry, persistence1, queue1)
        await dispatcher1.dispatch(source="Inst1", target="Inst2", payload=tany(m="hello"))
    # queue1 컨텍스트 종료 → 백그라운드 쓰기 완료 보장

    # ── 2. 재시작 시뮬레이션: 새 Dispatcher + drop_inflight_on_restart() ─────
    persistence2 = Persistence(db_path)
    queue2 = AsyncWriteQueue(persistence2)
    async with queue2:
        dispatcher2 = _make_dispatcher(registry, persistence2, queue2)
        dispatcher2.drop_inflight_on_restart()

    # ── 3. 또 다른 새 Dispatcher + restore_from_persistence() → 큐가 비어야 함 ─
    persistence3 = Persistence(db_path)
    queue3 = AsyncWriteQueue(persistence3)
    async with queue3:
        dispatcher3 = _make_dispatcher(registry, persistence3, queue3)
        dispatcher3.restore_from_persistence()
        # _queues는 collections.defaultdict(deque) — "Inst2" 큐가 비어 있어야 함
        assert len(dispatcher3._queues["Inst2"]) == 0


# ----------------------- _fmt_payload tests -----------------------

from agent_agora.dispatcher import _fmt_payload


def test_fmt_payload_is_pretty_printed():
    out = _fmt_payload({"msgtype": "x", "from": "A", "n": 1})
    assert "\n" in out                       # 멀티라인 (indent)
    assert '"msgtype": "x"' in out            # ": " 구분자 — 압축 아님
    assert '"n": 1' in out


def test_fmt_payload_non_serializable_falls_back_to_repr():
    out = _fmt_payload(object())              # JSON 직렬화 불가
    assert "object" in out                    # repr fallback


@pytest.mark.asyncio
async def test_system_notify_enqueues_and_wakes(setup):
    _, _, dispatcher = setup
    await dispatcher.system_notify("Inst3", {
        "msgtype": "schema_conflict", "schema_name": "s",
        "reason": "different body", "ts": "2026-05-17T00:00:00+00:00"})
    drained = await dispatcher.flush("Inst3")
    assert len(drained) == 1
    assert drained[0]["payload"]["msgtype"] == "schema_conflict"
    assert drained[0]["source"] == "agora-system"
