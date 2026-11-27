"""Map Strands stream events to SSE payloads for the chat UI."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any


def sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, default=str)}\n\n".encode("utf-8")


async def iter_chat_events(agent: Any, prompt: str) -> AsyncIterator[bytes]:
    """Yield SSE chunks for thoughts, text, and tool activity."""
    try:
        async for raw in agent.stream_async(prompt):
            for event in _normalize(raw):
                yield sse(event)
        yield sse({"type": "done"})
    except Exception as exc:
        yield sse({"type": "error", "message": str(exc) or "The assistant failed."})
        yield sse({"type": "done"})


def _normalize(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return []
    events: list[dict[str, Any]] = []

    reasoning = raw.get("reasoningText")
    if isinstance(reasoning, str) and reasoning:
        events.append({"type": "thought", "text": reasoning})

    data = raw.get("data")
    if isinstance(data, str) and data:
        events.append({"type": "text", "text": data})

    tool = raw.get("current_tool_use")
    if isinstance(tool, Mapping) and tool.get("name"):
        events.append(
            {
                "type": "tool",
                "name": str(tool.get("name")),
                "input": tool.get("input") or {},
                "toolUseId": tool.get("toolUseId") or "",
            }
        )

    # Some Strands versions surface tool results under tool_stream_event.
    tool_stream = raw.get("tool_stream_event")
    if isinstance(tool_stream, Mapping):
        result = tool_stream.get("data")
        name = str(tool_stream.get("tool_name") or tool_stream.get("name") or "tool")
        if result is not None:
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            events.append({"type": "tool_result", "name": name, "result": text[:4000]})

    return events
