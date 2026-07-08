"""Redis queue name constants and helpers.

We use plain Redis lists with LPUSH/BRPOP rather than streams for simplicity.
A crashed worker loses the in-flight job — this is acceptable in Phase 2
because uploads are resumable (client can POST/tus again) and the state is
reconstructible from DB (status=uploading, staging files present).

Every payload is auto-tagged with the current request_id (when present in
the contextvar) so the worker side of the chain can rebind it and keep
logs correlatable across HTTP → queue → task boundaries.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.context import current_request_id

UPLOAD_READY_QUEUE = "upload:ready"

# Aliases used by worker/main.py
UPLOAD_READY = UPLOAD_READY_QUEUE
CLEANUP_TICK = "cleanup:tick"
EMAIL_QUEUE = "email:queue"

# Reserved key in every job payload — consumers pop this before dispatching
# the handler so the same request_id appears in every log line from the
# worker's run of the job.
REQUEST_ID_KEY = "request_id"


async def push_job(redis: Redis, queue: str, payload: dict[str, Any]) -> None:
    # Only inject if caller hasn't already populated the field — lets
    # background tasks (scheduler, defender poll) push without stomping
    # an explicitly-supplied id.
    if REQUEST_ID_KEY not in payload:
        rid = current_request_id()
        if rid is not None:
            payload = {**payload, REQUEST_ID_KEY: rid}
    await redis.lpush(queue, json.dumps(payload).encode("utf-8"))  # type: ignore[misc]


async def pop_job(redis: Redis, queue: str, *, timeout: int = 5) -> dict[str, Any] | None:
    """Blocking pop with timeout. Returns None on timeout so caller can loop."""
    result = await redis.brpop([queue], timeout=timeout)  # type: ignore[misc]
    if result is None:
        return None
    _queue_name, raw = result
    job: dict[str, Any] = json.loads(raw)
    return job
