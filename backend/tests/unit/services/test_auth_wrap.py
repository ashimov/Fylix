import os

import pytest

from app.crypto.envelope import EnvelopeError
from app.services.auth import (
    is_wrapped_totp,
    unwrap_totp_secret,
    wrap_totp_secret,
)


def test_wrap_unwrap_roundtrip() -> None:
    master = os.urandom(32)
    secret = "JBSWY3DPEHPK3PXP"
    wrapped = wrap_totp_secret(master, secret)
    assert len(wrapped) == 48  # 40-byte plaintext + 8 AES-KW overhead
    assert unwrap_totp_secret(master, wrapped) == secret


def test_wrap_various_lengths() -> None:
    master = os.urandom(32)
    for length in [8, 16, 24, 32, 39]:  # includes pyotp default (32) and max (39)
        secret = "A" * length
        assert unwrap_totp_secret(master, wrap_totp_secret(master, secret)) == secret


def test_wrap_rejects_too_long() -> None:
    master = os.urandom(32)
    with pytest.raises(ValueError, match="too long"):
        wrap_totp_secret(master, "X" * 40)


def test_unwrap_rejects_wrong_master() -> None:
    m1 = os.urandom(32)
    m2 = os.urandom(32)
    wrapped = wrap_totp_secret(m1, "SECRET")
    with pytest.raises(EnvelopeError):
        unwrap_totp_secret(m2, wrapped)


def test_is_wrapped_heuristic() -> None:
    assert is_wrapped_totp(b"\x00" * 48) is True  # 40-byte plaintext → 48 wrapped
    assert is_wrapped_totp(b"\x00" * 40) is False  # old size — not wrapped
    assert is_wrapped_totp(b"JBSWY3DPEHPK3PXP") is False
    assert is_wrapped_totp(b"") is False


# --- Dual-key rotation: fallback to previous master key -------------------


def test_unwrap_totp_falls_back_to_previous_master() -> None:
    previous_master = os.urandom(32)
    current_master = os.urandom(32)
    wrapped = wrap_totp_secret(previous_master, "OLDSECRET")
    recovered = unwrap_totp_secret(current_master, wrapped, previous_master_key=previous_master)
    assert recovered == "OLDSECRET"


def test_unwrap_totp_prefers_current_when_both_valid() -> None:
    current_master = os.urandom(32)
    previous_master = os.urandom(32)
    wrapped = wrap_totp_secret(current_master, "NEWSECRET")
    recovered = unwrap_totp_secret(current_master, wrapped, previous_master_key=previous_master)
    assert recovered == "NEWSECRET"


def test_unwrap_totp_raises_when_neither_key_matches() -> None:
    wrapped = wrap_totp_secret(os.urandom(32), "ORIG")
    with pytest.raises(EnvelopeError):
        unwrap_totp_secret(os.urandom(32), wrapped, previous_master_key=os.urandom(32))


def test_unwrap_totp_previous_none_preserves_legacy_behavior() -> None:
    master = os.urandom(32)
    wrapped = wrap_totp_secret(master, "ORIG")
    with pytest.raises(EnvelopeError):
        unwrap_totp_secret(os.urandom(32), wrapped, previous_master_key=None)
