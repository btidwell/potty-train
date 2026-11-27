"""Web Push subscriptions and VAPID signing.

The phone stores one subscription per browser endpoint. The Lambda signs
each send with the VAPID key from Secrets Manager. Local runs skip sending
when that key is not configured.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 10
_CACHE: dict[str, Any] = {"loaded_at": 0.0, "material": None}


class PushFailed(Exception):
    """A push service rejected the send. Scheduler should retry."""


def public_push_key() -> str:
    material = load_vapid()
    if not material:
        return ""
    return str(material["public_key"])


def load_vapid() -> dict[str, str] | None:
    now = time.time()
    if now - float(_CACHE["loaded_at"]) < 60 and _CACHE["loaded_at"]:
        return _CACHE["material"]
    material = _load_vapid()
    _CACHE["material"] = material
    _CACHE["loaded_at"] = now
    return material


def upsert_subscription(state: dict[str, Any], body: dict[str, Any]) -> None:
    endpoint = str(body.get("endpoint") or "").strip()
    if not endpoint.startswith("https://"):
        raise ValueError("Push endpoint must start with https://.")
    keys = body.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("Push subscription is missing keys.")
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not p256dh or not auth:
        raise ValueError("Push subscription is missing keys.")
    item = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}
    kept = [
        sub
        for sub in state.get("push_subscriptions") or []
        if isinstance(sub, dict) and sub.get("endpoint") != endpoint
    ]
    kept.append(item)
    state["push_subscriptions"] = kept[-MAX_SUBSCRIPTIONS:]


def off_notification(state: dict[str, Any]) -> tuple[str, str, str]:
    schedule = state["schedule"]
    name = str(state["settings"].get("child_name") or "").strip()
    minutes = schedule.get("timer_interval_minutes")
    if isinstance(minutes, int) and not isinstance(minutes, bool):
        length = f"{minutes} min off potty"
    else:
        length = "Off-potty interval"
    body = f"{name}. {length}." if name else f"{length}."
    return "Time to go potty", body, f"off:{schedule.get('next_sit_at')}"


def sit_notification(state: dict[str, Any]) -> tuple[str, str, str]:
    active = state["schedule"]["active_sit"]
    name = str(state["settings"].get("child_name") or "").strip()
    length = f"{state['settings'].get('sit_minutes')} min sit"
    body = f"{name}. {length}." if name else f"{length}."
    return "Sit time is up", body, f"sit:{active.get('started_at')}"


def deliver(state: dict[str, Any], title: str, body: str, tag: str, *, required: bool) -> str:
    """Send one notification to every stored subscription.

    Returns "sent" when the caller should record the deadline as sent,
    including when no subscriptions remain. Returns "skipped" when VAPID
    material is missing and the send is optional. Raises PushFailed when a
    required send cannot be signed, or when a push service returns anything
    other than 404 or 410. Those two statuses drop the stale subscription.
    """
    subscriptions = [sub for sub in state.get("push_subscriptions") or [] if isinstance(sub, dict)]
    if not subscriptions:
        return "sent"
    material = load_vapid()
    subject = os.environ.get("VAPID_SUBJECT", "").strip()
    if not material or not subject:
        if required:
            raise PushFailed("VAPID is not configured.")
        return "skipped"

    vapid = Vapid.from_pem(material["private_pem"].encode("utf-8"))
    payload = json.dumps({"title": title, "body": body, "tag": tag})
    kept: list[dict[str, Any]] = []
    failed = False
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": sub.get("endpoint"), "keys": sub.get("keys") or {}},
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": subject},
                content_encoding="aes128gcm",
                ttl=300,
                headers={"Urgency": "high"},
            )
        except WebPushException as exc:
            if exc.status_code in {404, 410}:
                logger.info("Dropping expired push subscription status=%s", exc.status_code)
                continue
            logger.warning("Push failed status=%s", exc.status_code)
            failed = True
            kept.append(sub)
        else:
            kept.append(sub)
    if kept != subscriptions:
        state["push_subscriptions"] = kept
    if failed:
        raise PushFailed("Push service rejected a notification.")
    return "sent"


def application_server_key(public_pem: str) -> str:
    key = load_pem_public_key(public_pem.encode("utf-8"))
    if not isinstance(key, EllipticCurvePublicKey):
        raise ValueError("VAPID public key must be an EC key.")
    numbers = key.public_numbers()
    raw = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _load_vapid() -> dict[str, str] | None:
    private_pem = os.environ.get("POTTY_VAPID_PRIVATE_PEM", "")
    public_pem = os.environ.get("POTTY_VAPID_PUBLIC_PEM", "")
    if private_pem and public_pem:
        return _material(private_pem, public_pem)

    # Prefer the aggregated app secret (one ARN, key/value pairs).
    if os.environ.get("APP_SECRET_ARN") or os.environ.get("POTTY_ENV") == "local":
        try:
            from potty_train.secrets import app_secret

            private_pem = app_secret("vapid_private_pem")
            public_pem = app_secret("vapid_public_pem")
            if private_pem and public_pem:
                return _material(private_pem, public_pem)
        except Exception:
            logger.exception("Could not load VAPID keys from the app secret.")

    if os.environ.get("POTTY_ENV") == "local":
        return None

    # Legacy single-purpose secret kept during the migration window.
    arn = os.environ.get("VAPID_SECRET_ARN", "")
    if not arn:
        return None
    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
    parsed = json.loads(str(response.get("SecretString") or ""))
    if not isinstance(parsed, dict):
        raise RuntimeError("VAPID secret must be a JSON object.")
    return _material(str(parsed.get("private_pem") or ""), str(parsed.get("public_pem") or ""))


def _material(private_pem: str, public_pem: str) -> dict[str, str]:
    private_pem = private_pem.strip()
    public_pem = public_pem.strip()
    if not private_pem or not public_pem:
        raise RuntimeError("VAPID secret is missing a key.")
    return {
        "private_pem": private_pem,
        "public_pem": public_pem,
        "public_key": application_server_key(public_pem),
    }
