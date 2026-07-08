"""Dead-letter queue helper for worker consumers.

Wraps a single job-handling attempt so that unexpected exceptions (a) do not
kill the consumer coroutine and (b) preserve the payload for human review
by pushing a structured record to `<queue>:dlq`.

DLQ record shape::

    {
      "original_queue": "upload:ready",
      "payload": {...original job dict...},
      "error":   "RuntimeError: <message>",
      "failed_at": "2026-04-17T11:58:02.123456+00:00",
    }

Primary failures (handler exceptions) are the main use case. If the DLQ push
itself fails (e.g. Redis is down), we log and swallow — the worker loop must
keep running regardless of backend health.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.context import _request_id, set_request_id

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


def _dlq_name(queue_name: str) -> str:
    return f"{queue_name}:dlq"


async def run_consumer_iteration(
    *,
    queue_name: str,
    job: dict[str, Any],
    redis: Redis,
    handler: Handler,
) -> None:
    # Rebind the request_id from the job payload so worker logs + any
    # downstream push_job() calls stay on the same correlation chain.
    rid = job.get("request_id")
    token = set_request_id(rid) if isinstance(rid, str) and rid else None
    try:
        await handler(job)
    except Exception as exc:  # noqa: BLE001 — DLQ is the last line of defence.
        log.exception("worker: job failed on %s, moving to DLQ", queue_name)
        record = {
            "original_queue": queue_name,
            "payload": job,
            "error": f"{type(exc).__name__}: {exc}",
            "failed_at": datetime.now(UTC).isoformat(),
        }
        try:
            await redis.lpush(  # type: ignore[misc]
                _dlq_name(queue_name),
                json.dumps(record).encode("utf-8"),
            )
        except Exception:  # noqa: BLE001 — do not crash the consumer loop.
            log.exception("worker: DLQ push itself failed for %s", queue_name)
    finally:
        if token is not None:
            _request_id.reset(token)
