"""Cookie-based session authentication.

Separate from core/auth.py (bearer-token) so the eventual Phase E removal
is a clean file delete + import-replace rather than function-level surgery.

This module covers password hashing/verification. Subsequent additions
will include session helpers, the current_user FastAPI dependency,
and the login rate limiter.
"""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError


_ph = PasswordHasher()


def hash_password(plaintext: str) -> str:
    return _ph.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False
