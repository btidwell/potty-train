"""Lambda entrypoint for the potty-log MCP tool server.

The agent Lambda calls this over a Function URL with IAM SigV4. Locally the
same handler is mounted at /mcp by local_server.py.
"""

from __future__ import annotations

from typing import Any

from awslabs.mcp_lambda_handler import MCPLambdaHandler

from potty_mcp import tools

mcp = MCPLambdaHandler(name="potty-log", version="1.0.0")


@mcp.tool()
def get_log_state() -> str:
    """Return the full public log: settings, schedule, entries, and derived streaks."""
    return tools.get_log_state()


@mcp.tool()
def get_schedule() -> str:
    """Return the live timer and active sit, plus derived streak counters."""
    return tools.get_schedule()


@mcp.tool()
def get_settings() -> str:
    """Return the household settings used by the schedule rules."""
    return tools.get_settings()


@mcp.tool()
def list_recent_entries(limit: int = 20) -> str:
    """Return the newest sheet rows.

    Args:
        limit: Maximum number of rows to return (1-100).
    """
    return tools.list_recent_entries(limit=limit)


@mcp.tool()
def analyze_progress(days: int = 3) -> str:
    """Summarize recent progress for coaching.

    Args:
        days: How many recent calendar days to include (1-14).
    """
    return tools.analyze_progress(days=days)


@mcp.tool()
def start_off_potty_timer() -> str:
    """Start the off-potty countdown using the current interval."""
    return tools.start_off_potty_timer()


@mcp.tool()
def stop_off_potty_timer() -> str:
    """Stop the off-potty countdown without starting a sit."""
    return tools.stop_off_potty_timer()


@mcp.tool()
def cancel_active_sit() -> str:
    """Cancel the sit in progress and restore any preserved off-potty timer."""
    return tools.cancel_active_sit()


@mcp.tool()
def begin_sit(kind: str) -> str:
    """Start a sit.

    Args:
        kind: One of scheduled, asked, or accident.
    """
    return tools.begin_sit(kind)


@mcp.tool()
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
    return tools.add_sheet_entry(
        kind=kind,
        toilet_urine=toilet_urine,
        toilet_bm=toilet_bm,
        accident_wet=accident_wet,
        accident_soiled=accident_soiled,
        comment=comment,
        date=date,
        time=time,
    )


@mcp.tool()
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
    return tools.edit_sheet_entry(
        entry_id=entry_id,
        kind=kind,
        toilet_urine=toilet_urine,
        toilet_bm=toilet_bm,
        accident_wet=accident_wet,
        accident_soiled=accident_soiled,
        comment=comment,
        date=date,
        time=time,
    )


@mcp.tool()
def remove_sheet_entry(entry_id: str) -> str:
    """Delete a sheet row by id.

    Args:
        entry_id: Row id to remove.
    """
    return tools.remove_sheet_entry(entry_id)


@mcp.tool()
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
    return tools.change_settings(
        child_name=child_name,
        starting_interval_minutes=starting_interval_minutes,
        step_minutes=step_minutes,
        min_interval_minutes=min_interval_minutes,
        max_interval_minutes=max_interval_minutes,
        sit_minutes=sit_minutes,
        drink_prompt_minutes=drink_prompt_minutes,
        reinforcer_note=reinforcer_note,
        timezone=timezone,
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return mcp.handle_request(event, context)
