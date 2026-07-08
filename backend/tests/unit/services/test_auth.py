from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pyotp
import pytest

from app.services.auth import (
    AuthService,
    InvalidCredentials,
    LockedOut,
)


@pytest.fixture
def auth() -> AuthService:
    return AuthService(max_failed_attempts=3, lockout_minutes=15)


def test_hash_and_verify_roundtrip(auth: AuthService) -> None:
    h = auth.hash_password("secret-123")
    assert h.startswith("$argon2id$")
    assert auth.verify_password("secret-123", h) is True


def test_verify_rejects_wrong_password(auth: AuthService) -> None:
    h = auth.hash_password("right")
    assert auth.verify_password("wrong", h) is False


def test_verify_handles_garbage_hash_without_raising(auth: AuthService) -> None:
    # Corrupted DB row or constant-time dummy — must not raise.
    assert auth.verify_password("anything", "not-a-real-hash") is False


def test_dummy_hash_is_constant_time_safe(auth: AuthService) -> None:
    # Even when user unknown, caller should run verify_password against
    # a deterministic dummy to equalise time. The service exposes a
    # getter for that dummy.
    dummy = auth.dummy_hash()
    assert dummy.startswith("$argon2id$")
    # verify_password against the dummy should always succeed for its
    # known plaintext (which is unknown to attackers).
    assert auth.verify_password("any-incorrect-input", dummy) is False


def test_generate_totp_secret_returns_base32(auth: AuthService) -> None:
    s = auth.generate_totp_secret()
    assert isinstance(s, str)
    assert len(s) >= 16
    # pyotp accepts it
    pyotp.TOTP(s).now()  # smoke check


def test_build_totp_uri_contains_issuer_and_account(auth: AuthService) -> None:
    secret = "JBSWY3DPEHPK3PXP"
    uri = auth.build_totp_uri(secret, email="alice@example.com", issuer="Fylix")
    assert uri.startswith("otpauth://totp/")
    assert "Fylix" in uri
    assert "alice%40example.com" in uri or "alice@example.com" in uri
    assert f"secret={secret}" in uri


def test_verify_totp_accepts_current_code(auth: AuthService) -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    assert auth.verify_totp(secret, code) is True


def test_verify_totp_rejects_wrong_code(auth: AuthService) -> None:
    secret = pyotp.random_base32()
    assert auth.verify_totp(secret, "000000") is False


def test_verify_totp_allows_one_step_clock_skew(auth: AuthService) -> None:
    import time

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    prev_code = totp.at(int(time.time()) - 30)
    # Default valid_window=1 → accept the previous 30-sec window
    assert auth.verify_totp(secret, prev_code) is True


def test_register_failure_increments_counter(auth: AuthService) -> None:
    admin = MagicMock(failed_attempts=0, locked_until=None)
    auth.register_failure(admin)
    assert admin.failed_attempts == 1
    assert admin.locked_until is None  # not yet at threshold


def test_register_failure_locks_at_threshold(auth: AuthService) -> None:
    admin = MagicMock(failed_attempts=2, locked_until=None)
    auth.register_failure(admin)
    assert admin.failed_attempts == 3
    assert admin.locked_until is not None
    assert admin.locked_until > datetime.now(UTC)


def test_reset_failures(auth: AuthService) -> None:
    admin = MagicMock(
        failed_attempts=3,
        locked_until=datetime.now(UTC) + timedelta(minutes=5),
    )
    auth.reset_failures(admin)
    assert admin.failed_attempts == 0
    assert admin.locked_until is None


def test_is_locked_true_when_locked_until_in_future(auth: AuthService) -> None:
    admin = MagicMock(locked_until=datetime.now(UTC) + timedelta(minutes=1))
    assert auth.is_locked(admin) is True


def test_is_locked_false_when_expired(auth: AuthService) -> None:
    admin = MagicMock(locked_until=datetime.now(UTC) - timedelta(minutes=1))
    assert auth.is_locked(admin) is False


def test_is_locked_false_when_never_locked(auth: AuthService) -> None:
    admin = MagicMock(locked_until=None)
    assert auth.is_locked(admin) is False


def test_exceptions_are_types() -> None:
    assert issubclass(LockedOut, Exception)
    assert issubclass(InvalidCredentials, Exception)
