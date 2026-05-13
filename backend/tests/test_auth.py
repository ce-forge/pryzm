"""Unit tests for require_token dependency."""
import pytest
from fastapi import HTTPException

from core.auth import require_token


def test_require_token_accepts_correct_bearer(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    require_token(authorization="Bearer test-secret-token")  # must not raise


def test_require_token_rejects_missing_header(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization=None)
    assert exc.value.status_code == 401


def test_require_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization="Bearer wrong-token")
    assert exc.value.status_code == 401


def test_require_token_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization="Basic dGVzdDp0ZXN0")
    assert exc.value.status_code == 401
