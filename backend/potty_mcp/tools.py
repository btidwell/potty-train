"""Tool implementations shared by the MCP Lambda and local agent wiring.

Each function mutates or reads the same S3-backed log the phone UI uses.
Analysis helpers summarize streaks and recent days without changing state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from potty_train.service import (
    create_entry,
    delete_entry,
    public_state,
    schedule_action,
    start_sit,
    update_entry,
    update_settings,
)
from potty_train.store import Conflict, build_store

_STORE = None


def _store():
    global _STORE
    if _STORE is None:
        _STORE = build_store()
    return _STORE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> tuple[dict[str, Any], str]:
    return _store().load()


def _save(state: dict[str, Any], etag: str) -> str:
    return _store().save(state, etag)


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def get_log_state() -> str:
    """Return the full public log: settings, schedule, entries, and derived streaks."""
    state, _etag = _load()
    return _json(public_state(state, _now()))


def get_schedule() -> str:
    """Return the live timer and active sit, plus derived streak counters."""
    state, _etag = _load()
    view = public_state(state, _now())
    return _json(
        {
            "schedule": view["schedule"],
            "derived": {
                key: view["derived"][key]
                for key in (
                    "current_interval_minutes",
                    "dry_streak",
                    "accident_streak",
                    "today",
                    "today_sits",
                    "today_voids",
                    "today_accidents",
                    "summary_label",
                    "summary_sits",
                    "summary_voids",
                    "summary_accidents",
                    "server_now",
                )
                if key in view["derived"]
            },
        }
    )


def get_settings() -> str:
    """Return the household settings used by the schedule rules."""
    state, _etag = _load()
    return _json(state["settings"])


def list_recent_entries(limit: int = 20) -> str:
    """Return the newest sheet rows.

    Args:
        limit: Maximum number of rows to return (1-100).
    """
    capped = max(1, min(int(limit), 100))
    state, _etag = _load()
    view = public_state(state, _now())
    entries = list(reversed(view["entries"]))[:capped]
    return _json({"entries": entries, "count": len(entries)})


def analyze_progress(days: int = 3) -> str:
    """Summarize recent progress for coaching.

    Counts sits, toilet voids, and accidents per day for the last N days,
    and reports the current dry and accident streaks.

    Args:
        days: How many recent calendar days to include (1-14).
    """
    window = max(1, min(int(days), 14))
    state, _etag = _load()
    view = public_state(state, _now())
    entries = view["entries"]
    by_date: dict[str, dict[str, int]] = {}
    for entry in entries:
        day = str(entry.get("date") or "")
        if not day:
            continue
        bucket = by_date.setdefault(
            day,
            {"sits": 0, "voids": 0, "accidents": 0, "dry_intervals": 0},
        )
        bucket["sits"] += 1
        if entry.get("toilet_urine") or entry.get("toilet_bm"):
            bucket["voids"] += 1
        if entry.get("accident_wet") or entry.get("accident_soiled"):
            bucket["accidents"] += 1
        else:
            bucket["dry_intervals"] += 1
    dates = sorted(by_date.keys(), reverse=True)[:window]
    daily = [{"date": day, **by_date[day]} for day in dates]
    derived = view["derived"]
    return _json(
        {
            "current_interval_minutes": derived.get("current_interval_minutes"),
            "dry_streak": derived.get("dry_streak"),
            "accident_streak": derived.get("accident_streak"),
            "step_minutes": view["settings"].get("step_minutes"),
            "rules": {
                "add_step_after": "3 dry intervals in a row with at least one toilet void",
                "subtract_step_after": "2 accident intervals in a row",
            },
            "daily": daily,
        }
    )


def start_off_potty_timer() -> str:
    """Start the off-potty countdown using the current interval."""
    return _mutate(lambda state, now: schedule_action(state, "start_timer", now))


def stop_off_potty_timer() -> str:
    """Stop the off-potty countdown without starting a sit."""
    return _mutate(lambda state, now: schedule_action(state, "stop_timer", now))


def cancel_active_sit() -> str:
    """Cancel the sit in progress and restore any preserved off-potty timer."""
    return _mutate(lambda state, now: schedule_action(state, "cancel_sit", now))


def begin_sit(kind: str) -> str:
    """Start a sit.

    Args:
        kind: One of scheduled, asked, or accident.
    """
    return _mutate(lambda state, now: start_sit(state, kind, now))


def add_sheet_entry(
    kind: str = "manual",
    toilet_urine: bool = False,
    toilet_bm: bool = False,
    accident_wet: bool = False,
    accident_soiled: bool = False,
    comment: str = "",
    date: str = "",
    time: str = "",
) -> str:
    """Add a row to the data sheet. Closing an active sit updates the timer.

    Args:
        kind: scheduled, asked, accident, or manual.
        toilet_urine: Pee on the toilet.
        toilet_bm: Poop on the toilet.
        accident_wet: Wet accident.
        accident_soiled: Soiled accident.
        comment: Optional note.
        date: Optional YYYY-MM-DD. Defaults to today in the household timezone.
        time: Optional HH:MM. Defaults to now in the household timezone.
    """
    payload: dict[str, Any] = {
        "kind": kind,
        "toilet_urine": toilet_urine,
        "toilet_bm": toilet_bm,
        "accident_wet": accident_wet,
        "accident_soiled": accident_soiled,
        "comment": comment,
    }
    if date:
        payload["date"] = date
    if time:
        payload["time"] = time

    def action(state: dict[str, Any], now: datetime) -> None:
        create_entry(state, payload, now, recorded_by="assistant")

    return _mutate(action)


def edit_sheet_entry(
    entry_id: str,
    kind: str | None = None,
    toilet_urine: bool | None = None,
    toilet_bm: bool | None = None,
    accident_wet: bool | None = None,
    accident_soiled: bool | None = None,
    comment: str | None = None,
    date: str | None = None,
    time: str | None = None,
) -> str:
    """Update an existing sheet row by id.

    Args:
        entry_id: Row id from list_recent_entries or get_log_state.
        kind: Optional new kind.
        toilet_urine: Optional pee-on-toilet flag.
        toilet_bm: Optional poop-on-toilet flag.
        accident_wet: Optional wet-accident flag.
        accident_soiled: Optional soiled-accident flag.
        comment: Optional note.
        date: Optional YYYY-MM-DD.
        time: Optional HH:MM.
    """
    payload: dict[str, Any] = {}
    if kind is not None:
        payload["kind"] = kind
    if toilet_urine is not None:
        payload["toilet_urine"] = toilet_urine
    if toilet_bm is not None:
        payload["toilet_bm"] = toilet_bm
    if accident_wet is not None:
        payload["accident_wet"] = accident_wet
    if accident_soiled is not None:
        payload["accident_soiled"] = accident_soiled
    if comment is not None:
        payload["comment"] = comment
    if date is not None:
        payload["date"] = date
    if time is not None:
        payload["time"] = time

    def action(state: dict[str, Any], now: datetime) -> None:
        update_entry(state, entry_id, payload, now)

    return _mutate(action)


def remove_sheet_entry(entry_id: str) -> str:
    """Delete a sheet row by id.

    Args:
        entry_id: Row id to remove.
    """

    def action(state: dict[str, Any], now: datetime) -> None:
        delete_entry(state, entry_id)

    return _mutate(action)


def change_settings(
    child_name: str | None = None,
    starting_interval_minutes: int | None = None,
    step_minutes: int | None = None,
    min_interval_minutes: int | None = None,
    max_interval_minutes: int | None = None,
    sit_minutes: int | None = None,
    drink_prompt_minutes: int | None = None,
    reinforcer_note: str | None = None,
    timezone: str | None = None,
) -> str:
    """Update household schedule settings. Omit fields you do not want to change.

    Args:
        child_name: Display name.
        starting_interval_minutes: Starting off-potty interval.
        step_minutes: Minutes added or subtracted by the streak rules.
        min_interval_minutes: Floor for the interval.
        max_interval_minutes: Ceiling for the interval.
        sit_minutes: How long a sit lasts.
        drink_prompt_minutes: Drink reminder offset during a sit.
        reinforcer_note: Short reinforcer reminder.
        timezone: IANA timezone name.
    """
    payload: dict[str, Any] = {}
    for key, value in {
        "child_name": child_name,
        "starting_interval_minutes": starting_interval_minutes,
        "step_minutes": step_minutes,
        "min_interval_minutes": min_interval_minutes,
        "max_interval_minutes": max_interval_minutes,
        "sit_minutes": sit_minutes,
        "drink_prompt_minutes": drink_prompt_minutes,
        "reinforcer_note": reinforcer_note,
        "timezone": timezone,
    }.items():
        if value is not None:
            payload[key] = value

    def action(state: dict[str, Any], now: datetime) -> None:
        update_settings(state, payload)

    return _mutate(action)


def _mutate(action: Any) -> str:
    try:
        state, etag = _load()
        now = _now()
        action(state, now)
        _save(state, etag)
        return _json({"ok": True, "state": public_state(state, now)})
    except Conflict:
        state, _etag = _load()
        return _json(
            {
                "ok": False,
                "error": "The log was updated from another screen. Reload and try again.",
                "state": public_state(state, _now()),
            }
        )
    except ValueError as exc:
        return _json({"ok": False, "error": str(exc)})
