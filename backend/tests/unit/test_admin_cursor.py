"""Composite-cursor encode/decode for deterministic pagination.

Cursor format `"<iso-ts>|<uuid>"` guarantees (ts, id) tuple comparison in the
WHERE clause — a tie on `ts` no longer silently drops rows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.routers.admin import _decode_cursor, _encode_cursor


def test_encode_decode_roundtrip() -> None:
    ts = datetime(2026, 4, 17, 10, 30, 45, 123456, tzinfo=UTC)
    id_ = UUID("12345678-1234-5678-1234-567812345678")
    encoded = _encode_cursor(ts, id_)
    decoded = _decode_cursor(encoded)
    assert decoded is not None
    ts_out, id_out = decoded
    assert ts_out == ts
    assert id_out == id_


def test_encoded_cursor_is_pipe_delimited() -> None:
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    id_ = uuid4()
    encoded = _encode_cursor(ts, id_)
    assert encoded.count("|") == 1
    left, right = encoded.split("|", 1)
    assert left == ts.isoformat()
    assert right == str(id_)


def test_decode_returns_none_on_missing_separator() -> None:
    assert _decode_cursor("2026-04-17T10:30:45+00:00") is None


def test_decode_returns_none_on_bad_timestamp() -> None:
    assert _decode_cursor(f"not-a-ts|{uuid4()}") is None


def test_decode_returns_none_on_bad_uuid() -> None:
    assert _decode_cursor("2026-04-17T10:30:45+00:00|not-a-uuid") is None


def test_decode_returns_none_on_empty_string() -> None:
    assert _decode_cursor("") is None


def test_different_ids_with_same_timestamp_produce_distinct_cursors() -> None:
    """Key property: timestamps alone are ambiguous — ids disambiguate."""
    ts = datetime(2026, 4, 17, 10, 30, 45, tzinfo=UTC)
    id_a = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    id_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    assert _encode_cursor(ts, id_a) != _encode_cursor(ts, id_b)
