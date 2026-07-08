import io
import os

import pytest

from app.crypto.stream import StreamCryptoError, decrypt_stream, decrypt_stream_iter, encrypt_stream


def _roundtrip(plaintext: bytes, *, chunk: int = 64) -> bytes:
    key = os.urandom(32)
    iv = os.urandom(12)
    src = io.BytesIO(plaintext)
    ct_buf = io.BytesIO()
    sha = encrypt_stream(key, iv, src, ct_buf, chunk_size=chunk)
    assert isinstance(sha, bytes) and len(sha) == 32

    ct = ct_buf.getvalue()
    # ciphertext = plaintext bytes + 16 bytes GCM tag appended
    assert len(ct) == len(plaintext) + 16

    out = io.BytesIO()
    decrypt_stream(key, iv, io.BytesIO(ct), out, chunk_size=chunk)
    assert out.getvalue() == plaintext
    return ct


def test_encrypt_decrypt_small() -> None:
    _roundtrip(b"hello world")


def test_encrypt_decrypt_empty() -> None:
    _roundtrip(b"")


def test_encrypt_decrypt_large_streaming() -> None:
    # 1 MB, chunked, ensures streaming works across many iterations
    _roundtrip(os.urandom(1 << 20), chunk=4096)


def test_decrypt_tampered_body_raises() -> None:
    key = os.urandom(32)
    iv = os.urandom(12)
    src = io.BytesIO(b"A" * 1024)
    ct_buf = io.BytesIO()
    encrypt_stream(key, iv, src, ct_buf)
    ct = bytearray(ct_buf.getvalue())
    ct[100] ^= 0xFF  # flip a bit in the body

    with pytest.raises(StreamCryptoError, match="authentication"):
        decrypt_stream(key, iv, io.BytesIO(bytes(ct)), io.BytesIO())


def test_decrypt_tampered_tag_raises() -> None:
    key = os.urandom(32)
    iv = os.urandom(12)
    src = io.BytesIO(b"payload")
    ct_buf = io.BytesIO()
    encrypt_stream(key, iv, src, ct_buf)
    ct = bytearray(ct_buf.getvalue())
    ct[-1] ^= 0xFF  # flip the tag

    with pytest.raises(StreamCryptoError, match="authentication"):
        decrypt_stream(key, iv, io.BytesIO(bytes(ct)), io.BytesIO())


def test_encrypt_rejects_bad_key_len() -> None:
    with pytest.raises(StreamCryptoError, match="32 bytes"):
        encrypt_stream(b"short", os.urandom(12), io.BytesIO(), io.BytesIO())


def test_encrypt_rejects_bad_iv_len() -> None:
    with pytest.raises(StreamCryptoError, match="12 bytes"):
        encrypt_stream(os.urandom(32), b"short", io.BytesIO(), io.BytesIO())


def test_decrypt_stream_iter_roundtrip() -> None:
    """decrypt_stream_iter should produce byte-exact plaintext from encrypt_stream output."""
    key = os.urandom(32)
    iv = os.urandom(12)
    plaintext = os.urandom(1 * 1024 * 1024)  # 1 MB

    ct_buf = io.BytesIO()
    encrypt_stream(key, iv, io.BytesIO(plaintext), ct_buf)
    ct_buf.seek(0)

    result = b"".join(decrypt_stream_iter(key, iv, ct_buf))
    assert result == plaintext


def test_decrypt_stream_iter_tamper_raises() -> None:
    """Corrupting the last byte (tag) should raise StreamCryptoError."""
    key = os.urandom(32)
    iv = os.urandom(12)
    plaintext = b"tamper-test-payload"

    ct_buf = io.BytesIO()
    encrypt_stream(key, iv, io.BytesIO(plaintext), ct_buf)
    ct = bytearray(ct_buf.getvalue())
    ct[-1] ^= 0xFF  # corrupt the last byte of the GCM tag

    with pytest.raises(StreamCryptoError, match="authentication"):
        list(decrypt_stream_iter(key, iv, io.BytesIO(bytes(ct))))


import tracemalloc  # noqa: E402


class _NullWriter(io.RawIOBase):
    """Write-only sink that discards all data — keeps output off the heap."""

    def write(self, b: bytes | bytearray | memoryview) -> int:  # type: ignore[override]
        return len(b)


def test_encrypt_stream_peak_memory_bounded_for_large_input() -> None:
    """10 MB input must not cause more than ~4 MB peak above baseline.

    dst is a /dev/null sink so the measurement only covers what the
    implementation itself allocates, not the output buffer growth.
    """
    key = os.urandom(32)
    iv = os.urandom(12)
    payload = os.urandom(10 * 1024 * 1024)  # 10 MB

    # src created before tracing starts; its buffer is already on the heap
    src = io.BytesIO(payload)
    dst = _NullWriter()

    tracemalloc.start()
    before_peak = tracemalloc.get_traced_memory()[1]
    encrypt_stream(key, iv, src, dst, chunk_size=64 * 1024)
    after_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    added = after_peak - before_peak
    # Old implementation: ~20-30 MB peak added (src+intermediate+dst copies).
    # New implementation: ~64 KB chunk + 16 bytes tag + hashing state.
    # Loose bound: 4 MB leaves headroom for Python overhead.
    assert added < 4 * 1024 * 1024, (
        f"encrypt_stream peak memory grew by {added / 1024:.0f} KB for 10 MB input — "
        "expected < 4 MB if truly streaming"
    )


def test_decrypt_stream_peak_memory_bounded_for_large_input() -> None:
    """10 MB ciphertext must not cause more than ~4 MB peak above baseline during decrypt."""
    key = os.urandom(32)
    iv = os.urandom(12)
    payload = os.urandom(10 * 1024 * 1024)

    # Encrypt outside measured region (allowed to use memory)
    ct_buf = io.BytesIO()
    encrypt_stream(key, iv, io.BytesIO(payload), ct_buf)

    # src and dst both pre-allocated before tracing; measurement only sees
    # what decrypt_stream itself allocates internally.
    ct_buf.seek(0)
    out = _NullWriter()

    tracemalloc.start()
    before_peak = tracemalloc.get_traced_memory()[1]
    decrypt_stream(key, iv, ct_buf, out, chunk_size=64 * 1024)
    after_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    added = after_peak - before_peak
    assert added < 4 * 1024 * 1024, (
        f"decrypt_stream peak memory grew by {added / 1024:.0f} KB for 10 MB input — "
        "expected < 4 MB if truly streaming"
    )
