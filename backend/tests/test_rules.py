import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from potty_train.rules import streak_status
from potty_train.service import (
    create_entry,
    default_state,
    delete_entry,
    public_state,
    schedule_action,
    start_sit,
    update_entry,
)

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)

# The practice sheet: interval on the row, then the mark written after that row.
PRACTICE = [
    (False, True, 15, "same"),
    (False, False, 15, "same"),
    (False, False, 15, "same"),
    (True, False, 15, "increase"),
    (False, True, 20, "same"),
    (False, False, 20, "same"),
    (False, False, 20, "same"),
    (False, True, 20, "same"),  # soiled, coded below as wet=False soiled=True via flag
    (False, True, 20, "decrease"),
    (False, True, 15, "same"),
    (False, False, 15, "same"),
    (False, False, 15, "same"),
    (False, False, 15, "same"),
    (True, False, 15, "increase"),
]


def _log(state, index, urine, accident, soiled=False):
    moment = NOW + timedelta(minutes=index)
    create_entry(
        state,
        {
            "date": "2026-11-13",
            "time": moment.strftime("%H:%M"),
            "kind": "manual",
            "toilet_urine": urine,
            "toilet_bm": False,
            "accident_wet": accident and not soiled,
            "accident_soiled": soiled,
            "now": moment.isoformat(),
        },
        moment,
    )


def test_header_uses_today_or_the_latest_logged_day():
    state = default_state()
    empty = public_state(state, NOW)
    assert empty["derived"]["summary_label"] == "today"
    assert empty["derived"]["summary_sits"] == 0
    assert empty["derived"]["today_sits"] == 0

    create_entry(
        state,
        {
            "date": "2026-01-23",
            "time": "18:20",
            "kind": "manual",
            "toilet_urine": True,
            "toilet_bm": False,
            "accident_wet": False,
            "accident_soiled": False,
        },
        NOW,
    )
    create_entry(
        state,
        {
            "date": "2026-01-24",
            "time": "08:40",
            "kind": "manual",
            "toilet_urine": True,
            "toilet_bm": False,
            "accident_wet": False,
            "accident_soiled": False,
            "logged_interval": 0,
        },
        NOW,
    )
    create_entry(
        state,
        {
            "date": "2026-01-24",
            "time": "12:00",
            "kind": "manual",
            "toilet_urine": True,
            "toilet_bm": True,
            "accident_wet": False,
            "accident_soiled": True,
        },
        NOW,
    )
    older = public_state(state, NOW)
    assert older["derived"]["today"] == "2026-11-13"
    assert older["derived"]["today_sits"] == 0
    assert older["derived"]["summary_label"] == "2026-01-24"
    assert older["derived"]["summary_sits"] == 2
    assert older["derived"]["summary_voids"] == 2
    assert older["derived"]["summary_accidents"] == 1

    create_entry(
        state,
        {
            "date": "2026-11-13",
            "time": "10:00",
            "kind": "manual",
            "toilet_urine": False,
            "toilet_bm": False,
            "accident_wet": True,
            "accident_soiled": False,
        },
        NOW,
    )
    current = public_state(state, NOW)
    assert current["derived"]["summary_label"] == "today"
    assert current["derived"]["summary_sits"] == 1
    assert current["derived"]["summary_voids"] == 0
    assert current["derived"]["summary_accidents"] == 1
    assert current["derived"]["today_sits"] == 1


def test_practice_sheet_interval_changes():
    state = default_state()
    # Row 8 on the sheet is a soiled accident between dry sits, not a wet one.
    soiled_index = 7
    for index, (urine, accident, interval, decision) in enumerate(PRACTICE):
        _log(state, index, urine, accident, soiled=(index == soiled_index))
        view = public_state(state, NOW)
        row = view["entries"][index]
        assert row["interval_minutes"] == interval, (index, row)
        assert row["decision"] == decision, (index, row)
    assert view["derived"]["current_interval_minutes"] == 20


def test_three_dry_without_a_void_does_not_increase():
    state = default_state()
    for index in range(3):
        _log(state, index, urine=False, accident=False)
    view = public_state(state, NOW)
    assert view["derived"]["current_interval_minutes"] == 15
    assert "toilet void" in view["derived"]["rule_status"]


def test_accident_plus_void_counts_as_an_accident():
    state = default_state()
    _log(state, 0, urine=False, accident=False)
    _log(state, 1, urine=False, accident=False)
    create_entry(
        state,
        {
            "date": "2026-11-13",
            "time": "15:10",
            "kind": "accident",
            "toilet_urine": True,
            "toilet_bm": False,
            "accident_wet": True,
            "accident_soiled": False,
        },
        NOW,
    )
    view = public_state(state, NOW)
    assert view["entries"][-1]["decision"] == "same"
    assert view["derived"]["dry_streak"] == 0
    assert view["derived"]["accident_streak"] == 1


def test_delete_recomputes_later_intervals():
    state = default_state()
    for index, (urine, accident, _interval, _decision) in enumerate(PRACTICE[:4]):
        _log(state, index, urine, accident)
    void_id = state["entries"][-1]["id"]
    assert public_state(state, NOW)["derived"]["current_interval_minutes"] == 20
    delete_entry(state, void_id)
    view = public_state(state, NOW)
    assert view["derived"]["current_interval_minutes"] == 15
    assert all(row["decision"] == "same" for row in view["entries"])


def test_minimum_interval_holds():
    state = default_state()
    state["settings"]["starting_interval_minutes"] = 5
    _log(state, 0, urine=False, accident=True)
    _log(state, 1, urine=False, accident=True)
    view = public_state(state, NOW)
    assert view["derived"]["current_interval_minutes"] == 5
    assert view["entries"][-1]["decision_note"] == "stayed at minimum"


def test_streak_status_matches_public_view():
    state = default_state()
    _log(state, 0, urine=True, accident=False)
    status = streak_status(state["entries"], state["settings"])
    assert status["dry_streak"] == 1
    assert status["dry_streak_has_void"] is True


def test_start_timer_does_not_restart_a_running_timer():
    state = default_state()
    schedule_action(state, "start_timer", NOW)
    original = state["schedule"]["next_sit_at"]
    with pytest.raises(ValueError, match="already running"):
        schedule_action(state, "start_timer", NOW + timedelta(minutes=4))
    assert state["schedule"]["running"] is True
    assert state["schedule"]["next_sit_at"] == original


def test_accident_sit_does_not_reset_the_timer():
    state = default_state()
    schedule_action(state, "start_timer", NOW)
    original = state["schedule"]["next_sit_at"]
    later = NOW + timedelta(minutes=4)
    start_sit(state, "accident", later)
    create_entry(
        state,
        {
            "date": "2026-11-13",
            "time": "10:04",
            "kind": "accident",
            "toilet_urine": False,
            "accident_wet": True,
            "now": later.isoformat(),
        },
        later,
    )
    assert state["schedule"]["active_sit"] is None
    assert state["schedule"]["next_sit_at"] == original


def test_cancel_sit_from_ready_returns_to_ready():
    state = default_state()
    start_sit(state, "scheduled", NOW)
    schedule_action(state, "cancel_sit", NOW + timedelta(minutes=1))
    assert state["schedule"]["active_sit"] is None
    assert state["schedule"]["running"] is False
    assert state["schedule"]["next_sit_at"] is None
    assert state["schedule"]["timer_interval_minutes"] is None


def test_cancel_sit_restores_the_running_off_timer():
    for kind in ("scheduled", "asked", "accident"):
        state = default_state()
        schedule_action(state, "start_timer", NOW)
        original = state["schedule"]["next_sit_at"]
        interval = state["schedule"]["timer_interval_minutes"]
        start_sit(state, kind, NOW + timedelta(minutes=4))
        schedule_action(state, "cancel_sit", NOW + timedelta(minutes=6))
        assert state["schedule"]["running"] is True, kind
        assert state["schedule"]["next_sit_at"] == original, kind
        assert state["schedule"]["timer_interval_minutes"] == interval, kind
        assert state["schedule"]["active_sit"] is None, kind

        state = default_state()
        schedule_action(state, "start_timer", NOW)
        original = state["schedule"]["next_sit_at"]
        start_sit(state, kind, NOW + timedelta(minutes=4))
        schedule_action(state, "cancel_sit", NOW + timedelta(minutes=30))
        assert state["schedule"]["running"] is True, kind
        assert state["schedule"]["next_sit_at"] == original, kind
        assert state["schedule"]["active_sit"] is None, kind


def test_scheduled_sit_starts_the_next_interval():
    state = default_state()
    start_sit(state, "scheduled", NOW)
    create_entry(
        state,
        {
            "kind": "scheduled",
            "toilet_urine": True,
            "date": "2026-11-13",
            "time": "10:05",
        },
        NOW + timedelta(minutes=5),
    )
    expected = (NOW + timedelta(minutes=5 + 15)).isoformat()
    assert state["schedule"]["next_sit_at"] == expected
    assert state["schedule"]["timer_interval_minutes"] == 15


def test_pullup_sit_does_not_move_the_interval_or_the_streaks():
    state = default_state()
    state["settings"]["starting_interval_minutes"] = 20
    rows = [
        (20, False, False, False),
        (0, True, False, False),
        (20, False, False, False),
        (20, True, False, False),
    ]
    for index, (logged, urine, wet, soiled) in enumerate(rows):
        state["seq"] = index + 1
        state["entries"].append(
            {
                "id": f"row-{index}",
                "seq": index + 1,
                "date": "2026-01-22",
                "time": f"08:{20 + index:02d}",
                "kind": "manual",
                "toilet_bm": False,
                "toilet_urine": urine,
                "accident_soiled": soiled,
                "accident_wet": wet,
                "comment": "",
                "created_at": NOW.isoformat(),
                "logged_interval": logged,
            }
        )
    view = public_state(state, NOW)
    assert [row["interval_minutes"] for row in view["entries"]] == [20, 0, 20, 20]
    assert view["entries"][1]["dry_streak_after"] == 1
    assert view["entries"][1]["dry_streak_has_void"] is False
    assert view["entries"][2]["dry_streak_after"] == 2
    assert view["entries"][2]["dry_streak_has_void"] is False
    assert view["entries"][3]["decision"] == "same"
    assert view["derived"]["dry_streak"] == 3
    assert view["derived"]["dry_streak_has_void"] is True
    assert view["derived"]["current_interval_minutes"] == 20


def test_preload_csv_keeps_every_recorded_interval():
    state = _state_from_preload_csv()
    view = public_state(state, NOW)
    recorded = _preload_rows()
    assert len(view["entries"]) == len(recorded)
    for entry, row in zip(view["entries"], recorded):
        assert entry["interval_minutes"] == row["recorded"], (entry["date"], entry["time"], entry, row)
        assert entry["toilet_urine"] is row["toilet_urine"]
        assert entry["toilet_bm"] is row["toilet_bm"]
        assert entry["accident_wet"] is row["accident_wet"]
        assert entry["accident_soiled"] is row["accident_soiled"]
    stayed = next(entry for entry in view["entries"] if entry["date"] == "2026-01-21" and entry["time"] == "18:00")
    assert stayed["interval_minutes"] == 20
    assert stayed["decision"] == "same"
    pullups = [entry for entry in view["entries"] if entry["interval_minutes"] == 0]
    assert len(pullups) == 3
    assert view["derived"]["current_interval_minutes"] == 45
    assert view["derived"]["accident_streak"] == 1
    assert view["derived"]["dry_streak"] == 0

    edited = update_entry(
        state,
        state["entries"][0]["id"],
        {"comment": "checked"},
        NOW,
    )
    assert edited["logged_interval"] == 15
    assert public_state(state, NOW)["entries"][0]["interval_minutes"] == 15

    create_entry(
        state,
        {
            "date": "2026-01-24",
            "time": "12:45",
            "kind": "manual",
            "toilet_urine": False,
            "toilet_bm": False,
            "accident_wet": True,
            "accident_soiled": False,
        },
        NOW,
    )
    after = public_state(state, NOW)
    assert after["entries"][-1]["interval_minutes"] == 45
    assert after["entries"][-1]["decision"] == "decrease"
    assert after["derived"]["current_interval_minutes"] == 40


def _preload_rows():
    path = Path(__file__).resolve().parent / "fixtures" / "preload.csv"
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            voids = raw["Toile Voids (BM=Boul movement U=Urine N=Nothing)"].upper().replace(" ", "")
            accident = raw["Accident (S=Soil W=Wet)"].strip().upper()
            date = datetime.strptime(raw["Date"], "%m/%d/%Y").date().isoformat()
            hour, minute = raw["Time"].split(":")
            rows.append(
                {
                    "date": date,
                    "time": f"{int(hour):02d}:{int(minute):02d}",
                    "recorded": int(raw["Off-Potty Interval (in Minutes)"]),
                    "toilet_bm": "BM" in voids,
                    "toilet_urine": voids == "U" or voids.startswith("U") or ",U" in voids,
                    "accident_wet": "W" in accident,
                    "accident_soiled": "S" in accident,
                    "comment": raw["Comments"].strip(),
                }
            )
    return rows


def _state_from_preload_csv():
    state = default_state()
    for index, row in enumerate(_preload_rows(), start=1):
        state["entries"].append(
            {
                "id": f"preload-{index}",
                "seq": index,
                "date": row["date"],
                "time": row["time"],
                "kind": "manual",
                "toilet_bm": row["toilet_bm"],
                "toilet_urine": row["toilet_urine"],
                "accident_soiled": row["accident_soiled"],
                "accident_wet": row["accident_wet"],
                "comment": row["comment"],
                "created_at": f"{row['date']}T{row['time']}:00-05:00",
                "logged_interval": row["recorded"],
            }
        )
    state["seq"] = len(state["entries"])
    return state
