"""API Gateway / Lambda Function URL entrypoint.

Routes are intentionally few. Every mutation returns the full public state
so the phone UI can refresh from one response.

EventBridge Scheduler invokes the same function with a reminder event when
a timer deadline arrives and the phone may be closed. That event is not an
HTTP request and does not pass through CloudFront.
"""

from __future__ import annotations

import csv
import hmac
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from potty_train.auth import auth_config, is_owner, token_is_valid, token_username
from potty_train.directory import actor_email, list_users
from potty_train.invites import send_invite
from potty_train.push import PushFailed, upsert_subscription
from potty_train.reminders import apply_reminder, sync_reminders
from potty_train.sessions import display_ip, list_sessions, open_session, owns, revoke, touch
from potty_train.service import (
    create_entry,
    delete_entry,
    public_state,
    resolve_now,
    schedule_action,
    start_sit,
    update_entry,
    update_settings,
)
from potty_train.store import Conflict, build_store

logger = logging.getLogger(__name__)

_STORE = None

# These rejects mean the schedule is already in the state the phone asked for,
# or another save landed first. The response includes the current log so the
# open page can show that timer instead of staying on the start button.
_SCHEDULE_CONFLICTS = {
    "The off-potty timer is already running.",
    "A sit is already in progress.",
    "Finish or cancel the sit that is already in progress.",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if _is_reminder_event(event):
        return _remind(event)
    if not _from_cloudfront(event):
        return _response(403, {"error": "Forbidden."})
    method = _method(event)
    path = _path(event)
    if method == "OPTIONS":
        return _response(204, {})

    try:
        if method == "GET" and path == "/api/health":
            return _response(200, {"ok": True})
        if method == "GET" and path == "/api/auth-config":
            try:
                return _response(200, auth_config())
            except RuntimeError:
                return _response(500, {"error": "Sign-in is not configured."})
        if not _authorized(event):
            return _response(401, {"error": "Sign in again."})
        if method == "POST" and path == "/api/sessions":
            return _open_session(event)
        if not session_allows(event):
            return _response(401, {"error": "Sign in again."})
        if method == "GET" and path == "/api/sessions":
            return _list_sessions(event)
        if method == "DELETE" and path.startswith("/api/sessions/"):
            return _revoke_session(event, path.rsplit("/", 1)[-1])
        if method == "GET" and path == "/api/state":
            state, _etag = _load()
            return _response(200, public_state(state, _server_now()))
        if method == "GET" and path == "/api/export.csv":
            return _export()
        if method == "GET" and path == "/api/users":
            return _users(event)
        if method == "PUT" and path == "/api/settings":
            return _mutate(event, lambda state, body, now: update_settings(state, body))
        if method == "POST" and path == "/api/entries":
            return _mutate(
                event,
                lambda state, body, now: create_entry(state, body, now, recorded_by=_actor(event)),
            )
        if method == "PUT" and path.startswith("/api/entries/"):
            entry_id = path.rsplit("/", 1)[-1]
            return _mutate(event, lambda state, body, now: update_entry(state, entry_id, body, now))
        if method == "DELETE" and path.startswith("/api/entries/"):
            entry_id = path.rsplit("/", 1)[-1]
            return _mutate(event, lambda state, body, now: delete_entry(state, entry_id))
        if method == "POST" and path == "/api/schedule/start-sit":
            return _mutate(event, lambda state, body, now: start_sit(state, str(body.get("kind") or ""), now))
        if method == "POST" and path == "/api/schedule/start-timer":
            return _mutate(event, lambda state, body, now: schedule_action(state, "start_timer", now))
        if method == "POST" and path == "/api/schedule/stop-timer":
            return _mutate(event, lambda state, body, now: schedule_action(state, "stop_timer", now))
        if method == "POST" and path == "/api/schedule/cancel-sit":
            return _mutate(event, lambda state, body, now: schedule_action(state, "cancel_sit", now))
        if method == "POST" and path == "/api/push/subscribe":
            return _subscribe(event)
        if method == "POST" and path == "/api/invites":
            return _invite(event)
        return _response(404, {"error": "Not found."})
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be JSON."})
    except ValueError as exc:
        message = str(exc)
        if message in _SCHEDULE_CONFLICTS:
            return _schedule_conflict(message)
        return _response(400, {"error": message})
    except Conflict:
        return _schedule_conflict("The log was updated from another screen. Reload and try again.")
    except RuntimeError:
        return _response(500, {"error": "The app is not configured."})


def session_allows(event: dict[str, Any]) -> bool:
    username = token_username(_bearer(event))
    session_id = _session_id(event)
    if not username or not session_id or not owns(session_id, username):
        return False
    try:
        touch(session_id)
    except Exception:
        logger.exception("Could not refresh the session.")
    return True


def _open_session(event: dict[str, Any]) -> dict[str, Any]:
    username = token_username(_bearer(event))
    if not username:
        return _response(401, {"error": "Sign in again."})
    body = _body(event)
    try:
        opened = open_session(
            username,
            label=str(body.get("label") or ""),
            device_key=str(body.get("device_key") or ""),
            remembered=bool(body.get("remembered")),
            ip=_client_ip(event),
            session_id=_session_id(event),
            now=_server_now(),
        )
    except RuntimeError:
        return _response(500, {"error": "Could not start the session."})
    return _response(200, {"session": opened})


def _list_sessions(event: dict[str, Any]) -> dict[str, Any]:
    username = token_username(_bearer(event))
    if not username:
        return _response(401, {"error": "Sign in again."})
    return _response(200, {"sessions": list_sessions(username)})


def _revoke_session(event: dict[str, Any], session_id: str) -> dict[str, Any]:
    username = token_username(_bearer(event))
    if not username:
        return _response(401, {"error": "Sign in again."})
    if revoke(session_id, username) is None:
        return _response(404, {"error": "That device is already signed out."})
    return _response(200, {"ok": True})


def _session_id(event: dict[str, Any]) -> str:
    return _headers_in(event).get("x-potty-session", "").strip()


def _client_ip(event: dict[str, Any]) -> str:
    headers = _headers_in(event)
    raw = headers.get("cloudfront-viewer-address") or headers.get("x-forwarded-for") or ""
    return display_ip(raw.split(",")[0])


def _users(event: dict[str, Any]) -> dict[str, Any]:
    if not is_owner(_bearer(event)):
        return _response(403, {"error": "Only the account owner can see accounts."})
    try:
        return _response(200, {"users": list_users()})
    except RuntimeError:
        return _response(500, {"error": "Could not load accounts."})


def _actor(event: dict[str, Any]) -> str:
    try:
        return actor_email(_bearer(event))
    except Exception:
        logger.exception("Could not name the account saving this row.")
        return ""


def _invite(event: dict[str, Any]) -> dict[str, Any]:
    if not is_owner(_bearer(event)):
        return _response(403, {"error": "Only the account owner can send invites."})
    try:
        result = send_invite(str(_body(event).get("email") or ""))
    except ValueError as exc:
        return _response(400, {"error": str(exc)})
    except RuntimeError:
        return _response(500, {"error": "Could not send the invitation."})
    message = "Invitation sent again." if result == "resent" else "Invitation sent."
    return _response(200, {"ok": True, "message": message})


def _schedule_conflict(message: str) -> dict[str, Any]:
    state, _etag = _load()
    return _response(409, {"error": message, "state": public_state(state, _server_now())})


def _mutate(event: dict[str, Any], action: Any) -> dict[str, Any]:
    body = _body(event)
    now = resolve_now(body, _server_now())
    state, etag = _load()
    action(state, body, now)
    etag = _save(state, etag)
    _sync_after_save(state, etag, now)
    return _response(200, public_state(state, now))


def _subscribe(event: dict[str, Any]) -> dict[str, Any]:
    state, etag = _load()
    upsert_subscription(state, _body(event))
    _save(state, etag)
    return _response(200, public_state(state, _server_now()))


def _remind(event: dict[str, Any]) -> dict[str, Any]:
    state, etag = _load()
    try:
        changed = apply_reminder(state, event["reminder"])
    except PushFailed:
        _save_quietly(state, etag)
        raise
    if changed:
        _save(state, etag)
    return {"ok": True}


def _sync_after_save(state: dict[str, Any], etag: str, now: datetime) -> None:
    try:
        if sync_reminders(state, now):
            _save(state, etag)
    except Exception:
        logger.exception("Could not sync timer reminders.")


def _save_quietly(state: dict[str, Any], etag: str) -> None:
    try:
        _save(state, etag)
    except Exception:
        logger.exception("Could not save push subscriptions after a failed send.")


def _is_reminder_event(event: dict[str, Any]) -> bool:
    if "httpMethod" in event or "requestContext" in event:
        return False
    reminder = event.get("reminder")
    return isinstance(reminder, dict) and reminder.get("kind") in {"off", "sit"}


def _export() -> dict[str, Any]:
    state, _etag = _load()
    view = public_state(state, _server_now())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Date",
            "Time",
            "Off-potty interval",
            "BM",
            "Urine",
            "Soiled",
            "Wet",
            "Kind",
            "Decision",
            "Comments",
            "Who",
        ]
    )
    for entry in view["entries"]:
        writer.writerow(
            [
                entry["date"],
                entry["time"],
                entry["interval_minutes"],
                "Y" if entry["toilet_bm"] else "N",
                "Y" if entry["toilet_urine"] else "N",
                "Y" if entry["accident_soiled"] else "N",
                "Y" if entry["accident_wet"] else "N",
                entry["kind"],
                entry["decision_note"],
                entry["comment"],
                entry.get("recorded_by") or "",
            ]
        )
    return {
        "statusCode": 200,
        "headers": {
            **_headers(),
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=potty-log.csv",
        },
        "body": buffer.getvalue(),
    }


def _authorized(event: dict[str, Any]) -> bool:
    return token_is_valid(_bearer(event))


def _bearer(event: dict[str, Any]) -> str:
    headers = _headers_in(event)
    # CloudFront signs the origin request, so it replaces Authorization.
    # The browser sends the access token in X-Potty-Authorization.
    header = headers.get("x-potty-authorization") or headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def _load() -> tuple[dict[str, Any], str]:
    return _store().load()


def _save(state: dict[str, Any], etag: str) -> str:
    return _store().save(state, etag)


def _store():
    global _STORE
    if _STORE is None:
        _STORE = build_store()
    return _STORE


def _server_now() -> datetime:
    return datetime.now(timezone.utc)


def _body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and isinstance(raw, str):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be an object.")
    return parsed


def _from_cloudfront(event: dict[str, Any]) -> bool:
    if os.environ.get("POTTY_ENV") == "local":
        return True
    expected = os.environ.get("POTTY_ORIGIN_SECRET", "")
    got = _headers_in(event).get("x-potty-origin", "")
    if not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def _method(event: dict[str, Any]) -> str:
    return str(event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "").upper()


def _path(event: dict[str, Any]) -> str:
    raw = str(event.get("rawPath") or event.get("path") or "/")
    if raw.endswith("/") and raw != "/":
        raw = raw[:-1]
    return raw


def _headers_in(event: dict[str, Any]) -> dict[str, str]:
    headers = event.get("headers") or {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": _headers(), "body": json.dumps(body)}


def _headers() -> dict[str, str]:
    origin = os.environ.get("CORS_ORIGIN", "")
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Potty-Authorization, X-Potty-Session"
        headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return headers
