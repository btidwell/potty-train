"""Invitations for people who do not have an account yet.

Public sign-up is off. The owner asks Cognito to create the user, and Cognito
emails a temporary password. The invited person signs in with that password,
chooses their own, and sets up an authenticator.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EXISTS = {"UsernameExistsException", "AliasExistsException"}


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL.fullmatch(email) or len(email) > 254:
        raise ValueError("Enter an email address.")
    return email


def send_invite(email: str, client: Any | None = None) -> str:
    email = normalize_email(email)
    if client is None:
        import boto3

        client = boto3.client(
            "cognito-idp",
            region_name=os.environ.get("COGNITO_REGION") or os.environ.get("AWS_REGION"),
        )
    pool_id = os.environ["COGNITO_USER_POOL_ID"]
    try:
        client.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            DesiredDeliveryMediums=["EMAIL"],
            UserAttributes=_attributes(email),
        )
    except Exception as exc:
        if _code(exc) not in _EXISTS:
            if _code(exc):
                logger.exception("Could not create invited user")
                raise RuntimeError("Could not send the invitation.") from exc
            raise
        return _resend(client, pool_id, email)
    return "sent"


def _resend(client: Any, pool_id: str, email: str) -> str:
    try:
        existing = client.admin_get_user(UserPoolId=pool_id, Username=email)
    except Exception as exc:
        if _code(exc):
            raise ValueError("That person already has an account.") from exc
        raise
    if existing.get("UserStatus") != "FORCE_CHANGE_PASSWORD":
        raise ValueError("That person already has an account.")
    try:
        client.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            MessageAction="RESEND",
            DesiredDeliveryMediums=["EMAIL"],
        )
    except Exception as exc:
        if _code(exc):
            logger.exception("Could not resend invitation")
            raise RuntimeError("Could not send the invitation.") from exc
        raise
    return "resent"


def _attributes(email: str) -> list[dict[str, str]]:
    return [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
    ]


def _code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    error = response.get("Error") or {}
    if not isinstance(error, dict):
        return ""
    return str(error.get("Code") or "")
