"""Structured JSON log formatter — contracts for every log line Fylix emits."""

from __future__ import annotations

import json
import logging

from app.context import _request_id, set_request_id
from app.logging_config import JsonFormatter


def _format(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter().format(record))


def _record(
    *,
    level: int = logging.INFO,
    msg: str = "hello",
    name: str = "fylix.test",
    args: tuple | None = None,
    exc_info: object | None = None,
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    rec = logging.LogRecord(
        name=name,
        level=level,
        pathname="x.py",
        lineno=1,
        msg=msg,
        args=args or (),
        exc_info=exc_info,
    )
    if extra:
        for k, v in extra.items():
            setattr(rec, k, v)
    return rec


def test_core_fields_always_present() -> None:
    out = _format(_record(msg="boot"))
    assert out["level"] == "INFO"
    assert out["logger"] == "fylix.test"
    assert out["msg"] == "boot"
    assert "ts" in out


def test_timestamp_is_iso8601_utc() -> None:
    out = _format(_record())
    ts = str(out["ts"])
    # Example: 2026-04-17T15:04:05.123+00:00
    assert "T" in ts
    assert ts.endswith("+00:00") or ts.endswith("Z")


def test_format_args_are_interpolated() -> None:
    out = _format(_record(msg="user %s did %s", args=("alice", "login")))
    assert out["msg"] == "user alice did login"


def test_level_name_propagates() -> None:
    assert _format(_record(level=logging.WARNING))["level"] == "WARNING"
    assert _format(_record(level=logging.ERROR))["level"] == "ERROR"


def test_request_id_absent_when_contextvar_unset() -> None:
    out = _format(_record())
    assert "request_id" not in out


def test_request_id_injected_from_contextvar() -> None:
    token = set_request_id("abc-123")
    try:
        out = _format(_record())
        assert out["request_id"] == "abc-123"
    finally:
        _request_id.reset(token)


def test_extra_fields_are_merged() -> None:
    out = _format(_record(extra={"transfer_id": "T-42", "status": "ready"}))
    assert out["transfer_id"] == "T-42"
    assert out["status"] == "ready"


def test_exception_info_serialised() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _record(level=logging.ERROR, msg="failure", exc_info=sys.exc_info())
    out = _format(rec)
    assert "exc" in out
    assert "ValueError: boom" in str(out["exc"])


def test_output_is_valid_json_single_line() -> None:
    formatted = JsonFormatter().format(_record(msg="line1\nline2"))
    # Must parse cleanly; embedded newline inside the quoted msg is OK.
    parsed = json.loads(formatted)
    assert parsed["msg"] == "line1\nline2"


def test_reserved_logrecord_fields_not_leaked() -> None:
    """Noisy internal LogRecord attributes (pathname, thread, process) must
    not clutter the JSON output — we only surface what ops need."""
    out = _format(_record(msg="ok"))
    for noise in ("pathname", "process", "thread", "args", "exc_text"):
        assert noise not in out
