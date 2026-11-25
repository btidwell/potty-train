"""Cognito access-token checks.

Sign-up, email codes, password reset, and authenticator setup happen in the
browser against the user pool. The API only checks the access token. A
session lasts seven days from login because the app client's refresh token
is valid for that long. The access token itself is short-lived; the browser
refreshes it until the refresh token expires.
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from jwt import PyJWKClient

SESSION_DAYS = 7

_JWKS: dict[str, Any] = {}


def auth_config() -> dict[str, Any]:
    region = os.environ.get("COGNITO_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    client_id = os.environ.get("COGNITO_CLIENT_ID", "")
    if not pool_id or not client_id:
        raise RuntimeError("Cognito user pool is not configured.")
    return {
        "userPoolId": pool_id,
        "userPoolClientId": client_id,
        "region": region,
        "sessionDays": SESSION_DAYS,
    }


def token_is_valid(token: str) -> bool:
    return _verified(token) is not None


def is_owner(token: str) -> bool:
    claims = _verified(token)
    if not claims:
        return False
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return isinstance(groups, list) and "owners" in groups


def token_username(token: str) -> str:
    claims = _verified(token)
    if not claims:
        return ""
    return str(claims.get("username") or claims.get("sub") or "")


def _verified(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        claims = _claims(token)
    except (jwt.InvalidTokenError, RuntimeError, ValueError):
        return None
    config = auth_config()
    if claims.get("token_use") != "access" or claims.get("client_id") != config["userPoolClientId"]:
        return None
    return claims


def _claims(token: str) -> dict[str, Any]:
    config = auth_config()
    issuer = f"https://cognito-idp.{config['region']}.amazonaws.com/{config['userPoolId']}"
    signing_key = _jwks().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        options={
            "verify_aud": False,
            "require": ["exp", "iss", "token_use"],
        },
    )
    if not isinstance(claims, dict):
        raise jwt.InvalidTokenError("Token claims are not an object.")
    return claims


def _jwks() -> PyJWKClient:
    config = auth_config()
    url = (
        f"https://cognito-idp.{config['region']}.amazonaws.com/"
        f"{config['userPoolId']}/.well-known/jwks.json"
    )
    client = _JWKS.get("client")
    if client is None or _JWKS.get("url") != url:
        client = PyJWKClient(url, cache_keys=True, lifespan=3600)
        _JWKS["client"] = client
        _JWKS["url"] = url
    return client
