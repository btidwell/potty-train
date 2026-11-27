"""MCP tool coverage for schedule and sheet mutations."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from potty_mcp import tools
from potty_train.service import default_state


@pytest.fixture(autouse=True)
def _local_store(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(default_state()), encoding="utf-8")
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setenv("POTTY_STATE_PATH", str(path))
    tools._STORE = None
    yield
    tools._STORE = None


def test_get_schedule_and_start_timer():
    before = json.loads(tools.get_schedule())
    assert before["schedule"]["running"] is False

    started = json.loads(tools.start_off_potty_timer())
    assert started["ok"] is True
    assert started["state"]["schedule"]["running"] is True
    assert started["state"]["schedule"]["next_sit_at"]


def test_begin_sit_and_add_entry_resets_scheduled_interval():
    json.loads(tools.start_off_potty_timer())
    sit = json.loads(tools.begin_sit("scheduled"))
    assert sit["ok"] is True
    assert sit["state"]["schedule"]["active_sit"]["kind"] == "scheduled"

    saved = json.loads(
        tools.add_sheet_entry(
            kind="scheduled",
            toilet_urine=True,
            comment="good sit",
        )
    )
    assert saved["ok"] is True
    assert saved["state"]["schedule"]["active_sit"] is None
    assert saved["state"]["schedule"]["running"] is True
    assert len(saved["state"]["entries"]) == 1


def test_analyze_progress_counts_days():
    tools.add_sheet_entry(kind="manual", toilet_urine=True, date="2026-11-26", time="09:00")
    tools.add_sheet_entry(kind="manual", accident_wet=True, date="2026-11-26", time="10:00")
    tools.add_sheet_entry(kind="manual", toilet_bm=True, date="2026-11-27", time="09:30")

    report = json.loads(tools.analyze_progress(days=2))
    assert report["rules"]["add_step_after"]
    assert len(report["daily"]) >= 1
    assert report["daily"][0]["date"] in {"2026-11-27", "2026-11-26"}


def test_change_settings_and_conflict_message(monkeypatch):
    ok = json.loads(tools.change_settings(child_name="Theo", step_minutes=5))
    assert ok["ok"] is True
    assert ok["state"]["settings"]["child_name"] == "Theo"

    settings = json.loads(tools.get_settings())
    assert settings["child_name"] == "Theo"
