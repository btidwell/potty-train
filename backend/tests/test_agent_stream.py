"""SSE mapping for agent stream events."""

from __future__ import annotations

import json
from pathlib import Path

from potty_agent.stream import _normalize, sse

ROOT = Path(__file__).resolve().parents[2]


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


def test_agent_package_ships_jwt_for_chat_auth():
    """Every /api/chat call imports potty_train.auth, which needs PyJWT in the zip."""
    requirements = (ROOT / "backend" / "requirements-agent.txt").read_text(encoding="utf-8")
    assert "PyJWT" in requirements
    from potty_train.auth import token_is_valid
    from potty_train.sessions import owns

    assert callable(token_is_valid)
    assert callable(owns)
