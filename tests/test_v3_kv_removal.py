# tests/test_v3_kv_removal.py
"""v3 M0 regression tests — Agora KV removal.

These tests pin the M0-end behavior:

1. The FastMCP app must NOT register the legacy v1 KV tools
   (agora.set / agora.get / agora.append / agora.delete / agora.list).
   v3 also drops agora.list because its primary purpose was KV key listing —
   instance enumeration uses agora.instances.

2. Presence of a legacy `.agentagora/schemas.json` on disk must NOT crash
   server startup; the file is ignored and a warning is emitted to stderr.

Both tests target the post-Task-6 entry point `_build_app`, which is added
to `agent_agora.__main__` in M0 Task 6 to centralize app construction (and
to give tests a stable handle on app wiring without going through the full
CLI). The helper does not exist yet — these tests are expected to fail in
the **red phase** of TDD and will go green after Tasks 5-7.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_LEGACY_KV_TOOL_NAMES = frozenset({
    "agora.set",
    "agora.get",
    "agora.append",
    "agora.delete",
    "agora.list",
})


def _import_build_app():
    """Import the M0-end app factory. Will ImportError until Task 6 lands."""
    from agent_agora.__main__ import _build_app  # type: ignore[attr-defined]
    return _build_app


def test_v1_kv_tools_removed(tmp_path: Path) -> None:
    """The v3 FastMCP app must not advertise any legacy KV tool.

    Red-phase expectation: this fails with ImportError because
    `agent_agora.__main__._build_app` does not exist yet (Task 6 introduces it).

    After M0 is complete, it should pass: KV tools are removed from server.py
    in Task 5, and _build_app exposes the same FastMCP instance.
    """
    build_app = _import_build_app()
    app = build_app(agora_dir=tmp_path, port=0, no_tls=True)
    # _build_app may return either the FastMCP directly or a (FastMCP, ...) tuple
    # depending on how Task 6 shapes the helper. Tolerate both — what we care
    # about is the FastMCP's registered tool names.
    mcp = app[0] if isinstance(app, tuple) else app
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    leaked = tool_names & _LEGACY_KV_TOOL_NAMES
    assert not leaked, (
        f"v3 must not expose KV tools, but found: {sorted(leaked)}. "
        f"All advertised tools: {sorted(tool_names)}"
    )


def test_legacy_schemas_json_present_warned_but_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A leftover `.agentagora/schemas.json` from a v1 install must not crash startup.

    Acceptance:
        - _build_app constructs successfully (no exception)
        - a warning containing the substring "schemas.json" is written to stderr

    Red-phase: fails with ImportError until Task 6 adds _build_app, and the
    schemas.json detection / warning logic is added in Task 7 (alongside
    schema.py / store.py deletion).
    """
    build_app = _import_build_app()

    agora_dir = tmp_path / ".agentagora"
    agora_dir.mkdir()
    (agora_dir / "schemas.json").write_text('{"legacy": {"type": "string"}}')

    app = build_app(agora_dir=agora_dir, port=0, no_tls=True)
    assert app is not None, "_build_app must return a non-None app object"

    captured = capsys.readouterr()
    assert "schemas.json" in captured.err, (
        f"Expected a stderr warning mentioning 'schemas.json', got: {captured.err!r}"
    )
