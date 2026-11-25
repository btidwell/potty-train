import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPushException

import potty_train.auth as auth
import potty_train.handler as handler_mod
import potty_train.push as push
from potty_train.auth import issue_token
from potty_train.handler import handler
from potty_train.push import PushFailed, application_server_key
from potty_train.reminders import sync_reminders
from potty_train.service import default_state, public_state
from potty_train.store import FileStore

START = datetime(2026, 11, 25, 2, 15, tzinfo=timezone.utc)
OFF_DUE = "2026-11-25T02:30:00+00:00"


class AwsError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class FakeScheduler:
    def __init__(self) -> None:
        self.schedules: dict[str, dict] = {}
        self.created: list[str] = []
        self.updated: list[str] = []
        self.deleted: list[str] = []
        self.delete_attempts: list[str] = []

    def create_schedule(self, **kwargs):
        name = kwargs["Name"]
        if name in self.schedules:
            raise AwsError("ConflictException")
        self.schedules[name] = kwargs
        self.created.append(name)

    def update_schedule(self, **kwargs):
        name = kwargs["Name"]
        if name not in self.schedules:
            raise AwsError("ResourceNotFoundException")
        self.schedules[name] = kwargs
        self.updated.append(name)

    def delete_schedule(self, Name, GroupName="default"):
        self.delete_attempts.append(Name)
        if Name not in self.schedules:
            raise AwsError("ResourceNotFoundException")
        del self.schedules[Name]
        self.deleted.append(Name)


class App:
    def __init__(self, path: Path, scheduler: FakeScheduler, pushes: list[dict]) -> None:
        self.path = path
        self.scheduler = scheduler
        self.pushes = pushes
        self.clock = {"now": START}
        self.token = issue_token("test-key")

    def now(self) -> datetime:
        return self.clock["now"]

    def headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.token}",
            "x-potty-origin": "origin-secret",
        }

    def invoke(self, method: str, path: str, body: dict | None = None):
        result = handler(
            {
                "httpMethod": method,
                "path": path,
                "headers": self.headers(),
                "body": "{}" if body is None else json.dumps(body),
            },
            None,
        )
        payload = json.loads(result["body"]) if result.get("body") else {}
        return result["statusCode"], payload

    def remind(self, reminder: dict):
        return handler({"reminder": reminder}, None)

    def subscribe(self, endpoint: str = "https://push.example/device"):
        status, body = self.invoke(
            "POST",
            "/api/push/subscribe",
            {"endpoint": endpoint, "keys": {"p256dh": "p256", "auth": "auth"}},
        )
        assert status == 200, body
        return body

    def stored(self) -> dict:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw.pop("_rev", None)
        return raw


def _pem_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private, public


@pytest.fixture
def app(monkeypatch, tmp_path):
    private, public = _pem_pair()
    path = tmp_path / "state.json"
    scheduler = FakeScheduler()
    pushes: list[dict] = []
    clock = {"now": START}

    monkeypatch.setenv("POTTY_ENV", "test")
    monkeypatch.setenv("POTTY_ORIGIN_SECRET", "origin-secret")
    monkeypatch.setenv("SCHEDULER_ROLE_ARN", "arn:aws:iam::143977713810:role/potty-log-scheduler")
    monkeypatch.setenv("SCHEDULE_TARGET_ARN", "arn:aws:lambda:us-east-1:143977713810:function:potty-log-api")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")
    monkeypatch.setenv("POTTY_VAPID_PRIVATE_PEM", private)
    monkeypatch.setenv("POTTY_VAPID_PUBLIC_PEM", public)
    monkeypatch.delenv("VAPID_SECRET_ARN", raising=False)
    push._CACHE["loaded_at"] = 0.0
    push._CACHE["material"] = None
    handler_mod._STORE = FileStore(str(path))
    monkeypatch.setattr(handler_mod, "load_secret", lambda: {"password": "pw", "token_key": "test-key"})
    monkeypatch.setattr(handler_mod, "_server_now", lambda: clock["now"])
    monkeypatch.setattr("potty_train.reminders._client", lambda: scheduler)

    def fake_webpush(**kwargs):
        pushes.append(kwargs)
        return None

    monkeypatch.setattr(push, "webpush", fake_webpush)
    built = App(path, scheduler, pushes)
    built.clock = clock
    return built


def test_application_server_key_is_the_uncompressed_point():
    _private, public = _pem_pair()
    encoded = application_server_key(public)
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    assert raw[0] == 4
    assert len(raw) == 65
    Vapid.from_pem(_private.encode())


def test_public_state_omits_subscriptions():
    push._CACHE["loaded_at"] = 0.0
    push._CACHE["material"] = None
    state = default_state()
    state["push_subscriptions"] = [
        {"endpoint": "https://push.example/secret", "keys": {"p256dh": "p", "auth": "a"}}
    ]
    state["reminders"] = {"off_sent_for": "2026-11-25T02:30:00+00:00", "off_scheduled_for": "x"}
    view = public_state(state, START)
    assert "push_subscriptions" not in view
    assert "reminders" not in view
    assert "https://push.example/secret" not in json.dumps(view)
    assert set(view["push"]) == {
        "public_key",
        "off_sent_for",
        "sit_sent_for",
        "off_scheduled_for",
        "sit_scheduled_for",
    }
    assert view["push"]["off_sent_for"] == "2026-11-25T02:30:00+00:00"
    assert view["push"]["off_scheduled_for"] == "x"
    assert view["push"]["sit_sent_for"] is None
    assert view["push"]["sit_scheduled_for"] is None


def test_future_off_timer_schedules_without_sending(app):
    app.subscribe()
    status, body = app.invoke("POST", "/api/schedule/start-timer")
    assert status == 200, body
    assert "push_subscriptions" not in body
    assert "reminders" not in body
    schedule = app.scheduler.schedules["potty-log-off"]
    assert schedule["ScheduleExpression"] == "at(2026-11-25T02:30:00)"
    assert schedule["ScheduleExpressionTimezone"] == "UTC"
    assert schedule["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert schedule["ActionAfterCompletion"] == "DELETE"
    assert schedule["Target"]["RetryPolicy"] == {
        "MaximumRetryAttempts": 2,
        "MaximumEventAgeInSeconds": 300,
    }
    assert json.loads(schedule["Target"]["Input"]) == {"reminder": {"kind": "off", "due": OFF_DUE}}
    assert app.pushes == []
    assert app.stored()["reminders"]["off_scheduled_for"] == OFF_DUE
    assert not app.stored()["reminders"].get("off_sent_for")


def test_stop_timer_deletes_the_off_schedule(app):
    app.invoke("POST", "/api/schedule/start-timer")
    status, _body = app.invoke("POST", "/api/schedule/stop-timer")
    assert status == 200
    assert "potty-log-off" not in app.scheduler.schedules
    assert app.scheduler.deleted == ["potty-log-off"]
    assert app.stored()["reminders"]["off_scheduled_for"] is None


def test_same_deadline_is_not_rewritten(app):
    app.invoke("POST", "/api/schedule/start-timer")
    status, _body = app.invoke("PUT", "/api/settings", {})
    assert status == 200
    assert app.scheduler.created == ["potty-log-off"]
    assert app.scheduler.updated == []


def test_changed_deadline_updates_the_existing_schedule(app):
    token = (START + timedelta(minutes=20)).isoformat()
    state = default_state()
    state["schedule"]["running"] = True
    state["schedule"]["next_sit_at"] = token
    state["schedule"]["timer_interval_minutes"] = 20
    state["reminders"] = {"off_scheduled_for": "old"}
    app.scheduler.schedules["potty-log-off"] = {"Name": "potty-log-off"}
    assert sync_reminders(state, START) is True
    assert app.scheduler.updated == ["potty-log-off"]
    assert app.scheduler.schedules["potty-log-off"]["ScheduleExpression"] == "at(2026-11-25T02:35:00)"


def test_deadline_inside_one_minute_is_left_to_the_open_page(app):
    state = default_state()
    state["schedule"]["running"] = True
    state["schedule"]["next_sit_at"] = (START + timedelta(seconds=30)).isoformat()
    state["schedule"]["timer_interval_minutes"] = 15
    state["push_subscriptions"] = [
        {"endpoint": "https://push.example/device", "keys": {"p256dh": "p", "auth": "a"}}
    ]
    assert sync_reminders(state, START) is False
    assert app.scheduler.schedules == {}
    assert app.pushes == []


def test_active_sit_schedules_the_sit_end_and_skips_a_due_off_push(app):
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    app.clock["now"] = START + timedelta(minutes=16)
    status, _body = app.invoke("POST", "/api/schedule/start-sit", {"kind": "scheduled"})
    assert status == 200
    assert app.pushes == []
    started = (START + timedelta(minutes=16)).isoformat()
    sit = app.scheduler.schedules["potty-log-sit"]
    assert sit["ScheduleExpression"] == "at(2026-11-25T02:36:00)"
    assert json.loads(sit["Target"]["Input"]) == {"reminder": {"kind": "sit", "started_at": started}}
    assert not app.stored()["reminders"].get("off_sent_for")


def test_past_off_deadline_sends_once_after_the_sit_ends(app):
    app.invoke("PUT", "/api/settings", {"child_name": "Sam"})
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    app.clock["now"] = START + timedelta(minutes=16)
    app.invoke("POST", "/api/schedule/start-sit", {"kind": "accident"})
    assert app.pushes == []
    status, _body = app.invoke("POST", "/api/schedule/cancel-sit")
    assert status == 200
    assert len(app.pushes) == 1
    sent = app.pushes[0]
    assert json.loads(sent["data"]) == {
        "title": "Time to go potty",
        "body": "Sam. 15 min off potty.",
        "tag": f"off:{OFF_DUE}",
    }
    assert sent["ttl"] == 300
    assert sent["content_encoding"] == "aes128gcm"
    assert sent["headers"]["Urgency"] == "high"
    assert sent["vapid_claims"]["sub"] == "mailto:test@example.com"
    assert app.stored()["reminders"]["off_sent_for"] == OFF_DUE
    app.invoke("PUT", "/api/settings", {})
    assert len(app.pushes) == 1


def test_matching_reminder_sends_once(app):
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    token = app.stored()["schedule"]["next_sit_at"]
    assert app.remind({"kind": "off", "due": token}) == {"ok": True}
    assert len(app.pushes) == 1
    assert app.stored()["reminders"]["off_sent_for"] == token
    assert app.stored()["reminders"]["off_scheduled_for"] is None
    assert app.remind({"kind": "off", "due": token}) == {"ok": True}
    assert len(app.pushes) == 1


def test_off_reminder_during_a_sit_does_not_send(app):
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    app.invoke("POST", "/api/schedule/start-sit", {"kind": "scheduled"})
    token = app.stored()["schedule"]["next_sit_at"]
    assert app.remind({"kind": "off", "due": token}) == {"ok": True}
    assert app.pushes == []
    stored = app.stored()
    assert stored["reminders"]["off_scheduled_for"] is None
    assert not stored["reminders"].get("off_sent_for")
    app.invoke("POST", "/api/schedule/cancel-sit")
    assert app.pushes == []
    assert app.scheduler.schedules["potty-log-off"]["ScheduleExpression"] == "at(2026-11-25T02:30:00)"


def test_stale_reminder_sends_nothing(app):
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    real_off = app.stored()["schedule"]["next_sit_at"]
    assert app.remind({"kind": "off", "due": "2000-01-01T00:00:00+00:00"}) == {"ok": True}
    assert app.pushes == []
    assert app.stored()["reminders"]["off_scheduled_for"] == real_off
    assert not app.stored()["reminders"].get("off_sent_for")

    app.invoke("POST", "/api/schedule/start-sit", {"kind": "asked"})
    real_sit = app.stored()["schedule"]["active_sit"]["started_at"]
    assert app.remind({"kind": "sit", "started_at": "2000-01-01T00:00:00+00:00"}) == {"ok": True}
    assert app.pushes == []
    assert app.stored()["reminders"]["sit_scheduled_for"] == real_sit
    assert not app.stored()["reminders"].get("sit_sent_for")


def test_gone_subscription_is_removed_and_the_invoke_succeeds(app, monkeypatch):
    def gone(**kwargs):
        app.pushes.append(kwargs)
        response = type("Response", (), {"status_code": 410, "text": "gone", "reason": "Gone"})()
        raise WebPushException("gone", response=response)

    monkeypatch.setattr(push, "webpush", gone)
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    token = app.stored()["schedule"]["next_sit_at"]
    assert app.remind({"kind": "off", "due": token}) == {"ok": True}
    assert app.stored()["push_subscriptions"] == []
    assert app.stored()["reminders"]["off_sent_for"] == token


def test_push_failure_retries(app, monkeypatch):
    def rejected(**_kwargs):
        response = type("Response", (), {"status_code": 500, "text": "no", "reason": "Error"})()
        raise WebPushException("no", response=response)

    monkeypatch.setattr(push, "webpush", rejected)
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    token = app.stored()["schedule"]["next_sit_at"]
    with pytest.raises(PushFailed):
        app.remind({"kind": "off", "due": token})
    stored = app.stored()
    assert stored["push_subscriptions"][0]["endpoint"] == "https://push.example/device"
    assert not stored["reminders"].get("off_sent_for")


def test_http_event_cannot_trigger_a_reminder(app):
    app.subscribe()
    app.invoke("POST", "/api/schedule/start-timer")
    token = app.stored()["schedule"]["next_sit_at"]
    result = handler(
        {
            "httpMethod": "POST",
            "path": "/api/not-a-route",
            "headers": app.headers(),
            "body": json.dumps({"reminder": {"kind": "off", "due": token}}),
            "reminder": {"kind": "off", "due": token},
            "requestContext": {"http": {"method": "POST"}},
        },
        None,
    )
    assert result["statusCode"] == 404
    assert app.pushes == []


def test_subscribe_rejects_non_https_and_caps_the_list(app):
    last = {}
    for index in range(11):
        status, last = app.invoke(
            "POST",
            "/api/push/subscribe",
            {"endpoint": f"https://push.example/{index}", "keys": {"p256dh": "p", "auth": "a"}},
        )
        assert status == 200
    assert "push_subscriptions" not in last
    status, body = app.invoke(
        "POST",
        "/api/push/subscribe",
        {"endpoint": "http://push.example/no", "keys": {"p256dh": "p", "auth": "a"}},
    )
    assert status == 400
    assert "https://" in body["error"]
    stored = app.stored()["push_subscriptions"]
    assert [item["endpoint"] for item in stored] == [f"https://push.example/{index}" for index in range(1, 11)]
    assert app.scheduler.created == []
    assert app.scheduler.delete_attempts == []


def test_scheduler_failure_does_not_fail_the_save(app, monkeypatch):
    def down():
        raise RuntimeError("scheduler down")

    monkeypatch.setattr("potty_train.reminders._client", down)
    status, body = app.invoke("POST", "/api/schedule/start-timer")
    assert status == 200
    assert body["schedule"]["running"] is True
    assert app.stored()["schedule"]["running"] is True
    assert not app.stored().get("reminders", {}).get("off_scheduled_for")


def test_local_env_does_not_call_aws(monkeypatch, tmp_path):
    calls: list[str] = []

    def client():
        calls.append("scheduler")
        raise RuntimeError("AWS")

    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setenv("POTTY_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("POTTY_LOCAL_PASSWORD", "secret")
    monkeypatch.setenv("POTTY_LOCAL_TOKEN_KEY", "local-key")
    monkeypatch.setenv("SCHEDULER_ROLE_ARN", "arn:aws:iam::143977713810:role/potty-log-scheduler")
    monkeypatch.delenv("VAPID_SECRET_ARN", raising=False)
    monkeypatch.delenv("POTTY_VAPID_PRIVATE_PEM", raising=False)
    monkeypatch.delenv("POTTY_VAPID_PUBLIC_PEM", raising=False)
    push._CACHE["loaded_at"] = 0.0
    push._CACHE["material"] = None
    auth._CACHE["secret"] = None
    auth._CACHE["loaded_at"] = 0.0
    handler_mod._STORE = None
    monkeypatch.setattr("potty_train.reminders._client", client)
    monkeypatch.setattr(handler_mod, "_server_now", lambda: START)
    token = issue_token("local-key")
    result = handler(
        {
            "httpMethod": "POST",
            "path": "/api/schedule/start-timer",
            "headers": {"authorization": f"Bearer {token}"},
            "body": "{}",
        },
        None,
    )
    assert result["statusCode"] == 200, result
    assert calls == []
    body = json.loads(result["body"])
    assert body["schedule"]["running"] is True
    assert body["push"]["public_key"] == ""
