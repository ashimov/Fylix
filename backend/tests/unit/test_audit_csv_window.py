"""Audit CSV export date-window validation.

Prevents accidental "dump the whole table" (OOM + sequential scan) by
requiring both since/until and capping the span at 90 days.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hawkapi import HTTPException

from app.routers.admin import _CSV_MAX_WINDOW_DAYS, _validate_audit_window


def _ts(day: int) -> datetime:
    return datetime(2026, 4, day, 12, 0, 0, tzinfo=UTC)


def test_missing_both_endpoints_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_audit_window(None, None)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "missing_range"


def test_missing_since_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_audit_window(None, _ts(10))
    assert exc.value.detail["error"] == "missing_range"


def test_missing_until_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_audit_window(_ts(1), None)
    assert exc.value.detail["error"] == "missing_range"


def test_inverted_range_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_audit_window(_ts(10), _ts(5))
    assert exc.value.detail["error"] == "bad_range"


def test_zero_width_range_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_audit_window(_ts(10), _ts(10))
    assert exc.value.detail["error"] == "bad_range"


def test_window_at_exactly_max_days_is_accepted() -> None:
    since = _ts(1)
    until = since + timedelta(days=_CSV_MAX_WINDOW_DAYS)
    s, u = _validate_audit_window(since, until)
    assert s == since
    assert u == until


def test_window_one_second_over_max_is_rejected() -> None:
    since = _ts(1)
    until = since + timedelta(days=_CSV_MAX_WINDOW_DAYS) + timedelta(seconds=1)
    with pytest.raises(HTTPException) as exc:
        _validate_audit_window(since, until)
    assert exc.value.detail["error"] == "window_too_large"


def test_small_valid_window_is_accepted() -> None:
    since = _ts(1)
    until = _ts(8)
    s, u = _validate_audit_window(since, until)
    assert s == since
    assert u == until
