"""Build the Strands agent wired to the MCP tool server and x.ai."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from potty_train.secrets import app_secret

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Potty Log assistant for a household running a scheduled-sit potty plan.

You can read and change the live timer and data sheet through tools. Follow the practice sheet rules:

- Three dry intervals in a row, with a pee or poop on the toilet in at least one, add the step (usually 5 minutes).
- Accidents on two intervals in a row subtract the step.
- An accident sit does not reset the off-potty timer. A scheduled sit, or a sit he asked for, starts the next interval when it is saved.

Be concise and practical. Prefer tools over guessing. When you change the log, say what you did in plain language. Do not invent sheet rows or timer state.
"""


@contextmanager
def open_agent() -> Iterator[Any]:
    """Yield a configured Agent. Closes the MCP client when done."""
    from strands import Agent
    from strands.models.openai import OpenAIModel

    from potty_agent.telemetry import configure_telemetry

    configure_telemetry()

    api_key = app_secret("xai_api_key") or os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("xAI is not configured. Add xai_api_key to the app secret.")

    model_id = os.environ.get("XAI_MODEL_ID", "grok-4-1-fast-reasoning").strip()
    model = OpenAIModel(
        client_args={
            "api_key": api_key,
            "base_url": os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").strip(),
        },
        model_id=model_id,
        params={
            "max_tokens": int(os.environ.get("XAI_MAX_TOKENS", "2048")),
            "temperature": float(os.environ.get("XAI_TEMPERATURE", "0.3")),
        },
    )

    mcp_client = None
    tools: list[Any] = []
    if os.environ.get("POTTY_ENV") == "local" and not os.environ.get("MCP_FUNCTION_URL"):
        tools = _local_tools()
    else:
        mcp_client = _mcp_client()
        mcp_client.__enter__()
        tools = mcp_client.list_tools_sync()

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        callback_handler=None,
    )
    try:
        yield agent
    finally:
        if mcp_client is not None:
            try:
                mcp_client.__exit__(None, None, None)
            except Exception:
                logger.exception("Could not close MCP client.")


def _mcp_client() -> Any:
    from strands.tools.mcp import MCPClient

    url = os.environ.get("MCP_FUNCTION_URL", "").strip()
    if not url:
        raise RuntimeError("MCP_FUNCTION_URL is not configured.")

    if os.environ.get("POTTY_ENV") == "local" or url.startswith("http://127.0.0.1"):
        from mcp.client.streamable_http import streamablehttp_client

        return MCPClient(lambda: streamablehttp_client(url))

    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=url,
            aws_service="lambda",
            aws_region=region,
        )
    )


def _local_tools() -> list[Any]:
    """Register the same tool functions in-process when no MCP URL is set."""
    from strands import tool

    from potty_mcp import tools as t

    @tool
    def get_log_state() -> str:
        """Return the full public log: settings, schedule, entries, and derived streaks."""
        return t.get_log_state()

    @tool
    def get_schedule() -> str:
        """Return the live timer and active sit, plus derived streak counters."""
        return t.get_schedule()

    @tool
    def get_settings() -> str:
        """Return the household settings used by the schedule rules."""
        return t.get_settings()

    @tool
    def list_recent_entries(limit: int = 20) -> str:
        """Return the newest sheet rows."""
        return t.list_recent_entries(limit=limit)

    @tool
    def analyze_progress(days: int = 3) -> str:
        """Summarize recent progress for coaching."""
        return t.analyze_progress(days=days)

    @tool
    def start_off_potty_timer() -> str:
        """Start the off-potty countdown using the current interval."""
        return t.start_off_potty_timer()

    @tool
    def stop_off_potty_timer() -> str:
        """Stop the off-potty countdown without starting a sit."""
        return t.stop_off_potty_timer()

    @tool
    def cancel_active_sit() -> str:
        """Cancel the sit in progress and restore any preserved off-potty timer."""
        return t.cancel_active_sit()

    @tool
    def begin_sit(kind: str) -> str:
        """Start a sit. Kind is scheduled, asked, or accident."""
        return t.begin_sit(kind)

    @tool
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
        """Add a row to the data sheet."""
        return t.add_sheet_entry(
            kind=kind,
            toilet_urine=toilet_urine,
            toilet_bm=toilet_bm,
            accident_wet=accident_wet,
            accident_soiled=accident_soiled,
            comment=comment,
            date=date,
            time=time,
        )

    @tool
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
        """Update an existing sheet row by id."""
        return t.edit_sheet_entry(
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

    @tool
    def remove_sheet_entry(entry_id: str) -> str:
        """Delete a sheet row by id."""
        return t.remove_sheet_entry(entry_id)

    @tool
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
        """Update household schedule settings."""
        return t.change_settings(
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

    return [
        get_log_state,
        get_schedule,
        get_settings,
        list_recent_entries,
        analyze_progress,
        start_off_potty_timer,
        stop_off_potty_timer,
        cancel_active_sit,
        begin_sit,
        add_sheet_entry,
        edit_sheet_entry,
        remove_sheet_entry,
        change_settings,
    ]
