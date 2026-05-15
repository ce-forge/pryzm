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


def test_require_token_accepts_url_query_fallback(monkeypatch):
    """EventSource can't set custom headers; the token rides as ?token=.
    See backend/services/ingest_pipeline.py + frontend/useUploader.ts."""
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    require_token(authorization=None, token="test-secret-token")  # must not raise


def test_require_token_rejects_wrong_url_query_token(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization=None, token="wrong-url-token")
    assert exc.value.status_code == 401


def test_require_token_prefers_bearer_over_url_when_bearer_valid(monkeypatch):
    """Bearer header is the canonical path; URL token is the fallback.
    When both are present and bearer is correct, accept it without
    inspecting the query string."""
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    require_token(authorization="Bearer test-secret-token", token="something-else")
