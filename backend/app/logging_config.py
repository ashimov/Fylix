"""Structured JSON logging for Fylix.

Every log line is emitted as a single JSON object on stdout with a
stable field set so Grafana Loki / OpenSearch / ELK / even `jq` can
pivot on `request_id` across nginx access logs → api logs → worker
logs → downstream SMTP/Telegram attempts.

Standard fields:
  - ts:          ISO-8601 UTC timestamp, millisecond precision
  - level:       INFO | WARNING | ERROR | CRITICAL | DEBUG
  - logger:      dotted logger name (e.g. "app.routers.admin")
  - msg:         interpolated log message
  - request_id:  (optional) correlation id from the contextvar
  - exc:         (optional) exception traceback for log.exception()
  - *:           any `extra={}` fields merged in (transfer_id, etc.)

Keeping zero external deps: no python-json-logger, no structlog. 30
lines of stdlib is the right trade vs one more supply-chain hop.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.context import current_request_id

# LogRecord attributes we intentionally DO NOT surface in the JSON output
# either because they're internal plumbing (args, msg, exc_text) or because
# they're noise (pathname, thread/process ids). Keep the schema minimal so
# log shippers don't index thousands of useless fields.
_RESERVED: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = current_request_id()
        if rid is not None:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge caller-supplied extra={...} fields.
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in payload:
                # Don't let a rogue extra={} shadow a core field.
                continue
            payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(*, level: str = "INFO") -> None:
    """Install the JSON formatter as the root handler.

    Safe to call multiple times — the previous handlers are cleared so
    uvicorn/gunicorn/pytest default handlers don't emit duplicate lines
    on top of our JSON stream.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    # Remove anything pre-existing (uvicorn adds its own by default).
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Silence the double-emit from uvicorn's named loggers by routing them
    # through the root handler with propagate=True (the default) but make
    # sure they have no handlers of their own.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            logger.removeHandler(h)
        logger.propagate = True
