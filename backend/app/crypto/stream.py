"""Streaming AES-256-GCM encryption.

Layout: [ciphertext bytes][16-byte auth tag]. IV is stored separately in the DB
(on transfer_files.iv), never embedded in the ciphertext file. This keeps the
MinIO object a pure byte-for-byte record of ciphertext + tag, and lets us
validate the IV origin independently.

Also returns SHA-256 of the ciphertext (tag excluded) so callers can detect
bit-rot on the storage side without needing the key.

Uses PyCA's low-level Cipher/GCM API for O(chunk_size) peak memory rather than
reading the entire file into memory at once.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import IO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_KEY_LEN = 32
_IV_LEN = 12
_TAG_LEN = 16
_DEFAULT_CHUNK = 64 * 1024


class StreamCryptoError(RuntimeError):
    """Raised for length violations or GCM authentication failure."""


def _check_lens(key: bytes, iv: bytes) -> None:
    if len(key) != _KEY_LEN:
        raise StreamCryptoError(f"key must be {_KEY_LEN} bytes; got {len(key)}")
    if len(iv) != _IV_LEN:
        raise StreamCryptoError(f"iv must be {_IV_LEN} bytes; got {len(iv)}")


def encrypt_stream(
    key: bytes,
    iv: bytes,
    src: IO[bytes],
    dst: IO[bytes],
    *,
    chunk_size: int = _DEFAULT_CHUNK,
) -> bytes:
    """Encrypt `src` → `dst` using AES-256-GCM. Returns SHA-256 of ciphertext (tag excluded).

    Uses the low-level Cipher API so peak memory is O(chunk_size), not O(file_size).
    AES-GCM uses CTR mode internally, so encryptor.update(chunk) returns ciphertext
    of the same length immediately — no internal buffering.
    """
    _check_lens(key, iv)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    sha = hashlib.sha256()

    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        ct = encryptor.update(chunk)
        if ct:
            dst.write(ct)
            sha.update(ct)

    # finalize() flushes any pending ciphertext (usually none for CTR-based GCM)
    final = encryptor.finalize()
    if final:
        dst.write(final)
        sha.update(final)

    # Append the 16-byte GCM authentication tag (not included in sha256)
    dst.write(encryptor.tag)

    return sha.digest()


def decrypt_stream(
    key: bytes,
    iv: bytes,
    src: IO[bytes],
    dst: IO[bytes],
    *,
    chunk_size: int = _DEFAULT_CHUNK,
) -> None:
    """Decrypt `src` (ciphertext || tag) → `dst`. Raises StreamCryptoError on tamper.

    Uses finalize_with_tag() so the GCM tag can be supplied at end-of-stream
    rather than upfront — enabling true streaming with O(chunk_size + TAG_LEN)
    peak memory. A TAG_LEN-byte sliding window holds back the last 16 bytes
    of the stream; at EOF those bytes are the tag.
    """
    _check_lens(key, iv)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    decryptor = cipher.decryptor()

    # Sliding window: hold back the last TAG_LEN bytes so that at EOF
    # we have the tag without having read the whole stream into memory.
    held = bytearray()
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        held.extend(chunk)
        if len(held) > _TAG_LEN:
            to_process = bytes(held[:-_TAG_LEN])
            del held[:-_TAG_LEN]
            pt = decryptor.update(to_process)
            if pt:
                dst.write(pt)

    if len(held) < _TAG_LEN:
        raise StreamCryptoError("ciphertext too short to contain a GCM tag")

    tag = bytes(held)
    try:
        final = decryptor.finalize_with_tag(tag)
    except InvalidTag as e:
        raise StreamCryptoError("GCM authentication failed (wrong key or tampered data)") from e

    if final:
        dst.write(final)


def decrypt_stream_iter(
    key: bytes,
    iv: bytes,
    src: IO[bytes],
    *,
    chunk_size: int = _DEFAULT_CHUNK,
) -> Iterator[bytes]:
    """Generator version of `decrypt_stream`. Yields plaintext chunks.

    Uses the same sliding-window approach: holds the last 16 bytes back
    to use as the GCM tag at finalize_with_tag time.
    """
    _check_lens(key, iv)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    decryptor = cipher.decryptor()

    held = bytearray()
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        held.extend(chunk)
        if len(held) > _TAG_LEN:
            to_process = bytes(held[:-_TAG_LEN])
            del held[:-_TAG_LEN]
            if to_process:
                pt = decryptor.update(to_process)
                if pt:
                    yield pt

    if len(held) < _TAG_LEN:
        raise StreamCryptoError("ciphertext too short to contain a GCM tag")

    tag = bytes(held)
    try:
        final = decryptor.finalize_with_tag(tag)
    except InvalidTag as e:
        raise StreamCryptoError("GCM authentication failed (wrong key or tampered data)") from e
    if final:
        yield final
