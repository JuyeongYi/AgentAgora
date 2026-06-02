"""dispatcher.py event hook 등록·발화·예외 안전 검증."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from agent_agora.dispatcher import Dispatcher
from agent_agora.registry import InstanceRegistry, InstanceInfo
from agent_agora.persistence import Persistence, AsyncWriteQueue
from agent_agora.bot_registry import BotRegistry
from agent_agora.comm_matrix import CommMatrix
from agent_agora.envelope import make_envelope
from _helpers import make_schema_registry, tany


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_envelope(recipient: str):
    """테스트용 Envelope 헬퍼 — dispatch hook 발화 테스트에서 사용."""
    return make_envelope(
        cmd_id=str(uuid.uuid4()),
        source="Source1",
        target=recipient,
        payload=tany(text="hello"),
        created_at="2026-01-01T00:00:00Z",
        conversation_id=str(uuid.uuid4()),
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def instance_registry():
    reg = InstanceRegistry()
    reg.register("sess-1", "Worker1")
    reg.register("sess-2", "Worker2")
    return reg


@pytest_asyncio.fixture
async def dispatcher_fixture(tmp_path, instance_registry):
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    async with queue:
        d = Dispatcher(
            instance_registry,
            persistence,
            queue,
            schema_registry=make_schema_registry(),
            bot_registry=BotRegistry(),
            comm_matrix=CommMatrix(),
            default_timeout_ms=500,
        )
        yield d


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_hook_called(dispatcher_fixture, instance_registry):
    """dispatch 발생 시 on_dispatch hook이 envelope과 함께 호출된다."""
    captured: list = []
    dispatcher_fixture.register_dispatch_hook(lambda env: captured.append(env))

    await dispatcher_fixture.dispatch(
        source="Worker1",
        target="Worker2",
        payload=tany(text="hello"),
    )

    assert len(captured) == 1
    assert captured[0].target == "Worker2"


@pytest.mark.asyncio
async def test_register_hook_called(dispatcher_fixture, instance_registry):
    """register hook 등록 후 _fire_register_hooks를 직접 호출하면 hook이 실행된다."""
    captured: list = []
    dispatcher_fixture.register_register_hook(lambda info: captured.append(info))

    # InstanceRegistry는 Dispatcher hooks를 직접 발화하지 않는다.
    # Task 9에서 wiring이 추가될 때까지, 인프라가 동작하는지 _fire_register_hooks로 검증.
    fake_info = InstanceInfo(
        instance_id="W1",
        session_id="s1",
        role="coder",
        registered_at="2026-01-01T00:00:00Z",
        description="d",
    )
    dispatcher_fixture._fire_register_hooks(fake_info)

    assert len(captured) == 1
    assert captured[0].instance_id == "W1"


@pytest.mark.asyncio
async def test_hook_exception_does_not_break_dispatch(dispatcher_fixture, instance_registry):
    """hook이 raise해도 dispatch 본 로직은 진행된다."""
    def bad(env):
        raise RuntimeError("boom")

    dispatcher_fixture.register_dispatch_hook(bad)

    # 예외 swallow + dispatch는 성공해야 한다
    result = await dispatcher_fixture.dispatch(
        source="Worker1",
        target="Worker2",
        payload=tany(text="hello"),
    )
    assert result is not None
    assert "command_id" in result


@pytest.mark.asyncio
async def test_unregister_hook_fires(dispatcher_fixture):
    """_fire_unregister_hooks 인프라가 등록된 callback을 실행한다."""
    captured: list = []
    dispatcher_fixture.register_unregister_hook(lambda iid: captured.append(iid))

    dispatcher_fixture._fire_unregister_hooks("Worker1")

    assert captured == ["Worker1"]


@pytest.mark.asyncio
async def test_notify_registered_delegates_to_register_hooks(dispatcher_fixture):
    """공개 notify_registered(server/auto_register 경로)가 register hook을 발화한다."""
    captured: list = []
    dispatcher_fixture.register_register_hook(lambda info: captured.append(info))
    info = InstanceInfo(instance_id="W9", session_id="s9", role="coder",
                        registered_at="2026-01-01T00:00:00Z", description="d")
    dispatcher_fixture.notify_registered(info)
    assert [i.instance_id for i in captured] == ["W9"]


@pytest.mark.asyncio
async def test_notify_unregistered_delegates_to_unregister_hooks(dispatcher_fixture):
    """공개 notify_unregistered(server/sweeper dead_session 경로)가 unregister hook을 발화한다."""
    captured: list = []
    dispatcher_fixture.register_unregister_hook(lambda iid: captured.append(iid))
    dispatcher_fixture.notify_unregistered("W9")
    assert captured == ["W9"]


@pytest.mark.asyncio
async def test_multiple_dispatch_hooks_all_called(dispatcher_fixture, instance_registry):
    """여러 hook이 등록된 경우 모두 호출된다."""
    calls_a: list = []
    calls_b: list = []
    dispatcher_fixture.register_dispatch_hook(lambda env: calls_a.append(env))
    dispatcher_fixture.register_dispatch_hook(lambda env: calls_b.append(env))

    await dispatcher_fixture.dispatch(
        source="Worker1",
        target="Worker2",
        payload=tany(text="hello"),
    )

    assert len(calls_a) == 1
    assert len(calls_b) == 1


@pytest.mark.asyncio
async def test_hook_exception_mid_chain_continues(dispatcher_fixture, instance_registry):
    """첫 번째 hook이 raise해도 두 번째 hook은 호출된다."""
    calls: list = []

    def bad(env):
        raise ValueError("first hook fails")

    dispatcher_fixture.register_dispatch_hook(bad)
    dispatcher_fixture.register_dispatch_hook(lambda env: calls.append(env))

    await dispatcher_fixture.dispatch(
        source="Worker1",
        target="Worker2",
        payload=tany(text="hello"),
    )

    assert len(calls) == 1
