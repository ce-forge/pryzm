"""Password hashing via argon2id."""
import pytest

from core.cookie_auth import hash_password, verify_password


def test_hash_password_returns_argon2id_string():
    h = hash_password("hunter2hunter2")
    assert h.startswith("$argon2id$")


def test_verify_password_accepts_correct_password():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h) is True


def test_verify_password_rejects_wrong_password():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter3hunter3", h) is False


def test_verify_password_handles_invalid_hash():
    # Malformed hash strings shouldn't raise — return False.
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_password_produces_unique_salts():
    a = hash_password("hunter2hunter2")
    b = hash_password("hunter2hunter2")
    assert a != b  # different salts -> different hash strings
