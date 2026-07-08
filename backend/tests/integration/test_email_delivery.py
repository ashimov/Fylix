"""End-to-end email delivery via mailpit."""
import asyncio
import os

import httpx
import pytest
from sqlalchemy import text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.worker.queues import EMAIL_QUEUE

from .conftest import needs_mailpit


MAILPIT_API = os.environ.get("MAILPIT_URL", "http://mailpit:8025")


@pytest.fixture(autouse=True)
async def _reset_mailpit() -> None:
    # Delete all messages from mailpit before each test.
    async with httpx.AsyncClient() as c:
        try:
            await c.delete(f"{MAILPIT_API}/api/v1/messages")
        except Exception:
            pass
    async with SessionLocal() as session:
        await session.execute(text(
            "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, "
            "downloads, audit_log RESTART IDENTITY CASCADE"
        ))
        await session.commit()
    from redis.asyncio import Redis
    r = Redis.from_url(app_settings.redis_url, decode_responses=False)
    await r.delete(EMAIL_QUEUE)
    await r.aclose()


@needs_mailpit()
@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_job_delivered_to_mailpit() -> None:
    """Push a job into email:queue, worker sends it, mailpit receives it."""
    from redis.asyncio import Redis
    import json

    r = Redis.from_url(app_settings.redis_url, decode_responses=False)
    await r.lpush(EMAIL_QUEUE, json.dumps({
        "to": "test@example.com",
        "subject": "Hello from Fylix test",
        "html": "<p>Hi</p>",
        "text": "Hi",
    }))
    await r.aclose()

    # Poll mailpit for the message
    deadline = asyncio.get_running_loop().time() + 15
    async with httpx.AsyncClient() as c:
        while asyncio.get_running_loop().time() < deadline:
            resp = await c.get(f"{MAILPIT_API}/api/v1/messages")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("total", 0) >= 1:
                    msgs = data["messages"]
                    subjects = [m["Subject"] for m in msgs]
                    assert "Hello from Fylix test" in subjects
                    return
            await asyncio.sleep(0.3)
    pytest.fail("mailpit never received the test email")
