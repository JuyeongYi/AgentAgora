"""서버 MCP transport security — 신뢰망(--no-tls·무인증) 전용이라 DNS rebinding
protection을 꺼서 LAN Host가 421 Misdirected Request로 막히지 않게 한다(분산 셋업)."""
from agent_agora.comm_matrix import CommMatrix
from agent_agora.server import create_agora_app
from agent_agora.registry import InstanceRegistry, BotRegistry
from agent_agora.dispatcher import Dispatcher
from agent_agora.storage.persistence import Persistence, AsyncWriteQueue
from _helpers import make_schema_registry


def test_dns_rebinding_protection_disabled(tmp_path):
    instance_registry = InstanceRegistry()
    bot_registry = BotRegistry()
    schema_registry = make_schema_registry()
    persistence = Persistence(tmp_path / "agora.db")
    persistence.migrate()
    queue = AsyncWriteQueue(persistence)
    comm_matrix = CommMatrix()
    dispatcher = Dispatcher(
        instance_registry, persistence, queue,
        schema_registry=schema_registry, bot_registry=bot_registry,
        comm_matrix=comm_matrix)
    mcp = create_agora_app(
        agora_dir=tmp_path, instance_registry=instance_registry,
        schema_registry=schema_registry, bot_registry=bot_registry,
        comm_matrix=comm_matrix, persistence=persistence,
        dispatcher=dispatcher, port=0)
    ts = mcp.settings.transport_security
    assert ts is not None
    # LAN의 다른 PC(비-localhost Host)가 접속해도 거부되지 않아야 한다.
    assert ts.enable_dns_rebinding_protection is False
