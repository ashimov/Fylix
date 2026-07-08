"""Prometheus metrics endpoint.

Exposes `/metrics` in the standard text exposition format. Resilient to
Redis outages so the scraper never marks the target as down for transient
backend issues.

Currently emits two custom gauges:

  fylix_worker_queue_depth{queue="..."}
    Redis LLEN observed at scrape time. Covers the live worker queues
    and their `:dlq` siblings.

  fylix_cleanup_last_run_timestamp
    Unix timestamp of the last successful cleanup tick (written by the
    worker scheduler on every tick; read from Redis key
    `metrics:cleanup_last_run_ts` on scrape). Zero = never run. Pair
    with an alert like
        time() - fylix_cleanup_last_run_timestamp > 600
    (10 min vs expected 5-min cadence) — if it fires, expired transfers
    remain decryptable past their TTL, violating the crypto-shred SLA.

The endpoint is intentionally protected at the Nginx layer via the same
`$admin_allowed` CIDR gate as `/admin` and `/api/admin` — it MUST NOT be
reachable from the public internet.
"""
from __future__ import annotations

import logging
from typing import Annotated

from hawkapi import Router, Depends, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    generate_latest,
)
from redis.asyncio import Redis

from app.config import settings

log = logging.getLogger(__name__)

router = Router(tags=["metrics"])

# Own registry (not the default global) — makes the exposition deterministic
# and decoupled from any library that might register to the default.
_REGISTRY = CollectorRegistry()

_QUEUE_DEPTH = Gauge(
    "fylix_worker_queue_depth",
    "Current length of a Redis worker queue (observed at scrape time).",
    labelnames=("queue",),
    registry=_REGISTRY,
)

_CLEANUP_HEARTBEAT = Gauge(
    "fylix_cleanup_last_run_timestamp",
    "Unix timestamp of the last successful cleanup tick. 0 = never run.",
    registry=_REGISTRY,
)

_OBSERVED_QUEUES: tuple[str, ...] = (
    "upload:ready",
    "email:queue",
    "upload:ready:dlq",
    "email:queue:dlq",
)

_CLEANUP_HEARTBEAT_KEY = "metrics:cleanup_last_run_ts"

_redis_singleton: Redis | None = None


def get_redis() -> Redis:
    """Lazily-initialised Redis client for metric collection.

    A dedicated connection pool for the scrape path avoids contention with
    request-path consumers. Overridden in tests via `app.dependency_overrides`.
    """
    global _redis_singleton  # noqa: PLW0603
    if _redis_singleton is None:
        _redis_singleton = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis_singleton


async def _observe_queue_depths(redis: Redis) -> None:
    for q in _OBSERVED_QUEUES:
        try:
            depth = await redis.llen(q)  # type: ignore[misc]
        except Exception:  # noqa: BLE001 — metrics must never crash the scrape.
            log.warning("metrics: LLEN %s failed", q, exc_info=True)
            depth = 0
        _QUEUE_DEPTH.labels(queue=q).set(float(depth))


async def _observe_cleanup_heartbeat(redis: Redis) -> None:
    try:
        raw = await redis.get(_CLEANUP_HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001 — metrics must never crash the scrape.
        log.warning("metrics: GET %s failed", _CLEANUP_HEARTBEAT_KEY, exc_info=True)
        raw = None
    if raw is None:
        _CLEANUP_HEARTBEAT.set(0.0)
        return
    try:
        ts = float(raw.decode() if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError):
        ts = 0.0
    _CLEANUP_HEARTBEAT.set(ts)


@router.get("/metrics", include_in_schema=False)
async def metrics(redis: Annotated[Redis, Depends(get_redis)]) -> Response:
    await _observe_queue_depths(redis)
    await _observe_cleanup_heartbeat(redis)
    payload = generate_latest(_REGISTRY)
    return Response(content=payload, content_type=CONTENT_TYPE_LATEST)
