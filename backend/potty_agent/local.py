"""Stream a chat turn for the local ThreadingHTTPServer."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any

from potty_agent.agent import open_agent
from potty_agent.auth import authorized, body_json, from_cloudfront, session_allows
from potty_agent.stream import iter_chat_events, sse

logger = logging.getLogger(__name__)


def handle_chat_event(event: dict[str, Any]) -> dict[str, Any] | Iterator[bytes]:
    """Return either a normal API response dict or a live SSE byte iterator."""
    if not from_cloudfront(event):
        return _json(403, {"error": "Forbidden."})
    method = str(event.get("httpMethod") or "POST").upper()
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": _headers(), "body": ""}
    if not authorized(event) or not session_allows(event):
        return _json(401, {"error": "Sign in again."})
    try:
        payload = body_json(event)
    except (json.JSONDecodeError, ValueError):
        return _json(400, {"error": "Request body must be JSON."})
    message = str(payload.get("message") or "").strip()
    if not message:
        return _json(400, {"error": "Say something for the assistant."})
    if len(message) > 4000:
        return _json(400, {"error": "That message is too long."})
    prompt = _prompt_with_history(message, payload.get("history"))
    return _live_stream(prompt)


def _live_stream(prompt: str) -> Iterator[bytes]:
    chunks: queue.Queue[bytes | None] = queue.Queue()

    def runner() -> None:
        async def run() -> None:
            try:
                with open_agent() as agent:
                    async for chunk in iter_chat_events(agent, prompt):
                        chunks.put(chunk)
            except RuntimeError as exc:
                chunks.put(sse({"type": "error", "message": str(exc)}))
                chunks.put(sse({"type": "done"}))
            except Exception:
                logger.exception("Local chat stream failed.")
                chunks.put(sse({"type": "error", "message": "The assistant failed."}))
                chunks.put(sse({"type": "done"}))
            finally:
                chunks.put(None)

        asyncio.run(run())

    threading.Thread(target=runner, daemon=True).start()
    while True:
        item = chunks.get()
        if item is None:
            break
        yield item


def _prompt_with_history(message: str, history: Any) -> str:
    if not isinstance(history, list) or not history:
        return message
    lines: list[str] = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        text = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not text:
            continue
        lines.append(f"{role}: {text[:1500]}")
    if not lines:
        return message
    return "Conversation so far:\n" + "\n".join(lines) + f"\nuser: {message}\nassistant:"


def _json(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": _headers(), "body": json.dumps(body)}


def _headers() -> dict[str, str]:
    import os

    origin = os.environ.get("CORS_ORIGIN", "")
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, X-Potty-Authorization, X-Potty-Session"
        )
        headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return headers
