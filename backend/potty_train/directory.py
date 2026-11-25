"""Household accounts for the owner.

Cognito is the directory. This module turns that directory into the short
list the People page shows, and it names the account that saves a new row.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from potty_train.auth import token_username
from potty_train.invites import _code
from potty_train.sessions import sessions_by_user

logger = logging.getLogger(__name__)


def list_users(client: Any | None = None) -> list[dict[str, Any]]:
    pool_id = _pool_id()
    cognito = _client(client)
    found: list[dict[str, Any]] = []
    sessions = sessions_by_user()
    token = ""
    while True:
        kwargs: dict[str, Any] = {"UserPoolId": pool_id, "Limit": 60}
        if token:
            kwargs["PaginationToken"] = token
        try:
            page = cognito.list_users(**kwargs)
        except Exception as exc:
            if _code(exc):
                logger.exception("Could not list accounts")
                raise RuntimeError("Could not load accounts.") from exc
            raise
        for user in page.get("Users") or []:
            found.append(_public_user(cognito, pool_id, user, sessions))
        token = str(page.get("PaginationToken") or "")
        if not token:
            break
    found.sort(key=lambda item: (not item["owner"], item["email"]))
    return found


def actor_email(token: str, client: Any | None = None) -> str:
    username = token_username(token)
    if not username:
        return ""
    try:
        user = _client(client).admin_get_user(UserPoolId=_pool_id(), Username=username)
    except Exception as exc:
        if _code(exc):
            logger.exception("Could not name the account saving this row.")
            return ""
        raise
    return _email(user.get("UserAttributes") or [])


def _public_user(
    client: Any,
    pool_id: str,
    user: dict[str, Any],
    sessions: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    username = str(user.get("Username") or "")
    email = _email(user.get("Attributes") or []) or username
    enabled = bool(user.get("Enabled", True))
    status, label = _status(str(user.get("UserStatus") or ""), enabled)
    authenticator, owner = _detail(client, pool_id, username, str(user.get("UserStatus") or ""))
    return {
        "email": email,
        "status": status,
        "status_label": label,
        "enabled": enabled,
        "created_at": _iso(user.get("UserCreateDate")),
        "updated_at": _iso(user.get("UserLastModifiedDate")),
        "authenticator": authenticator,
        "owner": owner,
        "sessions": sessions.get(username, []),
    }


def _detail(client: Any, pool_id: str, username: str, user_status: str) -> tuple[bool, bool]:
    if not username:
        return False, False
    try:
        detail = client.admin_get_user(UserPoolId=pool_id, Username=username)
        groups = client.admin_list_groups_for_user(UserPoolId=pool_id, Username=username)
    except Exception as exc:
        if _code(exc):
            logger.exception("Could not read account %s", username)
            return False, False
        raise
    names = [group.get("GroupName") for group in groups.get("Groups") or []]
    return _authenticator(client, pool_id, username, detail, user_status), "owners" in names


def _authenticator(client: Any, pool_id: str, username: str, detail: dict[str, Any], user_status: str) -> bool:
    """Whether this account has a verified authenticator.

    Cognito only fills UserMFASettingList after a preference is saved. A pool
    that requires an authenticator still leaves that list empty after the user
    verifies one. Saving the preference records it. Cognito rejects that save
    when no authenticator has been verified.
    """
    settings = detail.get("UserMFASettingList") or []
    if "SOFTWARE_TOKEN_MFA" in settings or detail.get("PreferredMfaSetting") == "SOFTWARE_TOKEN_MFA":
        return True
    if user_status in {"FORCE_CHANGE_PASSWORD", "UNCONFIRMED"}:
        return False
    try:
        client.admin_set_user_mfa_preference(
            UserPoolId=pool_id,
            Username=username,
            SoftwareTokenMfaSettings={"Enabled": True, "PreferredMfa": True},
        )
    except Exception as exc:
        if _code(exc) == "InvalidParameterException":
            return False
        if _code(exc):
            logger.exception("Could not record authenticator status for %s", username)
            return False
        raise
    return True


def _status(user_status: str, enabled: bool) -> tuple[str, str]:
    if not enabled:
        return "disabled", "Disabled"
    if user_status == "FORCE_CHANGE_PASSWORD":
        return "invited", "Invited"
    if user_status == "CONFIRMED":
        return "active", "Active"
    if user_status == "RESET_REQUIRED":
        return "reset", "Needs a new password"
    return "other", user_status.replace("_", " ").title() or "Unknown"


def _email(attributes: list[dict[str, Any]]) -> str:
    for item in attributes:
        if item.get("Name") == "email" and item.get("Value"):
            return str(item["Value"])
    return ""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _pool_id() -> str:
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    if not pool_id:
        raise RuntimeError("Cognito user pool is not configured.")
    return pool_id


def _client(client: Any | None) -> Any:
    if client is not None:
        return client
    import boto3

    return boto3.client(
        "cognito-idp",
        region_name=os.environ.get("COGNITO_REGION") or os.environ.get("AWS_REGION"),
    )
