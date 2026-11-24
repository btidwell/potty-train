"""Off-potty interval rules from the training data sheet.

The sheet footnotes are the rule this tracker follows:

* Stay dry for 3 consecutive intervals AND void on the toilet during at
  least one of those intervals -> increase the off-potty interval by one step.
* An accident in 2 consecutive intervals -> decrease by one step.

A successful void on the same row as an accident does not count as a dry
interval. The accident streak resets when a decrease is applied, so the
interval does not keep dropping on every later accident. The dry streak
resets when an increase is applied, so one good window does not raise the
interval on every following dry sit.

A row can pin logged_interval to the number written on the paper log.
Those pins are kept even when they disagree with the rule. Zero is the
first sit after a pull-up comes off (naps, sleep, leaving the house). It
stays on the sheet and does not move the clock or either streak.
"""

from __future__ import annotations

from typing import Any

Decision = str  # "increase" | "decrease" | "same"


def is_accident(entry: dict[str, Any]) -> bool:
    return bool(entry.get("accident_wet") or entry.get("accident_soiled"))


def has_toilet_void(entry: dict[str, Any]) -> bool:
    return bool(entry.get("toilet_urine") or entry.get("toilet_bm"))


def clamp_interval(minutes: int, settings: dict[str, Any]) -> int:
    low = int(settings["min_interval_minutes"])
    high = int(settings["max_interval_minutes"])
    return max(low, min(high, minutes))


def recompute_entries(entries: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fill interval_minutes and decision fields in chronological order."""
    ordered = sorted(entries, key=lambda item: (item["date"], item["time"], item.get("seq", 0)))
    interval = int(settings["starting_interval_minutes"])
    step = int(settings["step_minutes"])
    dry_streak = 0
    dry_has_void = False
    accident_streak = 0

    for index, entry in enumerate(ordered):
        logged = _logged_minutes(entry)
        if logged == 0:
            entry["interval_minutes"] = 0
            entry["decision"] = "same"
            entry["decision_note"] = ""
            entry["dry_streak_after"] = dry_streak
            entry["accident_streak_after"] = accident_streak
            entry["dry_streak_has_void"] = dry_has_void
            continue

        accident = is_accident(entry)
        void = has_toilet_void(entry)
        if logged is None:
            shown = interval
            decision, blocked, interval, dry_streak, dry_has_void, accident_streak = _advance(
                shown, accident, void, dry_streak, dry_has_void, accident_streak, step, settings
            )
        else:
            shown = logged
            written_next = _next_positive_logged(ordered, index)
            if written_next is None:
                dry_streak, dry_has_void, accident_streak = _observe(
                    accident, void, dry_streak, dry_has_void, accident_streak
                )
                decision = "same"
                blocked = ""
                interval = shown
            else:
                decision, blocked, _rule_interval, dry_streak, dry_has_void, accident_streak = _advance(
                    shown, accident, void, dry_streak, dry_has_void, accident_streak, step, settings
                )
                if written_next > shown:
                    decision = "increase"
                    blocked = ""
                    dry_streak = 0
                    dry_has_void = False
                elif written_next < shown:
                    decision = "decrease"
                    blocked = ""
                    accident_streak = 0
                else:
                    decision = "same"
                    blocked = ""
                interval = written_next

        entry["interval_minutes"] = shown
        entry["decision"] = decision
        entry["decision_note"] = _note(decision, step, blocked)
        entry["dry_streak_after"] = dry_streak
        entry["accident_streak_after"] = accident_streak
        entry["dry_streak_has_void"] = dry_has_void

    return ordered


def streak_status(entries: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    ordered = recompute_entries([dict(item) for item in entries], settings)
    if ordered:
        last = ordered[-1]
        dry_streak = int(last["dry_streak_after"])
        accident_streak = int(last["accident_streak_after"])
        dry_has_void = bool(last["dry_streak_has_void"])
    else:
        dry_streak = 0
        accident_streak = 0
        dry_has_void = False

    interval = current_interval(ordered, settings)
    return {
        "current_interval_minutes": interval,
        "dry_streak": dry_streak,
        "dry_needed": 3,
        "dry_streak_has_void": dry_has_void,
        "accident_streak": accident_streak,
        "accident_needed": 2,
        "rule_status": describe_status(dry_streak, dry_has_void, accident_streak, interval, settings),
    }


def current_interval(ordered_entries: list[dict[str, Any]], settings: dict[str, Any]) -> int:
    if not ordered_entries:
        return int(settings["starting_interval_minutes"])
    last = None
    for entry in reversed(ordered_entries):
        if int(entry["interval_minutes"]) > 0:
            last = entry
            break
    if last is None:
        return int(settings["starting_interval_minutes"])
    interval = int(last["interval_minutes"])
    step = int(settings["step_minutes"])
    if last["decision"] == "increase":
        return clamp_interval(interval + step, settings)
    if last["decision"] == "decrease":
        return clamp_interval(interval - step, settings)
    return interval


def describe_status(
    dry_streak: int,
    dry_has_void: bool,
    accident_streak: int,
    interval: int,
    settings: dict[str, Any],
) -> str:
    step = int(settings["step_minutes"])
    if accident_streak == 1:
        return (
            f"One accident in the current streak. One more accident on the next interval "
            f"lowers the off-potty time by {step} minutes."
        )
    if dry_streak <= 0:
        return (
            f"Off-potty interval is {interval} minutes. "
            f"Three dry intervals in a row, with a pee or poop on the toilet in at least one of them, "
            f"raises it by {step} minutes."
        )
    void_bit = "A toilet void is already in this streak." if dry_has_void else "Still needs a pee or poop on the toilet."
    remaining = max(0, 3 - dry_streak)
    if remaining == 0 and not dry_has_void:
        return (
            f"{dry_streak} dry intervals in a row, but none of them had a toilet void, "
            f"so the off-potty interval stays {interval} minutes."
        )
    if remaining == 0:
        return f"Dry streak is ready to raise the interval by {step} minutes."
    noun = "dry interval" if remaining == 1 else "dry intervals"
    return f"Dry streak {dry_streak} of 3. {void_bit} {remaining} more {noun} to raise it by {step} minutes."


def _logged_minutes(entry: dict[str, Any]) -> int | None:
    if "logged_interval" not in entry or entry["logged_interval"] is None:
        return None
    return int(entry["logged_interval"])


def _next_positive_logged(ordered: list[dict[str, Any]], index: int) -> int | None:
    """Next paper interval. A 0 sits between rows and is skipped. An unlogged row ends the pin."""
    for later in ordered[index + 1 :]:
        logged = _logged_minutes(later)
        if logged is None:
            return None
        if logged > 0:
            return logged
    return None


def _observe(
    accident: bool,
    void: bool,
    dry_streak: int,
    dry_has_void: bool,
    accident_streak: int,
) -> tuple[int, bool, int]:
    if accident:
        return 0, False, accident_streak + 1
    dry_streak += 1
    if void:
        dry_has_void = True
    return dry_streak, dry_has_void, 0


def _advance(
    shown: int,
    accident: bool,
    void: bool,
    dry_streak: int,
    dry_has_void: bool,
    accident_streak: int,
    step: int,
    settings: dict[str, Any],
) -> tuple[Decision, str, int, int, bool, int]:
    dry_streak, dry_has_void, accident_streak = _observe(
        accident, void, dry_streak, dry_has_void, accident_streak
    )
    decision: Decision = "same"
    blocked = ""
    nxt = shown
    if accident and accident_streak >= 2:
        floored = clamp_interval(shown - step, settings)
        if floored < shown:
            decision = "decrease"
            nxt = floored
            accident_streak = 0
        else:
            blocked = "minimum"
            accident_streak = 0
    elif not accident and dry_streak >= 3 and dry_has_void:
        capped = clamp_interval(shown + step, settings)
        if capped > shown:
            decision = "increase"
            nxt = capped
            dry_streak = 0
            dry_has_void = False
        else:
            blocked = "maximum"
            dry_streak = 0
            dry_has_void = False
    return decision, blocked, nxt, dry_streak, dry_has_void, accident_streak


def _note(decision: Decision, step: int, blocked: str) -> str:
    if decision == "increase":
        return f"increase {step} min"
    if decision == "decrease":
        return f"decrease {step} min"
    if blocked == "minimum":
        return f"stayed at minimum"
    if blocked == "maximum":
        return f"stayed at maximum"
    return ""
