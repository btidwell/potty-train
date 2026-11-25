import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from potty_train.auth import SESSION_DAYS, auth_config, is_owner, token_is_valid
from potty_train.handler import handler

POOL = "us-east-1_TestPool"
CLIENT = "testclient"
REGION = "us-east-1"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"


@pytest.fixture
def signing_key(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT)
    monkeypatch.setenv("COGNITO_REGION", REGION)

    class Key:
        key = private.public_key()

    class Jwks:
        def get_signing_key_from_jwt(self, token):
            return Key()

    monkeypatch.setattr("potty_train.auth._jwks", lambda: Jwks())
    return private


def test_session_lasts_seven_days_from_login():
    assert SESSION_DAYS == 7


def test_auth_config_names_the_pool(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT)
    monkeypatch.setenv("COGNITO_REGION", REGION)
    assert auth_config() == {
        "userPoolId": POOL,
        "userPoolClientId": CLIENT,
        "region": REGION,
        "sessionDays": 7,
    }


def test_auth_config_is_public(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT)
    monkeypatch.setenv("COGNITO_REGION", REGION)
    result = handler({"httpMethod": "GET", "path": "/api/auth-config", "headers": {}}, None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["sessionDays"] == 7


def test_auth_config_reports_when_the_pool_is_missing(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    monkeypatch.delenv("COGNITO_CLIENT_ID", raising=False)
    result = handler({"httpMethod": "GET", "path": "/api/auth-config", "headers": {}}, None)
    assert result["statusCode"] == 500
    assert json.loads(result["body"])["error"] == "Sign-in is not configured."


def test_missing_token_is_rejected(monkeypatch):
    monkeypatch.setenv("POTTY_ENV", "local")
    result = handler({"httpMethod": "GET", "path": "/api/state", "headers": {}}, None)
    assert result["statusCode"] == 401


def test_access_token_is_accepted(signing_key):
    assert token_is_valid(_token(signing_key))


def test_expired_access_token_is_rejected(signing_key):
    assert not token_is_valid(_token(signing_key, exp=int(time.time()) - 30))


def test_id_token_is_rejected(signing_key):
    assert not token_is_valid(_token(signing_key, token_use="id"))


def test_wrong_client_is_rejected(signing_key):
    assert not token_is_valid(_token(signing_key, client_id="other-client"))


def test_wrong_pool_is_rejected(signing_key):
    other = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other"
    assert not token_is_valid(_token(signing_key, iss=other))


def test_bad_signature_is_rejected(signing_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert not token_is_valid(_token(other))


def test_blank_token_is_rejected():
    assert not token_is_valid("")


def test_only_the_owners_group_can_invite(signing_key):
    assert is_owner(_token(signing_key, **{"cognito:groups": ["owners"]}))
    assert not is_owner(_token(signing_key, **{"cognito:groups": ["family"]}))
    assert not is_owner(_token(signing_key))


def _token(private, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user",
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "exp": now + 3600,
        "iat": now,
    }
    claims.update(overrides)
    if claims.get("token_use") == "id":
        claims.pop("client_id", None)
        claims["aud"] = CLIENT
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "test"})
