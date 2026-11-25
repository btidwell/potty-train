import json
from datetime import datetime, timedelta, timezone

from potty_train.handler import handler
from potty_train.sessions import list_sessions, open_session, owns, revoke, sessions_by_user

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)


def test_a_session_is_private_to_the_account(monkeypatch, tmp_path):
    _local(monkeypatch, tmp_path)
    opened = open_session(
        "user-a",
        label="  Chrome   on   Windows  ",
        device_key="us-east-1_device",
        remembered=True,
        ip="203.0.113.9:443",
        now=NOW,
    )
    assert opened["label"] == "Chrome on Windows"
    assert opened["remembered"] is True
    assert opened["ip"] == "203.0.113.9"
    assert "device_key" not in opened
    assert owns(opened["id"], "user-a")
    assert not owns(opened["id"], "user-b")
    assert list_sessions("user-b") == []

    forgotten: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "potty_train.sessions.forget_remote_device",
        lambda username, device_key, client=None: forgotten.append((username, device_key)),
    )
    assert revoke(opened["id"], "user-b") is None
    assert owns(opened["id"], "user-a")
    assert revoke(opened["id"], "user-a")["id"] == opened["id"]
    assert forgotten == [("user-a", "us-east-1_device")]
    assert not owns(opened["id"], "user-a")


def test_same_browser_keeps_one_session(monkeypatch, tmp_path):
    _local(monkeypatch, tmp_path)
    first = open_session("user-a", label="Chrome on Windows", device_key="", remembered=False, ip="", now=NOW)
    second = open_session(
        "user-a",
        label="Chrome on Windows",
        device_key="device-1",
        remembered=True,
        ip="203.0.113.8",
        session_id=first["id"],
        now=NOW + timedelta(minutes=5),
    )
    assert second["id"] == first["id"]
    assert second["remembered"] is True
    assert len(list_sessions("user-a")) == 1
    assert sessions_by_user()["user-a"][0]["id"] == first["id"]


def test_api_rejects_a_token_without_a_session(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "user")
    monkeypatch.setattr("potty_train.handler.token_username", lambda token: "user-a")
    result = handler(_event("GET", "/api/state", "user"), None)
    assert result["statusCode"] == 401


def test_opening_a_session_lets_the_same_browser_back_in(monkeypatch, tmp_path):
    _local(monkeypatch, tmp_path)
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "user")
    monkeypatch.setattr("potty_train.handler.token_username", lambda token: "user-a")
    monkeypatch.setattr("potty_train.handler._server_now", lambda: NOW)
    created = handler(
        _event(
            "POST",
            "/api/sessions",
            "user",
            {"label": "Safari on iPhone or iPad", "device_key": "bad key", "remembered": True},
            ip="198.51.100.4, 203.0.113.1",
        ),
        None,
    )
    assert created["statusCode"] == 200
    session = json.loads(created["body"])["session"]
    assert session["remembered"] is False
    assert session["ip"] == "198.51.100.4"
    viewer = handler(
        _event(
            "POST",
            "/api/sessions",
            "user",
            {"label": "Safari on iPhone or iPad", "device_key": "", "remembered": False},
            session_id=session["id"],
            ip="2600:1005:b243:393d:6d4c:4a78:fb88:9791:58978",
            viewer=True,
        ),
        None,
    )
    assert json.loads(viewer["body"])["session"]["ip"] == "2600:1005:b243:393d:6d4c:4a78:fb88:9791"
    listed = handler(_event("GET", "/api/sessions", "user", session_id=session["id"]), None)
    assert listed["statusCode"] == 200
    assert json.loads(listed["body"])["sessions"][0]["id"] == session["id"]
    revoked = handler(_event("DELETE", f"/api/sessions/{session['id']}", "user", session_id=session["id"]), None)
    assert revoked["statusCode"] == 200
    blocked = handler(_event("GET", "/api/sessions", "user", session_id=session["id"]), None)
    assert blocked["statusCode"] == 401


def _local(monkeypatch, tmp_path):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setenv("POTTY_SESSIONS_PATH", str(tmp_path / "sessions.json"))


def _event(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
    session_id: str = "",
    ip: str = "",
    viewer: bool = False,
) -> dict:
    headers = {"x-potty-authorization": f"Bearer {token}"}
    if session_id:
        headers["x-potty-session"] = session_id
    if ip:
        headers["cloudfront-viewer-address" if viewer else "x-forwarded-for"] = ip
    return {
        "httpMethod": method,
        "path": path,
        "headers": headers,
        "body": json.dumps(body or {}),
    }
