"""Login rate limiting: lockout after N failures in a window."""
import time

import pytest

from core.cookie_auth import (
    LoginRateLimiter,
    RATE_LIMIT_FAILURES,
    RATE_LIMIT_WINDOW_SECONDS,
    LOCKOUT_SECONDS,
)


def test_rate_limiter_allows_attempts_below_threshold():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES - 1):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is False


def test_rate_limiter_locks_after_threshold():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is True


def test_rate_limiter_unlocks_after_lockout_window(monkeypatch):
    rl = LoginRateLimiter()
    # Fake time progression
    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])
    for _ in range(RATE_LIMIT_FAILURES):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is True
    fake_now[0] += LOCKOUT_SECONDS + 1
    assert rl.is_locked("alice") is False


def test_rate_limiter_record_success_clears_failures():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES - 1):
        rl.record_failure("alice")
    rl.record_success("alice")
    # Failures cleared, lockout shouldn't trigger on next failure
    rl.record_failure("alice")
    assert rl.is_locked("alice") is False


def test_rate_limiter_is_per_username():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is True
    assert rl.is_locked("bob") is False
