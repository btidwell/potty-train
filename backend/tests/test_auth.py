import json

from potty_train.auth import TOKEN_TTL_SECONDS, issue_token, token_is_valid

ISSUED_AT = 1_700_000_000
SIGNING_KEY = "test-signing-key"


def test_issued_token_lasts_thirty_days_not_fourteen_hours(monkeypatch):
    assert TOKEN_TTL_SECONDS == 30 * 24 * 60 * 60
    monkeypatch.setattr("potty_train.auth.time.time", lambda: ISSUED_AT)

    token = issue_token(SIGNING_KEY)
    payload = json.loads(_payload(token))
    assert payload["exp"] == ISSUED_AT + TOKEN_TTL_SECONDS

    fourteen_hours_later = ISSUED_AT + (14 * 60 * 60) + 1
    monkeypatch.setattr("potty_train.auth.time.time", lambda: fourteen_hours_later)
    assert token_is_valid(SIGNING_KEY, token)

    monkeypatch.setattr("potty_train.auth.time.time", lambda: ISSUED_AT + TOKEN_TTL_SECONDS)
    assert token_is_valid(SIGNING_KEY, token)

    monkeypatch.setattr("potty_train.auth.time.time", lambda: ISSUED_AT + TOKEN_TTL_SECONDS + 1)
    assert not token_is_valid(SIGNING_KEY, token)


def test_token_keeps_the_hmac_check(monkeypatch):
    monkeypatch.setattr("potty_train.auth.time.time", lambda: ISSUED_AT)
    token = issue_token(SIGNING_KEY)
    payload, signature = token.split(".", 1)

    assert token_is_valid(SIGNING_KEY, token)
    assert not token_is_valid("other-key", token)
    assert not token_is_valid(SIGNING_KEY, f"{payload}.{'0' * len(signature)}")
    assert not token_is_valid(SIGNING_KEY, "")


def _payload(token: str) -> bytes:
    import base64

    raw = token.split(".", 1)[0]
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)
