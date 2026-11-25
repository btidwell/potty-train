import json

import pytest

from potty_train.handler import handler
from potty_train.invites import normalize_email, send_invite


class InviteError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class Directory:
    def __init__(self) -> None:
        self.users: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    def admin_create_user(self, **kwargs):
        email = kwargs["Username"]
        if kwargs.get("MessageAction") == "RESEND":
            self.calls.append(("resend", email))
            return {}
        if email in self.users:
            raise InviteError("UsernameExistsException")
        self.users[email] = "FORCE_CHANGE_PASSWORD"
        self.calls.append(("create", email))
        attributes = {item["Name"]: item["Value"] for item in kwargs["UserAttributes"]}
        assert attributes["email"] == email
        assert attributes["email_verified"] == "true"
        assert kwargs["DesiredDeliveryMediums"] == ["EMAIL"]
        return {}

    def admin_get_user(self, **kwargs):
        status = self.users.get(kwargs["Username"])
        if status is None:
            raise InviteError("UserNotFoundException")
        return {"UserStatus": status}


def test_invite_email_must_look_like_an_email():
    assert normalize_email("  Person@Example.com ") == "person@example.com"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


def test_new_address_is_created(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    directory = Directory()
    assert send_invite("person@example.com", directory) == "sent"
    assert directory.calls == [("create", "person@example.com")]


def test_unfinished_invite_is_resent(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    directory = Directory()
    directory.users["person@example.com"] = "FORCE_CHANGE_PASSWORD"
    assert send_invite("person@example.com", directory) == "resent"
    assert directory.calls == [("resend", "person@example.com")]


def test_finished_account_is_not_invited_again(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    directory = Directory()
    directory.users["person@example.com"] = "CONFIRMED"
    with pytest.raises(ValueError, match="already has an account"):
        send_invite("person@example.com", directory)


def test_other_accounts_cannot_invite(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "user")
    monkeypatch.setattr("potty_train.handler.session_allows", lambda event: True)
    monkeypatch.setattr("potty_train.handler.is_owner", lambda token: False)
    result = handler(_event("user"), None)
    assert result["statusCode"] == 403


def test_owner_invite_returns_the_sent_message(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "owner")
    monkeypatch.setattr("potty_train.handler.session_allows", lambda event: True)
    monkeypatch.setattr("potty_train.handler.is_owner", lambda token: True)
    monkeypatch.setattr("potty_train.handler.send_invite", lambda email: "sent")
    result = handler(_event("owner"), None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["message"] == "Invitation sent."


def _event(token: str) -> dict:
    return {
        "httpMethod": "POST",
        "path": "/api/invites",
        "headers": {"authorization": f"Bearer {token}"},
        "body": json.dumps({"email": "person@example.com"}),
    }
