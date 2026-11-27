"""Aggregated secret loader."""

from __future__ import annotations

import json

from potty_train import secrets as secrets_mod


def test_local_env_overrides(monkeypatch):
    secrets_mod.clear_secret_cache()
    monkeypatch.setenv("POTTY_ENV", "local")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("POTTY_VAPID_PRIVATE_PEM", "priv")
    monkeypatch.setenv("POTTY_VAPID_PUBLIC_PEM", "pub")
    monkeypatch.delenv("APP_SECRET_ARN", raising=False)

    values = secrets_mod.load_app_secrets()
    assert values["xai_api_key"] == "xai-test"
    assert secrets_mod.app_secret("xai_api_key") == "xai-test"
    assert secrets_mod.app_secret("missing", "fallback") == "fallback"
