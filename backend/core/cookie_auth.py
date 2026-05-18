"""Cookie-based session authentication.

Separate from core/auth.py (bearer-token) so the eventual Phase E removal
is a clean file delete + import-replace rather than function-level surgery.

This module covers password hashing/verification, session helpers, the
current_user FastAPI dependency, and the login rate limiter.
"""
import hmac as _hmac
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from fastapi import Cookie, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session as DbSession

from config import settings as _config_settings
from db import database, models


_ph = PasswordHasher()


def hash_password(plaintext: str) -> str:
    return _ph.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


# Session lifetime defaults (resolved decisions: 7-day idle, 30-day hard cap)
SESSION_IDLE_TIMEOUT = timedelta(days=7)
SESSION_HARD_CAP = timedelta(days=30)


def create_session(db: DbSession, user_id: str) -> str:
    sid = secrets.token_urlsafe(32)  # ~43 chars, 256 bits
    now = datetime.now(timezone.utc)
    row = models.AuthSession(
        id=sid,
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_HARD_CAP,
    )
    db.add(row)
    db.commit()
    return sid


def get_session_user(db: DbSession, sid: str) -> models.User | None:
    """Resolve a session id to a User, sliding the idle window. Returns
    None if the session doesn't exist, is past its hard cap, or has been
    idle past the idle timeout."""
    if not sid:
        return None
    row = db.query(models.AuthSession).filter_by(id=sid).first()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        return None
    if row.last_seen_at + SESSION_IDLE_TIMEOUT <= now:
        return None
    row.last_seen_at = now
    db.commit()
    user = db.query(models.User).filter_by(id=row.user_id).first()
    if user is None or not user.is_active:
        return None
    return user


def invalidate_session(db: DbSession, sid: str) -> None:
    db.query(models.AuthSession).filter_by(id=sid).delete()
    db.commit()


def invalidate_user_sessions(db: DbSession, user_id: str) -> None:
    db.query(models.AuthSession).filter_by(user_id=user_id).delete()
    db.commit()


COOKIE_NAME = "pryzm_session"


_BEARER_PREFIX = "Bearer "


def _bearer_resolves_to_bootstrap_admin(
    authorization: Optional[str],
    token: Optional[str],
    db: DbSession,
) -> Optional[models.User]:
    """Translate a valid bearer token (header or ?token=) to the bootstrap
    admin user — the oldest user with is_admin=True AND is_active=True.
    Returns None if no bearer was presented, or if it didn't match the
    configured token."""
    presented: Optional[str] = None
    if authorization and authorization.startswith(_BEARER_PREFIX):
        presented = authorization[len(_BEARER_PREFIX):]
    elif token:
        presented = token
    if presented is None:
        return None
    if not _hmac.compare_digest(presented, _config_settings.PRYZM_API_TOKEN):
        return None
    return (
        db.query(models.User)
        .filter(models.User.is_admin.is_(True), models.User.is_active.is_(True))
        .order_by(models.User.created_at.asc())
        .first()
    )


def current_user(
    pryzm_session: Annotated[Optional[str], Cookie()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    token: Annotated[Optional[str], Query()] = None,
    db: DbSession = Depends(database.get_db),
) -> models.User:
    user = get_session_user(db, pryzm_session) if pryzm_session else None
    if user is None:
        user = _bearer_resolves_to_bootstrap_admin(authorization, token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return user


def require_admin(user: models.User = Depends(current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only.",
        )
    return user


RATE_LIMIT_FAILURES = 10
RATE_LIMIT_WINDOW_SECONDS = 15 * 60  # 15 minutes
LOCKOUT_SECONDS = 15 * 60            # 15-minute lockout


class LoginRateLimiter:
    """In-memory failed-login tracker per username.

    State resets on backend restart (acceptable for v1; a determined
    attacker can survive a restart but is unlikely to coordinate with
    one). Stored in process memory only; for multi-worker deployments,
    move to Redis later.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    def _normalize(self, username: str) -> str:
        return username.lower()

    def is_locked(self, username: str) -> bool:
        key = self._normalize(username)
        until = self._locked_until.get(key)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        # Lockout expired; clear it
        del self._locked_until[key]
        self._failures.pop(key, None)
        return False

    def record_failure(self, username: str) -> None:
        key = self._normalize(username)
        now = time.monotonic()
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        recent = [ts for ts in self._failures[key] if ts > cutoff]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= RATE_LIMIT_FAILURES:
            self._locked_until[key] = now + LOCKOUT_SECONDS

    def record_success(self, username: str) -> None:
        key = self._normalize(username)
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


# Module-level singleton used by the auth router
login_rate_limiter = LoginRateLimiter()


def assert_not_removing_last_admin(
    db: DbSession,
    target_user_id: str,
    would_be_admin: bool,
    would_be_active: bool,
) -> None:
    """Raise HTTP 400 if the proposed change to `target_user_id` would
    leave zero active admins. `would_be_admin`/`would_be_active` are the
    flag values AFTER the proposed change."""
    if would_be_admin and would_be_active:
        return
    other_active_admins = (
        db.query(models.User)
        .filter(
            models.User.is_admin.is_(True),
            models.User.is_active.is_(True),
            models.User.id != target_user_id,
        )
        .count()
    )
    if other_active_admins == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove last active admin. Promote another user to admin first.",
        )
