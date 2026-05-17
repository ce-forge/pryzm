"""Cookie-based session authentication.

Separate from core/auth.py (bearer-token) so the eventual Phase E removal
is a clean file delete + import-replace rather than function-level surgery.

This module covers password hashing/verification, session helpers, the
current_user FastAPI dependency, and the login rate limiter.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

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


def current_user(
    pryzm_session: Annotated[Optional[str], Cookie()] = None,
    db: DbSession = Depends(database.get_db),
) -> models.User:
    user = get_session_user(db, pryzm_session) if pryzm_session else None
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
