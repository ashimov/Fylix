"""Metrics endpoint — Prometheus exposition + worker queue depth gauge."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from hawkapi import HawkAPI
from hawkapi.testing import TestClient

import app.routers.metrics as metrics_mod
from app.routers.metrics import router


def _new_app() -> HawkAPI:
    return HawkAPI(
        health_url=None,
        readyz_url=None,
        livez_url=None,
        docs_url=None,
        redoc_url=None,
        scalar_url=None,
        openapi_url=None,
    )


@pytest.fixture(autouse=True)
def _reset_redis_singleton() -> Iterator[None]:
    # The metrics module caches a Redis client as a module-level singleton;
    # each test replaces it, and we clear it between tests so the next test
    # doesn't see a stale fake.
    metrics_mod._redis_singleton = None
    yield
    metrics_mod._redis_singleton = None


def _client_with_fake_redis(
    *, heartbeat: bytes | str | None = None, **llen_values: int
) -> TestClient:
    """Mount the metrics router with a fake redis whose `llen` and `get` are
    deterministic. `heartbeat` controls the value returned for the cleanup
    heartbeat Redis key (None = never-run)."""
    app = _new_app()
    app.include_router(router)

    fake = AsyncMock()

    async def _llen(key: bytes | str) -> int:
        name = key.decode() if isinstance(key, bytes) else str(key)
        return llen_values.get(name, 0)

    async def _get(_key: bytes | str) -> bytes | str | None:
        return heartbeat

    fake.llen.side_effect = _llen
    fake.get.side_effect = _get
    metrics_mod._redis_singleton = fake
    return TestClient(app)


def test_metrics_endpoint_returns_prometheus_exposition() -> None:
    client = _client_with_fake_redis()
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "version=0.0.4" in r.headers["content-type"]


def test_metrics_includes_queue_depth_gauge() -> None:
    client = _client_with_fake_redis()
    r = client.get("/metrics")
    assert "# HELP fylix_worker_queue_depth" in r.text
    assert "# TYPE fylix_worker_queue_depth gauge" in r.text


def test_metrics_gauge_reflects_llen() -> None:
    client = _client_with_fake_redis(**{"upload:ready": 42, "email:queue": 7})
    r = client.get("/metrics")
    body = r.text
    assert 'fylix_worker_queue_depth{queue="upload:ready"} 42.0' in body
    assert 'fylix_worker_queue_depth{queue="email:queue"} 7.0' in body


def test_metrics_resilient_to_redis_failure() -> None:
    app = _new_app()
    app.include_router(router)
    fake = AsyncMock()
    fake.llen.side_effect = ConnectionError("redis down")
    metrics_mod._redis_singleton = fake
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "fylix_worker_queue_depth" in r.text
    assert 'fylix_worker_queue_depth{queue="upload:ready"} 0.0' in r.text


def test_metrics_rescrape_refreshes_values() -> None:
    """Subsequent scrapes must re-observe live queue depths, not a stale cache."""
    depths: dict[str, int] = {"upload:ready": 1, "email:queue": 2}

    app = _new_app()
    app.include_router(router)
    fake = AsyncMock()

    async def _llen(key: bytes | str) -> int:
        name = key.decode() if isinstance(key, bytes) else str(key)
        return depths.get(name, 0)

    fake.llen.side_effect = _llen
    metrics_mod._redis_singleton = fake
    client = TestClient(app)

    r1 = client.get("/metrics")
    assert 'fylix_worker_queue_depth{queue="upload:ready"} 1.0' in r1.text

    depths["upload:ready"] = 99
    r2 = client.get("/metrics")
    assert 'fylix_worker_queue_depth{queue="upload:ready"} 99.0' in r2.text


# --- Cleanup heartbeat gauge ---------------------------------------------


def test_cleanup_heartbeat_defaults_to_zero_when_key_absent() -> None:
    client = _client_with_fake_redis()
    r = client.get("/metrics")
    assert "fylix_cleanup_last_run_timestamp 0.0" in r.text


def test_cleanup_heartbeat_reflects_redis_value() -> None:
    # Worker writes int(time.time()) on every successful cleanup tick.
    # Use a small value so Prometheus doesn't switch to scientific notation
    # in the exposition format (it does at ~1e9).
    client = _client_with_fake_redis(heartbeat=b"12345")
    r = client.get("/metrics")
    assert "fylix_cleanup_last_run_timestamp 12345.0" in r.text


def test_cleanup_heartbeat_tolerates_garbage_value() -> None:
    # Corrupt Redis value → gauge at 0, endpoint stays up.
    client = _client_with_fake_redis(heartbeat=b"not-a-number")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "fylix_cleanup_last_run_timestamp 0.0" in r.text


def test_cleanup_heartbeat_accepts_str_value() -> None:
    # Redis with decode_responses=True returns str, not bytes.
    client = _client_with_fake_redis(heartbeat="6789")
    r = client.get("/metrics")
    assert "fylix_cleanup_last_run_timestamp 6789.0" in r.text
