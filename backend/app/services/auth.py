"""Admin authentication primitives.

- Argon2id password hashing + verification with constant-time dummy hash
  for unknown-user path (equalises timing across found/not-found).
- TOTP secret generation, otpauth:// URI builder, code verification with
  ±1 step clock skew tolerance.
- Failure counter / lockout helpers that mutate Admin ORM instances.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

_DUMMY_INPUT = "dummy-password-for-constant-time"


class LockedOut(Exception):
    """Admin account is currently locked."""


class InvalidCredentials(Exception):
    """Email/password/TOTP combination is invalid."""


class AuthService:
    """Argon2id password + TOTP + lockout logic.

    No DB access; callers operate on Admin ORM instances. Password hashing
    uses time_cost=3, memory_cost=65536 (64 MB), parallelism=1.
    """

    def __init__(
        self,
        *,
        max_failed_attempts: int,
        lockout_minutes: int,
        time_cost: int = 3,
        memory_cost: int = 64 * 1024,
        parallelism: int = 1,
    ) -> None:
        self.max_failed_attempts = max_failed_attempts
        self.lockout_minutes = lockout_minutes
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )
        # Pre-compute a dummy hash once — use it on the unknown-user path
        # so verify_password runs in ~constant time regardless of lookup result.
        self._dummy_hash = self._hasher.hash(_DUMMY_INPUT)

    # ---- Passwords ----

    def hash_password(self, plain: str) -> str:
        return self._hasher.hash(plain)

    def verify_password(self, plain: str, hashed: str) -> bool:
        try:
            return self._hasher.verify(hashed, plain)
        except (VerifyMismatchError, InvalidHashError, VerificationError):
            return False
        except Exception:
            # Unknown error — fail closed.
            return False

    def dummy_hash(self) -> str:
        """Expose the constant-time dummy so callers can exercise it on unknown users."""
        return self._dummy_hash

    # ---- TOTP ----

    @staticmethod
    def generate_totp_secret() -> str:
        return pyotp.random_base32()

    @staticmethod
    def build_totp_uri(secret: str, *, email: str, issuer: str = "Fylix") -> str:
        # pyotp's provisioning_uri URL-encodes, but we prefer to construct manually
        # so we can control exactly what's returned.
        label = quote(f"{issuer}:{email}", safe="")
        return (
            f"otpauth://totp/{label}"
            f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
        )

    @staticmethod
    def verify_totp(secret: str, code: str) -> bool:
        if not secret or not code or not code.isdigit():
            return False
        totp = pyotp.TOTP(secret)
        # ±1 step (±30 sec) clock-skew tolerance
        return totp.verify(code, valid_window=1)

    # ---- Lockout ----

    def register_failure(self, admin: Any) -> None:
        admin.failed_attempts = (admin.failed_attempts or 0) + 1
        if admin.failed_attempts >= self.max_failed_attempts:
            admin.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=self.lockout_minutes
            )

    def reset_failures(self, admin: Any) -> None:
        admin.failed_attempts = 0
        admin.locked_until = None

    def is_locked(self, admin: Any) -> bool:
        if admin.locked_until is None:
            return False
        return admin.locked_until > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# TOTP secret envelope helpers (AES-KW via RFC 3394)
# ---------------------------------------------------------------------------

from cryptography.hazmat.primitives.keywrap import (  # noqa: E402
    InvalidUnwrap,
    aes_key_unwrap,
    aes_key_wrap,
)

from app.crypto.envelope import EnvelopeError  # noqa: E402

_MASTER_KEY_LEN = 32
_TOTP_BLOCK = 40   # plaintext block size (must be multiple of 8 for AES-KW)
_TOTP_WRAPPED = _TOTP_BLOCK + 8   # 48 bytes — AES-KW output
_TOTP_SECRET_MAX = _TOTP_BLOCK - 1  # 39 bytes available for the secret


def wrap_totp_secret(master_key: bytes, secret: str) -> bytes:
    """Wrap a base32 TOTP secret with AES-KW envelope.

    Layout: [1 byte length][N bytes UTF-8 secret][zero-pad to _TOTP_BLOCK bytes]
    Result: _TOTP_WRAPPED (48) bytes — RFC 3394 output for 40-byte plaintext.

    Supports secrets up to 39 UTF-8 bytes (covers all pyotp defaults: 16–32 chars).
    """
    if len(master_key) != _MASTER_KEY_LEN:
        raise EnvelopeError(f"master_key must be {_MASTER_KEY_LEN} bytes; got {len(master_key)}")
    raw = secret.encode("utf-8")
    if len(raw) > _TOTP_SECRET_MAX:
        raise ValueError(f"TOTP secret too long: {len(raw)} bytes (max {_TOTP_SECRET_MAX})")
    padded = bytes([len(raw)]) + raw + b"\x00" * (_TOTP_BLOCK - 1 - len(raw))
    assert len(padded) == _TOTP_BLOCK
    return aes_key_wrap(master_key, padded)


def unwrap_totp_secret(
    master_key: bytes,
    wrapped: bytes,
    *,
    previous_master_key: bytes | None = None,
) -> str:
    """Inverse of `wrap_totp_secret`. Raises EnvelopeError on tamper/wrong-key.

    If `previous_master_key` is supplied, falls back to it on InvalidUnwrap —
    used during the master-key rotation transition window so admin login keeps
    working while the rewrap job migrates all TOTP secrets to the new key.
    """
    if len(master_key) != _MASTER_KEY_LEN:
        raise EnvelopeError(f"master_key must be {_MASTER_KEY_LEN} bytes; got {len(master_key)}")
    if previous_master_key is not None and len(previous_master_key) != _MASTER_KEY_LEN:
        raise EnvelopeError(
            f"previous_master_key must be {_MASTER_KEY_LEN} bytes; got {len(previous_master_key)}"
        )
    if len(wrapped) != _TOTP_WRAPPED:
        raise EnvelopeError(f"wrapped TOTP must be {_TOTP_WRAPPED} bytes; got {len(wrapped)}")
    try:
        padded = aes_key_unwrap(master_key, wrapped)
    except InvalidUnwrap:
        if previous_master_key is None:
            raise EnvelopeError(
                "TOTP unwrap failed (wrong master key or tampered)"
            ) from None
        try:
            padded = aes_key_unwrap(previous_master_key, wrapped)
        except InvalidUnwrap as e:
            raise EnvelopeError(
                "TOTP unwrap failed with both current and previous master keys"
            ) from e
    assert len(padded) == _TOTP_BLOCK
    length = padded[0]
    if length > _TOTP_SECRET_MAX:
        raise ValueError(f"invalid unwrapped TOTP: bad length {length}")
    return padded[1 : 1 + length].decode("utf-8")


def is_wrapped_totp(data: bytes) -> bool:
    """True if `data` looks like AES-KW output (_TOTP_WRAPPED bytes); False for plain base32."""
    return len(data) == _TOTP_WRAPPED


# ---------------------------------------------------------------------------
# Telegram bot token envelope helpers (AES-KW via RFC 3394)
# ---------------------------------------------------------------------------

_TG_BLOCK = 256   # plaintext block size (must be multiple of 8 for AES-KW)
_TG_WRAPPED = _TG_BLOCK + 8   # 264 bytes — AES-KW output
_TG_TOKEN_MAX = _TG_BLOCK - 1  # 255 bytes available for the token


def wrap_telegram_token(master_key: bytes, token: str) -> bytes:
    """Wrap a Telegram bot token with AES-KW envelope.

    Layout: [1 byte length][N bytes UTF-8 token][zero-pad to _TG_BLOCK bytes]
    Result: _TG_WRAPPED (264) bytes — AES-KW output for a 256-byte plaintext.

    Supports tokens up to 255 UTF-8 bytes, which comfortably covers the
    current Telegram bot token format (`<bot_id>:<35-char-suffix>`, typically
    ~46 chars) plus plenty of headroom for format changes.
    """
    if len(master_key) != _MASTER_KEY_LEN:
        raise EnvelopeError(f"master_key must be {_MASTER_KEY_LEN} bytes; got {len(master_key)}")
    raw = token.encode("utf-8")
    if len(raw) > _TG_TOKEN_MAX:
        raise ValueError(f"telegram token too long: {len(raw)} bytes (max {_TG_TOKEN_MAX})")
    padded = bytes([len(raw)]) + raw + b"\x00" * (_TG_BLOCK - 1 - len(raw))
    assert len(padded) == _TG_BLOCK
    return aes_key_wrap(master_key, padded)


def unwrap_telegram_token(
    master_key: bytes,
    wrapped: bytes,
    *,
    previous_master_key: bytes | None = None,
) -> str:
    """Inverse of `wrap_telegram_token`. Supports the rotation fallback path
    (mirrors unwrap_totp_secret / unwrap_key)."""
    if len(master_key) != _MASTER_KEY_LEN:
        raise EnvelopeError(f"master_key must be {_MASTER_KEY_LEN} bytes; got {len(master_key)}")
    if previous_master_key is not None and len(previous_master_key) != _MASTER_KEY_LEN:
        raise EnvelopeError(
            f"previous_master_key must be {_MASTER_KEY_LEN} bytes; got {len(previous_master_key)}"
        )
    if len(wrapped) != _TG_WRAPPED:
        raise EnvelopeError(f"wrapped token must be {_TG_WRAPPED} bytes; got {len(wrapped)}")
    try:
        padded = aes_key_unwrap(master_key, wrapped)
    except InvalidUnwrap:
        if previous_master_key is None:
            raise EnvelopeError(
                "telegram token unwrap failed (wrong master key or tampered)"
            ) from None
        try:
            padded = aes_key_unwrap(previous_master_key, wrapped)
        except InvalidUnwrap as e:
            raise EnvelopeError(
                "telegram token unwrap failed with both current and previous master keys"
            ) from e
    assert len(padded) == _TG_BLOCK
    length = padded[0]
    if length > _TG_TOKEN_MAX:
        raise ValueError(f"invalid unwrapped telegram token: bad length {length}")
    return padded[1 : 1 + length].decode("utf-8")


def is_wrapped_telegram_token(data: bytes) -> bool:
    """True if `data` looks like AES-KW output for a Telegram token."""
    return len(data) == _TG_WRAPPED
