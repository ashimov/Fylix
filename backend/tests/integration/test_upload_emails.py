"""Full POST → PATCH → worker encrypt → mailpit receives recipient + sender emails."""
import asyncio
import os
import shutil
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import Transfer

from .conftest import needs_mailpit


BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")
MAILPIT_API = os.environ.get("MAILPIT_URL", "http://mailpit:8025")


@pytest.fixture(autouse=True)
async def _reset_all() -> None:
    async with SessionLocal() as session:
        await session.execute(text(
            "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, "
            "downloads, audit_log RESTART IDENTITY CASCADE"
        ))
        await session.commit()
    shutil.rmtree(app_settings.staging_dir, ignore_errors=True)
    app_settings.staging_dir.mkdir(parents=True, exist_ok=True)

    from redis.asyncio import Redis
    r = Redis.from_url(app_settings.redis_url)
    await r.delete("upload:ready")
    await r.delete("email:queue")
    await r.aclose()

    async with httpx.AsyncClient() as c:
        try:
            await c.delete(f"{MAILPIT_API}/api/v1/messages")
        except Exception:
            pass


@needs_mailpit()
@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_enqueues_recipient_and_sender_emails() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        resp = await c.post("/api/transfers", json={
            "sender_email": "alice@example.com",
            "recipient_emails": ["bob@example.com"],
            "message": "see files",
            "ttl_days": 1,
            "files": [{"filename": "f.txt", "size": 5}],
        })
        assert resp.status_code == 201
        body = resp.json()
        transfer_id = UUID(body["transfer_id"])
        patch = await c.patch(
            urlparse(body["upload_urls"]["f.txt"]).path,
            content=b"hello",
            headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
        )
        assert patch.status_code == 204

    # Wait for worker to ready + enqueue + SMTP send
    deadline = asyncio.get_running_loop().time() + 20
    async with httpx.AsyncClient() as c:
        while asyncio.get_running_loop().time() < deadline:
            resp = await c.get(f"{MAILPIT_API}/api/v1/messages")
            if resp.status_code == 200 and resp.json().get("total", 0) >= 2:
                msgs = resp.json()["messages"]
                to_set = {m["To"][0]["Address"] for m in msgs}
                assert "bob@example.com" in to_set
                assert "alice@example.com" in to_set
                # Recipient email must contain the download_token URL
                for m in msgs:
                    if m["To"][0]["Address"] == "bob@example.com":
                        detail = await c.get(f"{MAILPIT_API}/api/v1/message/{m['ID']}")
                        assert body["download_token"] in detail.json()["HTML"]
                return
            await asyncio.sleep(0.5)
    pytest.fail("mailpit did not receive 2 emails in 20s")


@needs_mailpit()
@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_recipient_sends_multiple_emails() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        resp = await c.post("/api/transfers", json={
            "sender_email": "s@example.com",
            "recipient_emails": ["a@x.co", "b@x.co", "c@x.co"],
            "ttl_days": 1,
            "files": [{"filename": "f.txt", "size": 3}],
        })
        body = resp.json()
        patch = await c.patch(
            urlparse(body["upload_urls"]["f.txt"]).path,
            content=b"abc",
            headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
        )
        assert patch.status_code == 204

    deadline = asyncio.get_running_loop().time() + 20
    async with httpx.AsyncClient() as c:
        while asyncio.get_running_loop().time() < deadline:
            resp = await c.get(f"{MAILPIT_API}/api/v1/messages")
            if resp.status_code == 200 and resp.json().get("total", 0) >= 4:
                # 3 recipients + 1 sender = 4 emails
                return
            await asyncio.sleep(0.5)
    pytest.fail("expected 4 emails (3 recipients + 1 sender)")
