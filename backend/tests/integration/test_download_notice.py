"""Downloading a file enqueues a notice email to the sender."""

import asyncio
import os
import shutil
from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import text

from app.config import settings as app_settings
from app.db import SessionLocal

from .conftest import needs_mailpit

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")
MAILPIT_API = os.environ.get("MAILPIT_URL", "http://mailpit:8025")


@pytest.fixture(autouse=True)
async def _reset_all() -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, "
                "downloads, audit_log RESTART IDENTITY CASCADE"
            )
        )
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
async def test_download_sends_notice_to_sender() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        # Create transfer
        resp = await c.post(
            "/api/transfers",
            json={
                "sender_email": "alice@example.com",
                "recipient_emails": ["bob@x.co"],
                "ttl_days": 1,
                "files": [{"filename": "f.txt", "size": 5}],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        download_token = body["download_token"]
        manage_token = body["manage_token"]

        # Extract file_id from the upload URL path
        # upload_urls: {"f.txt": "https://host/api/transfers/{tid}/files/{fid}"}
        upload_url_path = urlparse(body["upload_urls"]["f.txt"]).path
        file_id = upload_url_path.rstrip("/").split("/")[-1]

        # Upload the file
        patch = await c.patch(
            upload_url_path,
            content=b"hello",
            headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
        )
        assert patch.status_code == 204

        # Wait for transfer to become ready by polling the sender panel
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            panel = await c.get(f"/s/{manage_token}")
            if panel.status_code == 200 and panel.json().get("status") == "ready":
                break
            await asyncio.sleep(0.3)
        else:
            pytest.fail("transfer never ready")

        # Clear mailpit (drop upload-time emails)
        async with httpx.AsyncClient() as mc:
            await mc.delete(f"{MAILPIT_API}/api/v1/messages")

        # Download the file
        dl = await c.get(f"/t/{download_token}/file/{file_id}")
        assert dl.status_code == 200

    # Wait for notice email to arrive in mailpit
    deadline = asyncio.get_running_loop().time() + 15
    async with httpx.AsyncClient() as mc:
        while asyncio.get_running_loop().time() < deadline:
            resp = await mc.get(f"{MAILPIT_API}/api/v1/messages")
            if resp.status_code == 200 and resp.json().get("total", 0) >= 1:
                msgs = resp.json()["messages"]
                to = {m["To"][0]["Address"] for m in msgs}
                assert "alice@example.com" in to
                return
            await asyncio.sleep(0.4)
    pytest.fail("no notice email arrived within 15s")
