"""Load the single aggregated Secrets Manager secret.

All app secrets live under one ARN as JSON key/value pairs:

- password
- token_key
- vapid_private_pem
- vapid_public_pem
- xai_api_key

Values are cached briefly so chat and push paths do not call Secrets Manager
on every request.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] = {"loaded_at": 0.0, "values": None}
_CACHE_SECONDS = 60.0


def app_secret(key: str, default: str = "") -> str:
    values = load_app_secrets()
    raw = values.get(key)
    if raw is None:
        return default
    return str(raw)


def load_app_secrets() -> dict[str, str]:
    now = time.time()
    cached = _CACHE["values"]
    if cached is not None and now - float(_CACHE["loaded_at"]) < _CACHE_SECONDS:
        return cached

    values = _load_app_secrets()
    _CACHE["values"] = values
    _CACHE["loaded_at"] = now
    return values


def clear_secret_cache() -> None:
    _CACHE["values"] = None
    _CACHE["loaded_at"] = 0.0


def _load_app_secrets() -> dict[str, str]:
    # Local overrides for smoke tests without AWS.
    inline = {
        "password": os.environ.get("POTTY_SECRET_PASSWORD", ""),
        "token_key": os.environ.get("POTTY_SECRET_TOKEN_KEY", ""),
        "vapid_private_pem": os.environ.get("POTTY_VAPID_PRIVATE_PEM", ""),
        "vapid_public_pem": os.environ.get("POTTY_VAPID_PUBLIC_PEM", ""),
        "xai_api_key": os.environ.get("XAI_API_KEY", ""),
    }
    if any(inline.values()) and os.environ.get("POTTY_ENV") == "local":
        return {key: value for key, value in inline.items() if value}

    arn = os.environ.get("APP_SECRET_ARN", "").strip()
    if not arn:
        if os.environ.get("POTTY_ENV") == "local":
            return {key: value for key, value in inline.items() if value}
        return {}

    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
    parsed = json.loads(str(response.get("SecretString") or "{}"))
    if not isinstance(parsed, dict):
        raise RuntimeError("App secret must be a JSON object of key/value pairs.")
    out: dict[str, str] = {}
    for key, value in parsed.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            out[str(key)] = json.dumps(value)
        else:
            out[str(key)] = str(value)
    # Env overrides win for a single key (useful when wiring a new key before
    # the aggregated secret is updated).
    for key, value in inline.items():
        if value:
            out[key] = value
    return out
