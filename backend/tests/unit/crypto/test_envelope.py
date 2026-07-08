import os

import pytest

from app.crypto.envelope import EnvelopeError, unwrap_key, wrap_key


def test_wrap_unwrap_roundtrip() -> None:
    master = os.urandom(32)
    file_key = os.urandom(32)
    wrapped = wrap_key(master, file_key)
    # AES-KW 256-bit output = 256 + 64 = 320 bits = 40 bytes
    assert len(wrapped) == 40
    recovered = unwrap_key(master, wrapped)
    assert recovered == file_key


def test_wrap_rejects_wrong_master_size() -> None:
    with pytest.raises(EnvelopeError, match="32 bytes"):
        wrap_key(b"short", os.urandom(32))


def test_wrap_rejects_wrong_file_key_size() -> None:
    with pytest.raises(EnvelopeError, match="32 bytes"):
        wrap_key(os.urandom(32), b"short")


def test_unwrap_rejects_tampered_ciphertext() -> None:
    master = os.urandom(32)
    wrapped = wrap_key(master, os.urandom(32))
    tampered = bytearray(wrapped)
    tampered[0] ^= 0x01
    with pytest.raises(EnvelopeError, match="unwrap"):
        unwrap_key(master, bytes(tampered))


def test_unwrap_rejects_wrong_master() -> None:
    wrapped = wrap_key(os.urandom(32), os.urandom(32))
    with pytest.raises(EnvelopeError, match="unwrap"):
        unwrap_key(os.urandom(32), wrapped)


# --- Dual-key rotation: fallback to previous master key -------------------


def test_unwrap_with_previous_key_falls_back_when_current_wrong() -> None:
    previous_master = os.urandom(32)
    current_master = os.urandom(32)
    file_key = os.urandom(32)
    # Simulate ciphertext wrapped with the OLD key, now being unwrapped after
    # the master key was rotated — new current is fresh, old is available as
    # previous for the transition window.
    wrapped = wrap_key(previous_master, file_key)
    recovered = unwrap_key(current_master, wrapped, previous_master_key=previous_master)
    assert recovered == file_key


def test_unwrap_prefers_current_when_both_valid() -> None:
    current_master = os.urandom(32)
    previous_master = os.urandom(32)
    file_key = os.urandom(32)
    wrapped = wrap_key(current_master, file_key)
    # Should succeed via current without ever touching the previous.
    recovered = unwrap_key(current_master, wrapped, previous_master_key=previous_master)
    assert recovered == file_key


def test_unwrap_raises_when_neither_key_matches() -> None:
    wrapped = wrap_key(os.urandom(32), os.urandom(32))
    with pytest.raises(EnvelopeError, match="unwrap"):
        unwrap_key(
            os.urandom(32),
            wrapped,
            previous_master_key=os.urandom(32),
        )


def test_unwrap_with_previous_none_preserves_single_key_behavior() -> None:
    """Passing previous_master_key=None must behave exactly like legacy single-key unwrap."""
    master = os.urandom(32)
    wrapped = wrap_key(master, os.urandom(32))
    with pytest.raises(EnvelopeError, match="unwrap"):
        unwrap_key(os.urandom(32), wrapped, previous_master_key=None)


# --- Rewrap composition (building block of zero-downtime rotation) --------


def test_rewrap_composition_migrates_old_blob_to_current_key() -> None:
    """Blob wrapped with the previous key unwraps via fallback, rewraps with
    current — result no longer needs the fallback."""
    previous_master = os.urandom(32)
    current_master = os.urandom(32)
    file_key = os.urandom(32)
    old_wrapped = wrap_key(previous_master, file_key)

    # Rewrap step (what the admin endpoint will do per row):
    recovered = unwrap_key(current_master, old_wrapped, previous_master_key=previous_master)
    new_wrapped = wrap_key(current_master, recovered)

    # New blob unwraps with current-only.
    assert unwrap_key(current_master, new_wrapped) == file_key


def test_rewrap_is_idempotent_on_already_current_blobs() -> None:
    """Re-running the rewrap job is safe: a blob already wrapped with current
    round-trips to the same bytes (AES-KW RFC 3394 is deterministic)."""
    previous_master = os.urandom(32)
    current_master = os.urandom(32)
    file_key = os.urandom(32)
    already_current = wrap_key(current_master, file_key)

    recovered = unwrap_key(current_master, already_current, previous_master_key=previous_master)
    rewrapped = wrap_key(current_master, recovered)

    assert rewrapped == already_current
