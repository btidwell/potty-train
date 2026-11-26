import base64
import json
import re
import zlib
from datetime import datetime, timezone

from potty_train.handler import handler
from potty_train.rules import recompute_entries
from potty_train.service import create_entry, default_state
from potty_train.sheet_pdf import paper_comment, render_log_pdf

NOW = datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)


def test_sheet_comments_follow_the_practice_marks():
    state = default_state()
    _sit(state, "11:35", urine=False)
    _sit(state, "11:55", urine=False)
    _sit(state, "12:15", urine=False)
    _sit(state, "12:40", urine=False, wet=True)
    _sit(state, "13:00", urine=True)
    _sit(state, "13:20", urine=False)
    _sit(state, "13:40", urine=False)
    ordered = recompute_entries(state["entries"], state["settings"])
    assert paper_comment(ordered[2]) == "keep interval same"
    assert paper_comment(ordered[3]) == ""
    assert paper_comment(ordered[6]) == "increase 5 min"
    assert ordered[6]["interval_minutes"] == 15


def test_a_written_comment_stays_with_the_interval_note():
    state = default_state()
    _sit(state, "08:00", urine=False, wet=True)
    _sit(state, "08:20", urine=False, wet=True, comment="Soiled pull-up \u2014 nap")
    ordered = recompute_entries(state["entries"], state["settings"])
    assert paper_comment(ordered[1]) == "decrease 5 min - Soiled pull-up \u2014 nap"
    payload = render_log_pdf(state["entries"], state["settings"])
    assert b"Soiled pull-up - nap" in _pdf_text(payload)


def test_pdf_contains_the_filled_sheet():
    state = default_state()
    state["settings"]["child_name"] = "Sam"
    _sit(state, "11:35", urine=True, comment="Wake up")
    payload = render_log_pdf(state["entries"], state["settings"])
    text = _pdf_text(payload)
    assert payload.startswith(b"%PDF")
    assert b"Wake up" in text
    assert b"11-21-26" in text
    assert b"Y(BM)" in text or b"Y\\(BM\\)" in text
    assert b"Good luck" in text
    assert b"Sam" in text
    assert b"/Type /Page" in payload


def test_a_long_log_continues_on_the_next_page():
    state = default_state()
    for index in range(40):
        hour, minute = divmod(index * 20, 60)
        _sit(state, f"{hour % 24:02d}:{minute:02d}", urine=index % 5 == 0, date="2026-11-21")
    payload = render_log_pdf(state["entries"], state["settings"])
    pages = payload.count(b"/Type /Page") - payload.count(b"/Type /Pages")
    assert pages == 2
    assert b"2 / 2" in _pdf_text(payload)


def test_export_route_downloads_a_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setenv("POTTY_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("POTTY_SESSIONS_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setattr("potty_train.handler._STORE", None)
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "user")
    monkeypatch.setattr("potty_train.handler.token_username", lambda token: "user-a")
    opened = handler(_event("POST", "/api/sessions", "user", {"label": "Chrome on Windows"}), None)
    session_id = json.loads(opened["body"])["session"]["id"]
    result = handler(_event("GET", "/api/export.pdf", "user", session_id=session_id), None)
    assert result["statusCode"] == 200
    assert result["isBase64Encoded"] is True
    assert result["headers"]["Content-Type"] == "application/pdf"
    assert "potty-log.pdf" in result["headers"]["Content-Disposition"]
    body = base64.b64decode(result["body"])
    assert body.startswith(b"%PDF")
    assert b"Good luck" in _pdf_text(body)


def _sit(state, time, urine, wet=False, soiled=False, comment="", date="2026-11-21"):
    create_entry(
        state,
        {
            "date": date,
            "time": time,
            "kind": "manual",
            "toilet_urine": urine,
            "toilet_bm": False,
            "accident_wet": wet,
            "accident_soiled": soiled,
            "comment": comment,
        },
        NOW,
    )


def _pdf_text(payload: bytes) -> bytes:
    parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", payload, re.S):
        raw = match.group(1)
        try:
            parts.append(zlib.decompress(raw))
        except zlib.error:
            parts.append(raw)
    return b"\n".join(parts)


def _event(method, path, token, body=None, session_id=""):
    headers = {"x-potty-authorization": f"Bearer {token}"}
    if session_id:
        headers["x-potty-session"] = session_id
    return {"httpMethod": method, "path": path, "headers": headers, "body": json.dumps(body or {})}
