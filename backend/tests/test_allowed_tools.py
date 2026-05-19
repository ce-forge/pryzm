"""Tests for per-user allowed_tools cap (spec: 2026-05-19-per-user-allowed-tools.md)."""
import pytest
from fastapi import HTTPException

from core.tool_permissions import enforce_allowed_tools, filter_allowed_tools
from db import models


def _user(allowed: list[str], is_admin: bool = False) -> models.User:
    u = models.User(
        username="x",
        password_hash="x",
        is_admin=is_admin,
        allowed_tools=allowed,
    )
    return u


class TestEnforceAllowedTools:
    def test_empty_cap_allows_anything(self):
        enforce_allowed_tools(_user([]), ["web_search", "code_run"])

    def test_non_empty_cap_allows_subset(self):
        enforce_allowed_tools(_user(["web_search"]), ["web_search"])

    def test_non_empty_cap_allows_empty_request(self):
        enforce_allowed_tools(_user(["web_search"]), [])

    def test_disallowed_tool_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            enforce_allowed_tools(_user(["web_search"]), ["code_run"])
        assert exc.value.status_code == 400
        assert "code_run" in exc.value.detail

    def test_multiple_disallowed_listed_in_message(self):
        with pytest.raises(HTTPException) as exc:
            enforce_allowed_tools(_user(["web_search"]), ["code_run", "image_gen"])
        assert "code_run" in exc.value.detail
        assert "image_gen" in exc.value.detail

    def test_admin_bypasses_non_empty_cap(self):
        enforce_allowed_tools(_user(["web_search"], is_admin=True), ["code_run"])

    def test_admin_bypasses_with_empty_cap(self):
        enforce_allowed_tools(_user([], is_admin=True), ["code_run"])


class TestFilterAllowedTools:
    def test_empty_cap_keeps_everything(self):
        kept, dropped = filter_allowed_tools(_user([]), ["web_search", "code_run"])
        assert kept == ["web_search", "code_run"]
        assert dropped == []

    def test_non_empty_cap_filters(self):
        kept, dropped = filter_allowed_tools(_user(["web_search"]), ["web_search", "code_run"])
        assert kept == ["web_search"]
        assert dropped == ["code_run"]

    def test_admin_bypasses_cap(self):
        kept, dropped = filter_allowed_tools(_user(["web_search"], is_admin=True), ["code_run"])
        assert kept == ["code_run"]
        assert dropped == []

    def test_returns_lists_not_aliases(self):
        requested = ["web_search"]
        kept, _ = filter_allowed_tools(_user([]), requested)
        kept.append("mutated")
        assert requested == ["web_search"]
