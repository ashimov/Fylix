"""Simulate Defender quarantine by deleting a staging file mid-upload."""

import asyncio
import os
import shutil
from datetime import UTC
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import AuditLog, Transfer, TransferFile
from app.services.alerts import AlertDispatcher
from app.services.staging import StagingService
from app.services.telegram import TelegramClient
from app.worker.tasks.defender_poll import run_defender_poll_once

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_staging_file_flips_transfer_to_infected() -> None:
    # Create transfer, write partial chunk, delete the file, run poll.
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        resp = await c.post(
            "/api/transfers",
            json={
                "sender_email": "a@b.co",
                "recipient_emails": ["x@y.co"],
                "ttl_days": 1,
                "files": [{"filename": "malware.bin", "size": 100}],
            },
        )
        body = resp.json()
        tid = UUID(body["transfer_id"])
        file_url = urlparse(body["upload_urls"]["malware.bin"]).path
        # Write partial chunk so staging dir + file exists
        patch = await c.patch(
            file_url,
            content=b"A" * 50,
            headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
        )
        assert patch.status_code == 204

    # Wait past min_age_seconds, then simulate quarantine by deleting the file.
    await asyncio.sleep(0.5)
    staging = StagingService(root=app_settings.staging_dir)
    async with SessionLocal() as session:
        tf = (
            await session.execute(select(TransferFile).where(TransferFile.transfer_id == tid))
        ).scalar_one()
    path = staging.file_path(tid, tf.id, tf.safe_filename)
    assert path.exists()
    path.unlink()
    assert not path.exists()

    # Artificially age the transfer so the poll picks it up.
    async with SessionLocal() as session:
        from datetime import datetime, timedelta

        t = await session.get(Transfer, tid)
        t.created_at = datetime.now(UTC) - timedelta(seconds=30)
        await session.commit()

    # Run poll directly (use the tiny TG/AlertDispatcher which is a no-op in dev).
    telegram = TelegramClient(bot_token="", chat_id="")
    alerts = AlertDispatcher(telegram)
    async with SessionLocal() as session:
        flipped = await run_defender_poll_once(
            session=session,
            staging=staging,
            alerts=alerts,
            min_age_seconds=10,
        )
    assert flipped == 1

    async with SessionLocal() as session:
        t = await session.get(Transfer, tid)
        assert t.status == "infected"
        assert t.infected_at is not None

        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.transfer_id == tid)))
            .scalars()
            .all()
        )
        kinds = {a.event_type for a in audits}
        assert "defender_quarantine" in kinds


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ignores_transfer_without_staging_dir() -> None:
    """Transfer that never started tus upload → no staging dir → no false flag."""
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        resp = await c.post(
            "/api/transfers",
            json={
                "sender_email": "a@b.co",
                "recipient_emails": ["x@y.co"],
                "ttl_days": 1,
                "files": [{"filename": "nothing.txt", "size": 10}],
            },
        )
        tid = UUID(resp.json()["transfer_id"])

    # Forcibly remove the staging dir that was created by TransferService.
    staging = StagingService(root=app_settings.staging_dir)
    shutil.rmtree(staging.transfer_dir(tid), ignore_errors=True)

    # Age and poll.
    async with SessionLocal() as session:
        from datetime import datetime, timedelta

        t = await session.get(Transfer, tid)
        t.created_at = datetime.now(UTC) - timedelta(seconds=30)
        await session.commit()

    telegram = TelegramClient(bot_token="", chat_id="")
    alerts = AlertDispatcher(telegram)
    async with SessionLocal() as session:
        flipped = await run_defender_poll_once(
            session=session,
            staging=staging,
            alerts=alerts,
            min_age_seconds=10,
        )
    # Should NOT flip — we can't distinguish "never started" from "AV cleanup".
    assert flipped == 0
