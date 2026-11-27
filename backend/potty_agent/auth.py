"""Reuse the main API auth checks for the chat agent."""

from __future__ import annotations

import hmac
import os
from typing import Any

from potty_train.auth import token_is_valid, token_username
from potty_train.sessions import owns, touch


def from_cloudfront(event: dict[str, Any]) -> bool:
    if os.environ.get("POTTY_ENV") == "local":
        return True
    expected = os.environ.get("POTTY_ORIGIN_SECRET", "")
    got = headers_in(event).get("x-potty-origin", "")
    if not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def authorized(event: dict[str, Any]) -> bool:
    return token_is_valid(bearer(event))


def session_allows(event: dict[str, Any]) -> bool:
    username = token_username(bearer(event))
    session_id = headers_in(event).get("x-potty-session", "").strip()
    if not username or not session_id or not owns(session_id, username):
        return False
    try:
        touch(session_id)
    except Exception:
        pass
    return True


def bearer(event: dict[str, Any]) -> str:
    headers = headers_in(event)
    header = headers.get("x-potty-authorization") or headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def headers_in(event: dict[str, Any]) -> dict[str, str]:
    headers = event.get("headers") or {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def method_of(event: dict[str, Any]) -> str:
    return str(
        event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or ""
    ).upper()


def path_of(event: dict[str, Any]) -> str:
    raw = str(event.get("rawPath") or event.get("path") or "/")
    if raw.endswith("/") and raw != "/":
        raw = raw[:-1]
    return raw


def body_json(event: dict[str, Any]) -> dict[str, Any]:
    import base64
    import json

    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and isinstance(raw, str):
        raw = base64.b64decode(raw).decode("utf-8")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be an object.")
    return parsed
