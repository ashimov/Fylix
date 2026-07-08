"""AES Key Wrap (RFC 3394) for wrapping per-transfer file keys with the master key."""

from __future__ import annotations

from cryptography.hazmat.primitives.keywrap import (
    InvalidUnwrap,
    aes_key_unwrap,
    aes_key_wrap,
)

_KEY_LEN = 32


class EnvelopeError(RuntimeError):
    """Raised when wrap or unwrap fails."""


def _assert_key_len(key: bytes, name: str) -> None:
    if len(key) != _KEY_LEN:
        raise EnvelopeError(f"{name} must be {_KEY_LEN} bytes; got {len(key)}")


def wrap_key(master_key: bytes, file_key: bytes) -> bytes:
    """Wrap a 32-byte file_key using the 32-byte master_key.

    Returns 40 bytes (RFC 3394 standard for 256-bit plaintext key).
    """
    _assert_key_len(master_key, "master_key")
    _assert_key_len(file_key, "file_key")
    return aes_key_wrap(master_key, file_key)


def unwrap_key(
    master_key: bytes,
    wrapped: bytes,
    *,
    previous_master_key: bytes | None = None,
) -> bytes:
    """Unwrap a previously wrapped file key.

    Tries `master_key` first. If that fails AND `previous_master_key` is
    provided, tries the previous key — this is the transition-window path
    during zero-downtime master-key rotation: new ciphertext is wrapped with
    the current key, while ciphertext created before the rotation is still
    wrapped with the previous key until the background rewrap job finishes.

    Raises EnvelopeError if both keys fail (or if only `master_key` is
    provided and it fails, preserving legacy single-key semantics).
    """
    _assert_key_len(master_key, "master_key")
    if previous_master_key is not None:
        _assert_key_len(previous_master_key, "previous_master_key")
    if len(wrapped) != _KEY_LEN + 8:
        raise EnvelopeError(f"wrapped key must be {_KEY_LEN + 8} bytes; got {len(wrapped)}")
    try:
        return aes_key_unwrap(master_key, wrapped)
    except InvalidUnwrap:
        if previous_master_key is None:
            raise EnvelopeError("unwrap failed (wrong master key or tampered ciphertext)") from None
        try:
            return aes_key_unwrap(previous_master_key, wrapped)
        except InvalidUnwrap as e:
            raise EnvelopeError(
                "unwrap failed with both current and previous master keys "
                "(wrong keys or tampered ciphertext)"
            ) from e
