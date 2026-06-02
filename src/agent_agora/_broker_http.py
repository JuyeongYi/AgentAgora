"""Shared HTTP-client glue for talking to the broker's GET /channel/wait endpoint.

Used by both the agora-channel adapter (channel_adapter.py) and the AgoraBot SDK
(bot.py). Previously this logic was duplicated in both; it now lives here and the
two callers delegate (keeping their historical private symbols as thin wrappers).
"""
from __future__ import annotations

import json

import httpx


def result_to_json(result) -> dict:
    """Extract the first JSON object from a tool-call result's text content.

    Returns the first text content item that parses as a JSON dict, else {}.
    Defensive against a missing/None `content` attribute.
    """
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def channel_wait_base_url(broker_mcp_url: str) -> str:
    """Derive the base URL for the channel endpoints from a broker MCP URL.

    The broker MCP endpoint is http://host:port/mcp; /channel/wait is a sibling
    path on the same host:port — strip the trailing /mcp.
    """
    url = broker_mcp_url.rstrip("/")
    if url.endswith("/mcp"):
        url = url[: -len("/mcp")]
    return url.rstrip("/")


def channel_wait_url(broker_mcp_url: str) -> str:
    """Full GET /channel/wait URL derived from a broker MCP URL."""
    return channel_wait_base_url(broker_mcp_url) + "/channel/wait"


async def http_wait_notify(wait_url: str, instance_id: str, timeout_ms: int) -> dict:
    """Long-poll GET /channel/wait for inbox arrival.

    Replaces the blocking agora.wait_notify MCP tool with an HTTP path that does
    not pollute a worker's tool surface. On any failure returns {"error": ...}
    rather than raising — the caller treats an error dict as a backoff signal.
    """
    try:
        async with httpx.AsyncClient(timeout=None) as http:
            resp = await http.get(
                wait_url,
                params={"instance_id": instance_id, "timeout_ms": timeout_ms})
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001 — connection failure is a backoff signal
        return {"error": f"channel/wait HTTP 호출 실패: {exc!r}"}
