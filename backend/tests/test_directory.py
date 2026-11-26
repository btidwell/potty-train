import json
from datetime import datetime, timezone

from potty_train.directory import actor_email, list_users
from potty_train.handler import handler
from potty_train.service import create_entry, default_state, public_state, update_entry

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)
CREATED = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
UPDATED = datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc)


class DirectoryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class Pool:
    def __init__(self) -> None:
        self.pages = [
            {
                "Users": [
                    _user("person", "person@example.com", "FORCE_CHANGE_PASSWORD", enabled=True),
                    _user("owner", "owner@example.com", "CONFIRMED", enabled=True),
                ],
                "PaginationToken": "next",
            },
            {
                "Users": [
                    _user("paused", "paused@example.com", "CONFIRMED", enabled=False),
                    _user("ready", "ready@example.com", "CONFIRMED", enabled=True),
                ]
            },
        ]
        self.mfa = {"owner": ["SOFTWARE_TOKEN_MFA"]}
        self.groups = {"owner": ["owners"]}
        self.verified = {"ready"}
        self.preference_calls: list[str] = []

    def list_users(self, **kwargs):
        assert kwargs["UserPoolId"] == "pool"
        page = self.pages.pop(0)
        if kwargs.get("PaginationToken"):
            assert kwargs["PaginationToken"] == "next"
        return page

    def admin_get_user(self, **kwargs):
        username = kwargs["Username"]
        if username == "missing":
            raise DirectoryError("UserNotFoundException")
        return {"UserMFASettingList": self.mfa.get(username, [])}

    def admin_list_groups_for_user(self, **kwargs):
        return {"Groups": [{"GroupName": name} for name in self.groups.get(kwargs["Username"], [])]}

    def admin_set_user_mfa_preference(self, **kwargs):
        username = kwargs["Username"]
        self.preference_calls.append(username)
        if username not in self.verified:
            raise DirectoryError("InvalidParameterException")
        self.mfa[username] = ["SOFTWARE_TOKEN_MFA"]


def test_directory_describes_each_account(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    monkeypatch.setattr(
        "potty_train.directory.sessions_by_user",
        lambda: {
            "ready": [
                {
                    "id": "session-1",
                    "label": "Safari on iPhone or iPad",
                    "created_at": CREATED.isoformat(),
                    "last_seen": UPDATED.isoformat(),
                    "ip": "198.51.100.4",
                    "remembered": True,
                }
            ]
        },
    )
    pool = Pool()
    people = list_users(pool)
    assert [person["email"] for person in people] == [
        "owner@example.com",
        "paused@example.com",
        "person@example.com",
        "ready@example.com",
    ]
    owner = people[0]
    assert owner["status"] == "active"
    assert owner["status_label"] == "Active"
    assert owner["owner"] is True
    assert owner["authenticator"] is True
    assert owner["sessions"] == []
    assert owner["created_at"] == CREATED.isoformat()
    invited = next(person for person in people if person["email"] == "person@example.com")
    assert invited["status_label"] == "Invited"
    assert invited["authenticator"] is False
    paused = next(person for person in people if person["email"] == "paused@example.com")
    assert paused["status"] == "disabled"
    assert paused["authenticator"] is False
    ready = next(person for person in people if person["email"] == "ready@example.com")
    assert ready["authenticator"] is True
    assert ready["sessions"][0]["ip"] == "198.51.100.4"
    assert ready["sessions"][0]["label"] == "Safari on iPhone or iPad"
    assert pool.preference_calls == ["paused", "ready"]


def test_a_colliding_mfa_save_uses_the_preference_the_other_save_wrote(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    monkeypatch.setattr("potty_train.directory.sessions_by_user", lambda: {})
    pool = Pool()
    pool.pages = [{"Users": [_user("ready", "ready@example.com", "CONFIRMED", enabled=True)]}]
    pool.mfa = {}

    def collide(**kwargs):
        pool.preference_calls.append(kwargs["Username"])
        pool.mfa[kwargs["Username"]] = ["SOFTWARE_TOKEN_MFA"]
        raise DirectoryError("TooManyRequestsException")

    pool.admin_set_user_mfa_preference = collide  # type: ignore[method-assign]
    people = list_users(pool)
    assert people[0]["authenticator"] is True


def test_a_colliding_mfa_save_stays_off_when_nothing_was_saved(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    monkeypatch.setattr("potty_train.directory.sessions_by_user", lambda: {})
    pool = Pool()
    pool.pages = [{"Users": [_user("ready", "ready@example.com", "CONFIRMED", enabled=True)]}]
    pool.mfa = {}

    def collide(**kwargs):
        pool.preference_calls.append(kwargs["Username"])
        raise DirectoryError("TooManyRequestsException")

    pool.admin_set_user_mfa_preference = collide  # type: ignore[method-assign]
    people = list_users(pool)
    assert people[0]["authenticator"] is False


def test_a_saved_row_names_the_account(monkeypatch):
    monkeypatch.setattr("potty_train.directory.token_username", lambda token: "owner" if token == "token" else "")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    pool = Pool()
    pool.admin_get_user = lambda **kwargs: {  # type: ignore[method-assign]
        "UserAttributes": [{"Name": "email", "Value": "owner@example.com"}]
    }
    assert actor_email("token", pool) == "owner@example.com"
    assert actor_email("", pool) == ""

    state = default_state()
    created = create_entry(
        state,
        {"date": "2026-11-25", "time": "08:15", "kind": "scheduled", "toilet_urine": True},
        NOW,
        recorded_by="owner@example.com",
    )
    update_entry(state, created["id"], {"comment": "asked for water"}, NOW)
    shown = public_state(state, NOW)["entries"][0]
    assert shown["recorded_by"] == "owner@example.com"
    assert shown["comment"] == "asked for water"


def test_other_accounts_cannot_list_people(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "user")
    monkeypatch.setattr("potty_train.handler.session_allows", lambda event: True)
    monkeypatch.setattr("potty_train.handler.is_owner", lambda token: False)
    result = handler(_event("user"), None)
    assert result["statusCode"] == 403


def test_owner_sees_the_directory(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setattr("potty_train.handler.token_is_valid", lambda token: token == "owner")
    monkeypatch.setattr("potty_train.handler.session_allows", lambda event: True)
    monkeypatch.setattr("potty_train.handler.is_owner", lambda token: True)
    monkeypatch.setattr(
        "potty_train.handler.list_users",
        lambda: [{"email": "owner@example.com", "status": "active"}],
    )
    result = handler(_event("owner"), None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["users"][0]["email"] == "owner@example.com"


def _user(username: str, email: str, status: str, enabled: bool) -> dict:
    return {
        "Username": username,
        "Enabled": enabled,
        "UserStatus": status,
        "UserCreateDate": CREATED,
        "UserLastModifiedDate": UPDATED,
        "Attributes": [{"Name": "email", "Value": email}],
    }


def _event(token: str) -> dict:
    return {
        "httpMethod": "GET",
        "path": "/api/users",
        "headers": {"authorization": f"Bearer {token}"},
    }
