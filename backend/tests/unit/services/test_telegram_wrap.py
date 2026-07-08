"""AES-KW envelope for Telegram bot tokens — mirrors the TOTP pattern."""

from __future__ import annotations

import os

import pytest

from app.crypto.envelope import EnvelopeError
from app.services.auth import (
    is_wrapped_telegram_token,
    unwrap_telegram_token,
    wrap_telegram_token,
)

_SAMPLE = "123456789:ABCDefGhIjKlMnOpQrStUvWxYz0123456789"


def test_wrap_unwrap_roundtrip() -> None:
    master = os.urandom(32)
    wrapped = wrap_telegram_token(master, _SAMPLE)
    assert len(wrapped) == 264
    assert unwrap_telegram_token(master, wrapped) == _SAMPLE


def test_wrap_various_lengths() -> None:
    master = os.urandom(32)
    for length in (1, 16, 46, 100, 200, 255):
        token = "A" * length
        assert unwrap_telegram_token(master, wrap_telegram_token(master, token)) == token


def test_wrap_rejects_too_long() -> None:
    master = os.urandom(32)
    with pytest.raises(ValueError, match="too long"):
        wrap_telegram_token(master, "X" * 256)


def test_unwrap_rejects_wrong_master() -> None:
    m1 = os.urandom(32)
    m2 = os.urandom(32)
    wrapped = wrap_telegram_token(m1, _SAMPLE)
    with pytest.raises(EnvelopeError):
        unwrap_telegram_token(m2, wrapped)


def test_is_wrapped_heuristic() -> None:
    assert is_wrapped_telegram_token(b"\x00" * 264) is True
    assert is_wrapped_telegram_token(b"\x00" * 100) is False
    assert is_wrapped_telegram_token(b"plain-string") is False
    assert is_wrapped_telegram_token(b"") is False


# --- Dual-key rotation (fallback) -----------------------------------------


def test_unwrap_falls_back_to_previous_master() -> None:
    previous = os.urandom(32)
    current = os.urandom(32)
    wrapped = wrap_telegram_token(previous, _SAMPLE)
    assert unwrap_telegram_token(current, wrapped, previous_master_key=previous) == _SAMPLE


def test_unwrap_prefers_current_when_both_valid() -> None:
    current = os.urandom(32)
    previous = os.urandom(32)
    wrapped = wrap_telegram_token(current, "NEW")
    assert unwrap_telegram_token(current, wrapped, previous_master_key=previous) == "NEW"


def test_unwrap_raises_when_neither_key_matches() -> None:
    wrapped = wrap_telegram_token(os.urandom(32), _SAMPLE)
    with pytest.raises(EnvelopeError):
        unwrap_telegram_token(os.urandom(32), wrapped, previous_master_key=os.urandom(32))


def test_wrap_is_deterministic() -> None:
    """AES-KW RFC 3394 is deterministic — essential for rewrap idempotence
    and for comparing old==new in PATCH handlers."""
    master = os.urandom(32)
    assert wrap_telegram_token(master, _SAMPLE) == wrap_telegram_token(master, _SAMPLE)


def test_utf8_token_roundtrips() -> None:
    master = os.urandom(32)
    # Real bot tokens are ASCII, but the wrap must not assume that.
    token = "тест:BotToken-文件"
    assert unwrap_telegram_token(master, wrap_telegram_token(master, token)) == token
