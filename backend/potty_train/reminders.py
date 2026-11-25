"""One-time EventBridge schedules for timer deadlines.

The open page notifies itself. This module asks Scheduler to invoke the
Lambda when the phone is closed, and sends immediately when a deadline is
already past. A deadline inside the next minute is left to the open page:
Scheduler rejects an at() time that is too close.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from potty_train.push import PushFailed, deliver, off_notification, sit_notification

OFF_SCHEDULE = "potty-log-off"
SIT_SCHEDULE = "potty-log-sit"
LEAD = timedelta(seconds=60)


def scheduling_enabled() -> bool:
    if os.environ.get("POTTY_ENV") == "local":
        return False
    return bool(os.environ.get("SCHEDULER_ROLE_ARN"))


def sync_reminders(state: dict[str, Any], now: datetime) -> bool:
    """Update schedules and send anything already due. Returns True if state changed."""
    reminders = _reminders(state)
    changed = _sync_off(state, reminders, now)
    changed = _sync_sit(state, reminders, now) or changed
    return changed


def apply_reminder(state: dict[str, Any], reminder: dict[str, Any]) -> bool:
    """Handle a Scheduler invocation. Raises PushFailed so the invoke is retried."""
    reminders = _reminders(state)
    kind = reminder.get("kind")
    if kind == "off":
        token = str(reminder.get("due") or "")
        changed = _clear_if_same(reminders, "off_scheduled_for", token)
        if not _off_still_due(state, reminders, token):
            return changed
        if deliver(state, *off_notification(state), required=True) == "sent":
            reminders["off_sent_for"] = token
        return True
    if kind == "sit":
        token = str(reminder.get("started_at") or "")
        changed = _clear_if_same(reminders, "sit_scheduled_for", token)
        if not _sit_still_due(state, reminders, token):
            return changed
        if deliver(state, *sit_notification(state), required=True) == "sent":
            reminders["sit_sent_for"] = token
        return True
    return False


def _sync_off(state: dict[str, Any], reminders: dict[str, Any], now: datetime) -> bool:
    schedule = state["schedule"]
    token = schedule.get("next_sit_at")
    if not schedule.get("running") or not token:
        changed = _delete_schedule(OFF_SCHEDULE)
        return _clear_field(reminders, "off_scheduled_for") or changed
    due = _parse(str(token))
    if due - now > LEAD:
        if reminders.get("off_scheduled_for") == token or not scheduling_enabled():
            return False
        _upsert_schedule(OFF_SCHEDULE, due, {"reminder": {"kind": "off", "due": token}})
        reminders["off_scheduled_for"] = token
        return True
    if due > now or schedule.get("active_sit"):
        return False
    if reminders.get("off_sent_for") == token:
        return False
    return _send(state, reminders, "off_sent_for", str(token), off_notification(state))


def _sync_sit(state: dict[str, Any], reminders: dict[str, Any], now: datetime) -> bool:
    schedule = state["schedule"]
    active = schedule.get("active_sit")
    if not active or not active.get("started_at"):
        changed = _delete_schedule(SIT_SCHEDULE)
        return _clear_field(reminders, "sit_scheduled_for") or changed
    token = str(active["started_at"])
    end = _parse(token) + timedelta(minutes=int(state["settings"]["sit_minutes"]))
    if end - now > LEAD:
        if reminders.get("sit_scheduled_for") == token or not scheduling_enabled():
            return False
        _upsert_schedule(SIT_SCHEDULE, end, {"reminder": {"kind": "sit", "started_at": token}})
        reminders["sit_scheduled_for"] = token
        return True
    if end > now:
        return False
    if reminders.get("sit_sent_for") == token:
        return False
    return _send(state, reminders, "sit_sent_for", token, sit_notification(state))


def _send(
    state: dict[str, Any],
    reminders: dict[str, Any],
    field: str,
    token: str,
    message: tuple[str, str, str],
) -> bool:
    try:
        result = deliver(state, *message, required=False)
    except PushFailed:
        logger.exception("Immediate push failed.")
        return True
    if result == "sent":
        reminders[field] = token
        return True
    return False


def _off_still_due(state: dict[str, Any], reminders: dict[str, Any], token: str) -> bool:
    schedule = state.get("schedule") or {}
    if not token or schedule.get("active_sit") or not schedule.get("running"):
        return False
    if schedule.get("next_sit_at") != token:
        return False
    return reminders.get("off_sent_for") != token


def _sit_still_due(state: dict[str, Any], reminders: dict[str, Any], token: str) -> bool:
    if not token:
        return False
    active = (state.get("schedule") or {}).get("active_sit") or {}
    if active.get("started_at") != token:
        return False
    return reminders.get("sit_sent_for") != token


def _reminders(state: dict[str, Any]) -> dict[str, Any]:
    current = state.get("reminders")
    if not isinstance(current, dict):
        current = {}
        state["reminders"] = current
    return current


def _clear_field(reminders: dict[str, Any], field: str) -> bool:
    if reminders.get(field):
        reminders[field] = None
        return True
    return False


def _clear_if_same(reminders: dict[str, Any], field: str, token: str) -> bool:
    if token and reminders.get(field) == token:
        reminders[field] = None
        return True
    return False


def _upsert_schedule(name: str, when: datetime, payload: dict[str, Any]) -> None:
    client = _client()
    kwargs = {
        "Name": name,
        "GroupName": "default",
        "ScheduleExpression": _expression(when),
        "ScheduleExpressionTimezone": "UTC",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "ActionAfterCompletion": "DELETE",
        "Target": {
            "Arn": os.environ["SCHEDULE_TARGET_ARN"],
            "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
            "Input": json.dumps(payload),
            "RetryPolicy": {
                "MaximumRetryAttempts": 2,
                "MaximumEventAgeInSeconds": 300,
            },
        },
    }
    try:
        client.create_schedule(**kwargs)
    except Exception as exc:
        if _error_code(exc) != "ConflictException":
            raise
        client.update_schedule(**kwargs)


def _delete_schedule(name: str) -> bool:
    if not scheduling_enabled():
        return False
    try:
        _client().delete_schedule(Name=name, GroupName="default")
    except Exception as exc:
        if _error_code(exc) != "ResourceNotFoundException":
            raise
    return False


def _expression(moment: datetime) -> str:
    utc = moment.astimezone(timezone.utc).replace(microsecond=0)
    return f"at({utc.strftime('%Y-%m-%dT%H:%M:%S')})"


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _client() -> Any:
    import boto3

    return boto3.client("scheduler")


def _error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error") or {}
        if isinstance(error, dict):
            return str(error.get("Code") or "")
    return ""
