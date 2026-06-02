"""v4 테스트 공용 헬퍼 — payload 빌더 + registry 팩토리."""
from agent_agora.storage.schemas import SchemaRegistry, load_schemas_into, BUNDLED_DEFAULT_SCHEMAS

# 기존 v3 테스트가 임의 dict payload를 보내던 것을 흡수하는 느슨한 테스트 schema.
TEST_ANY_BODY = {
    "type": "object",
    "required": ["msgtype"],
    "properties": {"msgtype": {"type": "string", "const": "test_any"}},
    "additionalProperties": True,
}


def make_schema_registry() -> SchemaRegistry:
    """기본 schema 6종 + test_any가 등록된 SchemaRegistry."""
    reg = SchemaRegistry()
    load_schemas_into(reg, BUNDLED_DEFAULT_SCHEMAS)
    reg.register("test_any", TEST_ANY_BODY, kind="conversation",
                 purpose="테스트 전용 느슨한 schema")
    return reg


def tany(**fields) -> dict:
    """test_any payload 헬퍼. 기존 임의 dict payload 자리에 쓴다."""
    return {"msgtype": "test_any", **fields}


def wf(message: str = "hi", type_: str = "task", **extra) -> dict:
    """worker_freeform payload 헬퍼."""
    return {
        "msgtype": "worker_freeform", "type": type_,
        "from": "tester", "ts": "2026-01-01T00:00:00Z",
        "message": message, **extra,
    }


def get_tool(mcp, name):
    """Return the bare function behind a registered FastMCP tool (the single
    touch-point for mcp._tool_manager)."""
    return mcp._tool_manager.get_tool(name).fn


class FakeCtx:
    """Minimal MCP Context stub exposing
    request_context.request.headers['mcp-session-id'] — what
    server._session_id_from_ctx reads. Replaces the per-file _FakeCtx copies."""

    def __init__(self, session_id):
        self.request_context = type("RC", (), {"request": type("R", (), {
            "headers": {"mcp-session-id": session_id}})()})()
