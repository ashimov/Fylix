"""Integration-test configuration.

All async integration tests share a single event loop (session scope) so
that the module-level SQLAlchemy async engine can reuse its connection
pool across tests without "Future attached to a different loop" errors.
"""
import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest

T = TypeVar("T")


async def wait_until(
    predicate: Callable[[], Awaitable[T | None]],
    *,
    timeout: float = 15.0,
    interval: float = 0.3,
    message: str = "predicate never became truthy",
) -> T:
    """Poll an async predicate until it returns a truthy value or deadline hits.

    Drop-in replacement for the hand-rolled
    ``while loop.time() < deadline: ... await asyncio.sleep(...)`` pattern
    that was duplicated across ~12 integration tests. Centralising the
    helper makes the polling cadence consistent on slow CI and makes it
    easy to tune a single timeout knob.

    ``predicate`` is a no-arg async callable; return any truthy value to
    succeed (the value is returned to the caller), ``None`` / ``False`` to
    keep polling. Raises ``AssertionError`` on timeout.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(interval)
    raise AssertionError(f"wait_until timed out after {timeout}s: {message}")


def needs_mailpit():
    """Skip a test when SMTP_HOST is not the dev mailpit catch-all.

    When SMTP points at a real corporate relay, mailpit is empty and all
    tests that poll its API will fail spuriously.
    """
    return pytest.mark.skipif(
        os.environ.get("SMTP_HOST", "mailpit") != "mailpit",
        reason="requires SMTP_HOST=mailpit (dev SMTP catch-all)",
    )


@pytest.fixture(scope="session")
def event_loop():
    """Provide a session-scoped event loop for all async integration tests.

    Required because ``app.db.SessionLocal`` and the underlying asyncpg
    engine are module-level singletons bound to the loop they were
    created on. Per-test event loops trigger "Future attached to a
    different loop".
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def _flush_rl_keys_global() -> None:
    """Clear Redis rate-limit keys before every integration test.

    Prevents rate-limit middleware from blocking legitimate test requests
    when multiple integration tests POST to /api/transfers in the same run.

    Also nullifies settings.updated_by before each test to prevent FK
    violations when admin-settings tests run before admin-login tests in
    the full-suite run order.
    """
    from redis.asyncio import Redis

    from app.config import settings
    from app.db import SessionLocal

    # Null out the FK that settings rows hold against admins — this prevents
    # test_admin_login._reset (DELETE FROM admins) from hitting a FK violation
    # when admin-settings tests left settings.updated_by pointing at a now-
    # deleted admin from a previous test.
    from sqlalchemy import text as _text
    async with SessionLocal() as s:
        await s.execute(_text("UPDATE settings SET updated_by = NULL WHERE updated_by IS NOT NULL"))
        await s.commit()

    r = Redis.from_url(settings.redis_url, decode_responses=False)
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="rl:*", count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break
    await r.aclose()
