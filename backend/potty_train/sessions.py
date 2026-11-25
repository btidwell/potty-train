"""Browser sessions for one signed-in account.

Cognito remembers a device so a later sign-in can skip the authenticator
code. It does not offer a way to end one browser's refresh token from
another browser. This list is that missing piece: the API accepts a request
only when its session is still here, and revoking a row forgets the device
so the next sign-in asks for an authenticator code.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from potty_train.invites import _code
from potty_train.store import Conflict

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_RECENT: dict[str, datetime] = {}
_TOUCH_AFTER = timedelta(minutes=10)
_MAX_PER_USER = 20
_DEVICE_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def open_session(
    username: str,
    *,
    label: str,
    device_key: str,
    remembered: bool,
    ip: str,
    session_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    username = username.strip()
    if not username:
        raise ValueError("Sign in again.")
    stamp = _stamp(now)
    device_key = device_key if _DEVICE_KEY.fullmatch(device_key) else ""
    remembered = bool(remembered and device_key)
    label = _label(label)
    ip = ip.strip()[:64]

    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        current = _find(rows, session_id, username) if session_id else None
        if current:
            current["label"] = label
            current["device_key"] = device_key
            current["remembered"] = remembered
            current["last_seen"] = stamp
            if ip:
                current["ip"] = ip
            return _public(current)
        fresh = {
            "id": str(uuid4()),
            "sub": username,
            "label": label,
            "device_key": device_key,
            "remembered": remembered,
            "created_at": stamp,
            "last_seen": stamp,
            "ip": ip,
        }
        rows.append(fresh)
        _trim(rows, username)
        return _public(fresh)

    opened = _update(mutate)
    if opened is None:
        raise RuntimeError("Could not start the session.")
    return opened


def list_sessions(username: str) -> list[dict[str, Any]]:
    return sessions_by_user().get(username, [])


def sessions_by_user() -> dict[str, list[dict[str, Any]]]:
    rows, _etag = _load()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        username = str(row.get("sub") or "")
        if not username:
            continue
        grouped.setdefault(username, []).append(_public(row))
    for items in grouped.values():
        items.sort(key=lambda item: item["last_seen"], reverse=True)
    return grouped


def owns(session_id: str, username: str) -> bool:
    rows, _etag = _load()
    return _find(rows, session_id, username) is not None


def touch(session_id: str, now: datetime | None = None) -> None:
    moment = _parse(_stamp(now))
    recent = _RECENT.get(session_id)
    if moment and recent and moment - recent < _TOUCH_AFTER:
        return
    stamp = _stamp(now)

    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        for row in rows:
            if row.get("id") != session_id:
                continue
            seen = _parse(row.get("last_seen"))
            if seen and moment and moment - seen < _TOUCH_AFTER:
                _RECENT[session_id] = seen
                return None
            row["last_seen"] = stamp
            if moment:
                _RECENT[session_id] = moment
            return row
        return None

    _update(mutate)


def revoke(session_id: str, username: str, client: Any | None = None) -> dict[str, Any] | None:
    found: dict[str, Any] | None = None

    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        nonlocal found
        row = _find(rows, session_id, username)
        if not row:
            return None
        found = dict(row)
        rows.remove(row)
        return found

    removed = _update(mutate)
    if not removed or not found:
        return None
    _RECENT.pop(session_id, None)
    if found.get("device_key"):
        forget_remote_device(username, str(found["device_key"]), client)
    return _public(found)


def forget_remote_device(username: str, device_key: str, client: Any | None = None) -> None:
    if not username or not device_key:
        return
    try:
        _client(client).admin_forget_device(
            UserPoolId=_pool_id(),
            Username=username,
            DeviceKey=device_key,
        )
    except Exception as exc:
        if _code(exc) not in {"ResourceNotFoundException", "InvalidParameterException"}:
            logger.exception("Could not forget device")


def display_ip(value: str) -> str:
    """Drop a viewer port so an address stays readable.

    CloudFront appends the source port. An IPv6 hextet is at most four
    digits, so a longer all-digit tail is that port. One colon is an IPv4
    address plus a port.
    """
    ip = str(value or "").strip()
    if ip.startswith("[") and "]" in ip:
        ip = ip[1:ip.index("]")]
    host, sep, port = ip.rpartition(":")
    if sep and host and port.isdigit() and int(port) <= 65535 and (len(port) > 4 or ip.count(":") == 1):
        ip = host
    return ip[:64]


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "label": row["label"],
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
        "ip": display_ip(str(row.get("ip") or "")),
        "remembered": bool(row.get("remembered")),
    }


def _find(rows: list[dict[str, Any]], session_id: str, username: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("id") == session_id and row.get("sub") == username:
            return row
    return None


def _trim(rows: list[dict[str, Any]], username: str) -> None:
    own = [row for row in rows if row.get("sub") == username]
    if len(own) <= _MAX_PER_USER:
        return
    own.sort(key=lambda row: row.get("last_seen") or "")
    for extra in own[: len(own) - _MAX_PER_USER]:
        rows.remove(extra)


def _label(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        return "This browser"
    return text[:80]


def _stamp(now: datetime | None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _update(mutator: Any) -> Any:
    for _attempt in range(4):
        rows, etag = _load()
        result = mutator(rows)
        if result is None:
            return None
        try:
            _save(rows, etag)
            return result
        except Conflict:
            continue
    raise RuntimeError("Could not update sessions.")


def _load() -> tuple[list[dict[str, Any]], str]:
    if os.environ.get("POTTY_ENV") == "local":
        return _file_load()
    return _s3_load()


def _save(rows: list[dict[str, Any]], etag: str) -> None:
    if os.environ.get("POTTY_ENV") == "local":
        _file_save(rows, etag)
        return
    _s3_save(rows, etag)


def _file_path() -> Path:
    return Path(os.environ.get("POTTY_SESSIONS_PATH", "backend/.local-sessions.json"))


def _file_load() -> tuple[list[dict[str, Any]], str]:
    path = _file_path()
    with _LOCK:
        if not path.exists():
            return [], ""
        raw = json.loads(path.read_text(encoding="utf-8"))
    etag = str(raw.get("_rev", "")) if isinstance(raw, dict) else ""
    rows = raw.get("sessions") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return [], etag
    return [row for row in rows if isinstance(row, dict)], etag


def _file_save(rows: list[dict[str, Any]], etag: str) -> None:
    path = _file_path()
    with _LOCK:
        current = ""
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            current = str(raw.get("_rev", "")) if isinstance(raw, dict) else ""
        if current != etag:
            raise Conflict()
        revision = str(int(current or "0") + 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"_rev": revision, "sessions": rows}, indent=2), encoding="utf-8")
        tmp.replace(path)


def _s3_load() -> tuple[list[dict[str, Any]], str]:
    from botocore.exceptions import ClientError

    bucket, key = _s3_target()
    try:
        response = _s3().get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in {"NoSuchKey", "404", "NotFound", "AccessDenied", "403"}:
            return [], ""
        raise
    raw = json.loads(response["Body"].read().decode("utf-8"))
    rows = raw.get("sessions") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return [], response["ETag"]
    return [row for row in rows if isinstance(row, dict)], response["ETag"]


def _s3_save(rows: list[dict[str, Any]], etag: str) -> None:
    from botocore.exceptions import ClientError

    bucket, key = _s3_target()
    kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
        "Body": json.dumps({"sessions": rows}).encode("utf-8"),
        "ContentType": "application/json",
    }
    if etag:
        kwargs["IfMatch"] = etag
    else:
        kwargs["IfNoneMatch"] = "*"
    try:
        _s3().put_object(**kwargs)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in {"PreconditionFailed", "ConditionalRequestConflict", "412"}:
            raise Conflict() from exc
        raise


def _s3_target() -> tuple[str, str]:
    bucket = os.environ["DATA_BUCKET"]
    key = os.environ.get("SESSIONS_KEY", "state/sessions.json")
    return bucket, key


_S3: Any = None


def _s3() -> Any:
    global _S3
    if _S3 is None:
        import boto3

        _S3 = boto3.client("s3")
    return _S3


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
