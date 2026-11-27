"""ASGI app for the streaming chat agent (Lambda Web Adapter).

CloudFront posts to /api/chat. The adapter converts Function URL events into
HTTP and streams SSE back with RESPONSE_STREAM invoke mode.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from potty_agent.agent import open_agent
from potty_agent.stream import iter_chat_events, sse

logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)


async def health(_request: Request) -> Response:
    return JSONResponse({"ok": True})


async def chat(request: Request) -> Response:
    try:
        if not _origin_ok(request):
            return JSONResponse({"error": "Forbidden."}, status_code=403)
        if not await _authorized(request):
            return JSONResponse({"error": "Sign in again."}, status_code=401)

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Request body must be JSON."}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request body must be an object."}, status_code=400)

        message = str(payload.get("message") or "").strip()
        if not message:
            return JSONResponse({"error": "Say something for the assistant."}, status_code=400)
        if len(message) > 4000:
            return JSONResponse({"error": "That message is too long."}, status_code=400)

        history = payload.get("history")
        prompt = _prompt_with_history(message, history)

        async def generate():
            try:
                with open_agent() as agent:
                    async for chunk in iter_chat_events(agent, prompt):
                        yield chunk
            except RuntimeError as exc:
                yield sse({"type": "error", "message": str(exc)})
                yield sse({"type": "done"})
            except Exception:
                logger.exception("Chat stream failed.")
                yield sse({"type": "error", "message": "The assistant failed."})
                yield sse({"type": "done"})

        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }
        origin = os.environ.get("CORS_ORIGIN", "")
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-Potty-Authorization, X-Potty-Session, X-Potty-Origin"
            )
            headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)
    except Exception:
        logger.exception("Chat request failed before streaming.")
        return JSONResponse({"error": "The assistant is unavailable."}, status_code=500)


async def options_chat(request: Request) -> Response:
    headers = {
        "Access-Control-Allow-Origin": os.environ.get("CORS_ORIGIN", "*"),
        "Access-Control-Allow-Headers": (
            "Authorization, Content-Type, X-Potty-Authorization, X-Potty-Session, X-Potty-Origin"
        ),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    }
    return Response(status_code=204, headers=headers)


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


def _origin_ok(request: Request) -> bool:
    if os.environ.get("POTTY_ENV") == "local":
        return True
    expected = os.environ.get("POTTY_ORIGIN_SECRET", "")
    got = request.headers.get("x-potty-origin", "")
    if not expected or len(got) != len(expected):
        return False
    import hmac

    return hmac.compare_digest(got, expected)


async def _authorized(request: Request) -> bool:
    try:
        from potty_train.auth import token_is_valid, token_username
        from potty_train.sessions import owns, touch
    except Exception:
        logger.exception("Chat auth imports failed.")
        raise

    header = request.headers.get("x-potty-authorization") or request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return False
    token = header.split(" ", 1)[1].strip()
    if not token_is_valid(token):
        return False
    username = token_username(token)
    session_id = (request.headers.get("x-potty-session") or "").strip()
    if not username or not session_id:
        return False
    try:
        if not owns(session_id, username):
            return False
    except Exception:
        logger.exception("Chat session lookup failed.")
        raise
    try:
        touch(session_id)
    except Exception:
        pass
    return True


routes = [
    Route("/", health, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/chat", options_chat, methods=["OPTIONS"]),
]

app = Starlette(routes=routes)
