"""Password check and HMAC-signed bearer tokens.

The password and the token signing key live in Secrets Manager in production
({ "password": "...", "token_key": "..." }) and in environment variables when
running locally. Tokens are HMAC-signed so the Lambda does not need a session
table.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

_CACHE: dict[str, Any] = {"loaded_at": 0.0, "secret": None}


def passwords_match(provided: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(provided.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


# A personal device stays signed in across closing the app. Fourteen hours
# made the same person type the password again every morning.
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60


def issue_token(signing_key: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    payload = _b64(json.dumps({"exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(signing_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def token_is_valid(signing_key: str, token: str) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.split(".", 1)
    expected = hmac.new(signing_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    try:
        data = json.loads(_b64decode(payload))
        return int(data["exp"]) >= int(time.time())
    except (ValueError, KeyError, json.JSONDecodeError):
        return False


def load_secret() -> dict[str, str]:
    now = time.time()
    cached = _CACHE["secret"]
    if cached and now - float(_CACHE["loaded_at"]) < 60:
        return cached
    if os.environ.get("POTTY_ENV") == "local":
        secret = {
            "password": os.environ.get("POTTY_LOCAL_PASSWORD", ""),
            "token_key": os.environ.get("POTTY_LOCAL_TOKEN_KEY", "local-dev-token-key"),
        }
    else:
        secret = _load_from_secrets_manager()
    if not secret.get("password") or not secret.get("token_key"):
        raise RuntimeError("App secret is missing a password or token key.")
    _CACHE["secret"] = secret
    _CACHE["loaded_at"] = now
    return secret


def _load_from_secrets_manager() -> dict[str, str]:
    import boto3

    client = boto3.client("secretsmanager")
    password = _secret_string(client, os.environ["APP_PASSWORD_SECRET_ARN"])
    token_key = _secret_string(client, os.environ["APP_TOKEN_SECRET_ARN"])
    return {"password": password, "token_key": token_key}


def _secret_string(client: Any, arn: str) -> str:
    response = client.get_secret_value(SecretId=arn)
    value = str(response.get("SecretString") or "").strip()
    if not value:
        raise RuntimeError("App secret is empty.")
    if value.startswith("{"):
        parsed = json.loads(value)
        if isinstance(parsed, dict) and parsed.get("password"):
            return str(parsed["password"])
    return value


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
