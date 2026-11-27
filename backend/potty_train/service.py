"""State transitions for the potty log.

The schedule clock is separate from the sheet. A scheduled sit or a sit the
child asked for starts a new off-potty interval when it ends. An accident sit
does not reset that clock: the next trip stays on the original schedule.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from potty_train.rules import current_interval, recompute_entries, streak_status

KINDS = {"scheduled", "asked", "accident", "manual"}


def default_settings() -> dict[str, Any]:
    return {
        "child_name": "",
        "starting_interval_minutes": 15,
        "step_minutes": 5,
        "min_interval_minutes": 5,
        "max_interval_minutes": 120,
        "sit_minutes": 5,
        "drink_prompt_minutes": 10,
        "reinforcer_note": "",
        "timezone": "America/New_York",
    }


def default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "settings": default_settings(),
        "schedule": {
            "running": False,
            "next_sit_at": None,
            "timer_interval_minutes": None,
            "active_sit": None,
        },
        "entries": [],
        "seq": 0,
        "auth_failures": 0,
        "auth_locked_until": None,
    }


def public_state(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    settings = state["settings"]
    entries = recompute_entries(deepcopy(state["entries"]), settings)
    status = streak_status(state["entries"], settings)
    today = _local_date(now, settings["timezone"])
    todays = [entry for entry in entries if entry["date"] == today]
    today_sits, today_voids, today_accidents = _day_counts(todays)
    if todays or not entries:
        summary_label = "today"
        summary_sits, summary_voids, summary_accidents = today_sits, today_voids, today_accidents
    else:
        summary_label = max(entry["date"] for entry in entries)
        summary_sits, summary_voids, summary_accidents = _day_counts(
            [entry for entry in entries if entry["date"] == summary_label]
        )
    return {
        "settings": settings,
        "schedule": state["schedule"],
        "entries": entries,
        "derived": {
            **status,
            "today": today,
            "today_sits": today_sits,
            "today_voids": today_voids,
            "today_accidents": today_accidents,
            "summary_label": summary_label,
            "summary_sits": summary_sits,
            "summary_voids": summary_voids,
            "summary_accidents": summary_accidents,
            "server_now": now.isoformat(),
        },
        "push": _push_view(state),
    }


def _push_view(state: dict[str, Any]) -> dict[str, Any]:
    """Deadline tokens the open page needs so it does not alert again.

    The reminders object and the push subscriptions stay off the response.
    Import push lazily so chat/MCP auth paths can load service without pywebpush.
    """
    reminders = state.get("reminders")
    if not isinstance(reminders, dict):
        reminders = {}
    try:
        from potty_train.push import public_push_key

        public_key = public_push_key()
    except Exception:
        public_key = ""
    return {
        "public_key": public_key,
        "off_sent_for": _deadline_token(reminders.get("off_sent_for")),
        "sit_sent_for": _deadline_token(reminders.get("sit_sent_for")),
        "off_scheduled_for": _deadline_token(reminders.get("off_scheduled_for")),
        "sit_scheduled_for": _deadline_token(reminders.get("sit_scheduled_for")),
    }


def _deadline_token(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def update_settings(state: dict[str, Any], payload: dict[str, Any]) -> None:
    settings = deepcopy(state["settings"])
    fields = {
        "child_name": _clean_text(payload.get("child_name", settings["child_name"]), 80),
        "starting_interval_minutes": _minutes(payload.get("starting_interval_minutes", settings["starting_interval_minutes"]), 5, 240),
        "step_minutes": _minutes(payload.get("step_minutes", settings["step_minutes"]), 5, 30),
        "min_interval_minutes": _minutes(payload.get("min_interval_minutes", settings["min_interval_minutes"]), 5, 120),
        "max_interval_minutes": _minutes(payload.get("max_interval_minutes", settings["max_interval_minutes"]), 5, 240),
        "sit_minutes": _minutes(payload.get("sit_minutes", settings["sit_minutes"]), 1, 15),
        "drink_prompt_minutes": _minutes(payload.get("drink_prompt_minutes", settings["drink_prompt_minutes"]), 0, 60),
        "reinforcer_note": _clean_text(payload.get("reinforcer_note", settings["reinforcer_note"]), 240),
        "timezone": _timezone(payload.get("timezone", settings["timezone"])),
    }
    if fields["min_interval_minutes"] > fields["max_interval_minutes"]:
        raise ValueError("Minimum interval cannot be above the maximum.")
    if not (fields["min_interval_minutes"] <= fields["starting_interval_minutes"] <= fields["max_interval_minutes"]):
        raise ValueError("Starting interval must sit between the minimum and the maximum.")
    state["settings"] = fields


def create_entry(
    state: dict[str, Any],
    payload: dict[str, Any],
    now: datetime,
    recorded_by: str = "",
) -> dict[str, Any]:
    entry = _entry_from_payload(state, payload, now)
    name = recorded_by.strip()
    if name:
        entry["recorded_by"] = name
    state["entries"].append(entry)
    _finish_sit_if_needed(state, entry, now)
    return entry


def update_entry(state: dict[str, Any], entry_id: str, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    entry = _find(state, entry_id)
    merged = {
        "date": payload.get("date", entry["date"]),
        "time": payload.get("time", entry["time"]),
        "kind": payload.get("kind", entry["kind"]),
        "toilet_bm": payload.get("toilet_bm", entry["toilet_bm"]),
        "toilet_urine": payload.get("toilet_urine", entry["toilet_urine"]),
        "accident_soiled": payload.get("accident_soiled", entry["accident_soiled"]),
        "accident_wet": payload.get("accident_wet", entry["accident_wet"]),
        "comment": payload.get("comment", entry["comment"]),
    }
    refreshed = _entry_from_payload(state, merged, now, seq=entry["seq"], entry_id=entry["id"])
    refreshed["created_at"] = entry["created_at"]
    if entry.get("recorded_by"):
        refreshed["recorded_by"] = entry["recorded_by"]
    if "logged_interval" in entry and entry["logged_interval"] is not None:
        refreshed["logged_interval"] = int(entry["logged_interval"])
    index = state["entries"].index(entry)
    state["entries"][index] = refreshed
    return refreshed


def delete_entry(state: dict[str, Any], entry_id: str) -> None:
    entry = _find(state, entry_id)
    state["entries"] = [item for item in state["entries"] if item["id"] != entry["id"]]


def schedule_action(state: dict[str, Any], action: str, now: datetime) -> None:
    schedule = state["schedule"]
    settings = state["settings"]
    interval = _interval_now(state)

    if action == "start_timer":
        if schedule["active_sit"]:
            raise ValueError("Finish or cancel the sit that is already in progress.")
        if schedule["running"]:
            raise ValueError("The off-potty timer is already running.")
        schedule["running"] = True
        schedule["timer_interval_minutes"] = interval
        schedule["next_sit_at"] = (now + timedelta(minutes=interval)).isoformat()
        return

    if action == "stop_timer":
        if schedule["active_sit"]:
            raise ValueError("Finish or cancel the sit before stopping the timer.")
        schedule["running"] = False
        schedule["next_sit_at"] = None
        schedule["timer_interval_minutes"] = None
        return

    if action == "start_sit":
        raise ValueError("Use start_sit with a kind.")

    if action == "cancel_sit":
        active = schedule["active_sit"]
        if not active:
            raise ValueError("No sit is in progress.")
        schedule["active_sit"] = None
        preserved = active.get("preserved_next_sit_at")
        if preserved:
            schedule["running"] = True
            schedule["next_sit_at"] = preserved
            schedule["timer_interval_minutes"] = active.get("preserved_timer_interval_minutes")
        else:
            schedule["running"] = False
            schedule["next_sit_at"] = None
            schedule["timer_interval_minutes"] = None
        return

    raise ValueError(f"Unknown schedule action: {action}")


def start_sit(state: dict[str, Any], kind: str, now: datetime) -> None:
    if kind not in {"scheduled", "asked", "accident"}:
        raise ValueError("Sit kind must be scheduled, asked, or accident.")
    schedule = state["schedule"]
    if schedule["active_sit"]:
        raise ValueError("A sit is already in progress.")
    schedule["active_sit"] = {
        "started_at": now.isoformat(),
        "kind": kind,
        "preserved_next_sit_at": schedule["next_sit_at"],
        "preserved_timer_interval_minutes": schedule["timer_interval_minutes"],
    }


def _finish_sit_if_needed(state: dict[str, Any], entry: dict[str, Any], now: datetime) -> None:
    schedule = state["schedule"]
    active = schedule["active_sit"]
    if entry["kind"] == "manual" or not active:
        return
    if entry["kind"] != active["kind"]:
        # The row still closes the open sit. Trust the row the parent saved.
        pass
    schedule["active_sit"] = None
    new_interval = _interval_now(state)
    if entry["kind"] == "accident":
        preserved = active.get("preserved_next_sit_at")
        if not preserved:
            schedule["running"] = False
            schedule["next_sit_at"] = None
            schedule["timer_interval_minutes"] = None
            return
        schedule["running"] = True
        schedule["timer_interval_minutes"] = active.get("preserved_timer_interval_minutes") or new_interval
        if _parse_iso(preserved) > now:
            schedule["next_sit_at"] = preserved
        else:
            schedule["next_sit_at"] = now.isoformat()
        return
    schedule["running"] = True
    schedule["timer_interval_minutes"] = new_interval
    schedule["next_sit_at"] = (now + timedelta(minutes=new_interval)).isoformat()


def _interval_now(state: dict[str, Any]) -> int:
    ordered = recompute_entries(deepcopy(state["entries"]), state["settings"])
    return current_interval(ordered, state["settings"])


def _entry_from_payload(
    state: dict[str, Any],
    payload: dict[str, Any],
    now: datetime,
    seq: int | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    kind = str(payload.get("kind") or "manual")
    if kind not in KINDS:
        raise ValueError("Kind must be scheduled, asked, accident, or manual.")
    date, time = _date_time(payload, now, state["settings"]["timezone"])
    if seq is None:
        state["seq"] = int(state.get("seq", 0)) + 1
        seq = state["seq"]
    return {
        "id": entry_id or str(uuid4()),
        "seq": seq,
        "date": date,
        "time": time,
        "kind": kind,
        "toilet_bm": _bool(payload.get("toilet_bm")),
        "toilet_urine": _bool(payload.get("toilet_urine")),
        "accident_soiled": _bool(payload.get("accident_soiled")),
        "accident_wet": _bool(payload.get("accident_wet")),
        "comment": _clean_text(payload.get("comment") or "", 500),
        "created_at": now.isoformat(),
    }


def _find(state: dict[str, Any], entry_id: str) -> dict[str, Any]:
    for entry in state["entries"]:
        if entry["id"] == entry_id:
            return entry
    raise ValueError("That row is not on the sheet.")


def _date_time(payload: dict[str, Any], now: datetime, timezone: str) -> tuple[str, str]:
    date = payload.get("date")
    time = payload.get("time")
    local = now.astimezone(ZoneInfo(timezone))
    if not date:
        date = local.date().isoformat()
    if not time:
        time = local.strftime("%H:%M")
    date = str(date)
    time = str(time)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Date must look like 2026-11-13.") from exc
    try:
        datetime.strptime(time, "%H:%M")
    except ValueError as exc:
        raise ValueError("Time must look like 10:20.") from exc
    return date, time


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", 0, "0", "false", "False", "no"):
        return False
    if value in (1, "1", "true", "True", "yes"):
        return True
    raise ValueError("Yes/no fields must be true or false.")


def _minutes(value: Any, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Intervals must be whole minutes.") from exc
    if number < low or number > high:
        raise ValueError(f"That value must be between {low} and {high} minutes.")
    return number


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if len(text) > limit:
        raise ValueError(f"That note is too long (max {limit} characters).")
    return text


def _timezone(value: Any) -> str:
    name = str(value or "").strip()
    try:
        ZoneInfo(name)
    except Exception as exc:
        raise ValueError("Timezone is not recognized.") from exc
    return name


def _day_counts(entries: list[dict[str, Any]]) -> tuple[int, int, int]:
    voids = sum(1 for entry in entries if entry.get("toilet_urine") or entry.get("toilet_bm"))
    accidents = sum(1 for entry in entries if entry.get("accident_wet") or entry.get("accident_soiled"))
    return len(entries), voids, accidents


def _local_date(now: datetime, timezone_name: str) -> str:
    try:
        return now.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        return now.date().isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def resolve_now(payload: dict[str, Any] | None, server_now: datetime) -> datetime:
    """Prefer the parent's clock when it is close to the server clock."""
    if server_now.tzinfo is None:
        server_now = server_now.replace(tzinfo=ZoneInfo("UTC"))
    raw = (payload or {}).get("now") if isinstance(payload, dict) else None
    if not raw:
        return server_now
    try:
        client = datetime.fromisoformat(str(raw))
    except ValueError:
        return server_now
    if client.tzinfo is None:
        client = client.replace(tzinfo=server_now.tzinfo)
    if abs(client - server_now) > timedelta(minutes=10):
        return server_now
    return client
