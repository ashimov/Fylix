"""Worker dead-letter queue — failed jobs go to `<queue>:dlq` instead of
crashing the consumer loop or silently vanishing."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.worker.dlq import run_consumer_iteration


@pytest.mark.asyncio
async def test_successful_handler_does_not_push_to_dlq() -> None:
    fake_redis = AsyncMock()
    seen: list[dict[str, Any]] = []

    async def handler(job: dict[str, Any]) -> None:
        seen.append(job)

    await run_consumer_iteration(
        queue_name="test:q",
        job={"id": 1},
        redis=fake_redis,
        handler=handler,
    )
    assert seen == [{"id": 1}]
    fake_redis.lpush.assert_not_called()


@pytest.mark.asyncio
async def test_failing_handler_pushes_to_dlq() -> None:
    fake_redis = AsyncMock()

    async def handler(_job: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    await run_consumer_iteration(
        queue_name="test:q",
        job={"id": 1, "foo": "bar"},
        redis=fake_redis,
        handler=handler,
    )
    fake_redis.lpush.assert_called_once()
    dest, raw = fake_redis.lpush.call_args[0]
    assert dest == "test:q:dlq"
    record = json.loads(raw)
    assert record["original_queue"] == "test:q"
    assert record["payload"] == {"id": 1, "foo": "bar"}
    assert record["error"].startswith("RuntimeError")
    assert "boom" in record["error"]
    assert "failed_at" in record
    assert record["failed_at"].endswith("+00:00") or record["failed_at"].endswith("Z")


@pytest.mark.asyncio
async def test_failing_handler_does_not_reraise() -> None:
    """Individual job failure must NOT bubble up — worker loop survives."""
    fake_redis = AsyncMock()

    async def handler(_job: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    await run_consumer_iteration(
        queue_name="test:q",
        job={"id": 1},
        redis=fake_redis,
        handler=handler,
    )


@pytest.mark.asyncio
async def test_dlq_push_failure_does_not_crash_worker() -> None:
    """If DLQ push itself fails (Redis down), log and continue — never crash."""
    fake_redis = AsyncMock()
    fake_redis.lpush.side_effect = ConnectionError("redis down")

    async def handler(_job: dict[str, Any]) -> None:
        raise RuntimeError("original failure")

    await run_consumer_iteration(
        queue_name="test:q",
        job={"id": 1},
        redis=fake_redis,
        handler=handler,
    )
