"""SSE mapping for agent stream events."""

from __future__ import annotations

import json

from potty_agent.stream import _normalize, sse


def test_sse_format():
    raw = sse({"type": "text", "text": "hi"})
    assert raw.startswith(b"data: ")
    assert raw.endswith(b"\n\n")
    payload = json.loads(raw.decode("utf-8").removeprefix("data: ").strip())
    assert payload == {"type": "text", "text": "hi"}


def test_normalize_thought_text_and_tool():
    events = _normalize(
        {
            "reasoningText": "Checking the timer.",
            "data": "The timer is running.",
            "current_tool_use": {"name": "get_schedule", "input": {}, "toolUseId": "1"},
        }
    )
    assert events[0] == {"type": "thought", "text": "Checking the timer."}
    assert events[1] == {"type": "text", "text": "The timer is running."}
    assert events[2]["type"] == "tool"
    assert events[2]["name"] == "get_schedule"


def test_normalize_ignores_unknown():
    assert _normalize({"noop": True}) == []
    assert _normalize("x") == []
