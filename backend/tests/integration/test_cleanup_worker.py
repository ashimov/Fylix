"""Cleanup worker integration test — via direct run_cleanup_once call, not scheduler."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import AuditLog, Transfer
from app.services.staging import StagingService
from app.services.storage import StorageService
from app.worker.tasks.cleanup import run_cleanup_once

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _clean_state() -> None:
    import shutil

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
    await r.aclose()

    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )
    try:
        for obj in storage._client.list_objects(storage.bucket, recursive=True):  # noqa: SLF001
            storage._client.remove_object(storage.bucket, obj.object_name)  # noqa: SLF001
    except Exception:
        pass


async def _create_and_ready(c: httpx.AsyncClient, payload: bytes) -> dict:
    """Create and fully upload a transfer, wait for status=ready."""
    r = await c.post(
        "/api/transfers",
        json={
            "sender_email": "a@b.co",
            "recipient_emails": ["x@y.co"],
            "ttl_days": 1,
            "files": [{"filename": "blob.bin", "size": len(payload)}],
        },
    )
    body = r.json()
    patch = await c.patch(
        urlparse(body["upload_urls"]["blob.bin"]).path,
        content=payload,
        headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
    )
    assert patch.status_code == 204

    deadline = asyncio.get_running_loop().time() + 15.0
    while asyncio.get_running_loop().time() < deadline:
        async with SessionLocal() as session:
            t = await session.get(Transfer, UUID(body["transfer_id"]))
            if t is not None and t.status == "ready":
                return body
        await asyncio.sleep(0.3)
    raise AssertionError("transfer never ready")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_marks_expired_and_deletes_minio() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        body = await _create_and_ready(c, b"payload-to-expire")
    transfer_id = UUID(body["transfer_id"])

    # Force-expire: set expires_at to the past
    async with SessionLocal() as session:
        t = await session.get(Transfer, transfer_id)
        t.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    # Confirm MinIO has the object before cleanup
    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )
    assert list(storage.list_transfer_keys(transfer_id)) != []

    # Run cleanup
    staging = StagingService(root=app_settings.staging_dir)
    async with SessionLocal() as session:
        processed = await run_cleanup_once(session=session, staging=staging, storage=storage)
    assert processed == 1

    # Verify state
    async with SessionLocal() as session:
        t = await session.get(Transfer, transfer_id)
        assert t.status == "expired"
        assert t.wrapped_key is None
        assert t.deleted_at is not None

        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.event_type == "expired")))
            .scalars()
            .all()
        )
        assert len(audits) == 1

    assert list(storage.list_transfer_keys(transfer_id)) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_skips_non_expired() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        body = await _create_and_ready(c, b"live")
    transfer_id = UUID(body["transfer_id"])

    staging = StagingService(root=app_settings.staging_dir)
    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )
    async with SessionLocal() as session:
        processed = await run_cleanup_once(session=session, staging=staging, storage=storage)
    assert processed == 0

    async with SessionLocal() as session:
        t = await session.get(Transfer, transfer_id)
        assert t.status == "ready"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_does_not_touch_revoked_or_deleted() -> None:
    """Revoked transfers keep wrapped_key for forensics; deleted ones already cleaned.
    Cleanup should only affect status='ready'."""
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        body_r = await _create_and_ready(c, b"revoked")
        body_d = await _create_and_ready(c, b"deleted")

        # Revoke one, delete one
        await c.post(f"/s/{body_r['manage_token']}/revoke")
        await c.delete(f"/s/{body_d['manage_token']}")

    # Pre-age both (simulated expiry)
    async with SessionLocal() as session:
        for b in (body_r, body_d):
            t = await session.get(Transfer, UUID(b["transfer_id"]))
            t.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    staging = StagingService(root=app_settings.staging_dir)
    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )
    async with SessionLocal() as session:
        processed = await run_cleanup_once(session=session, staging=staging, storage=storage)
    assert processed == 0  # neither ready

    async with SessionLocal() as session:
        tr = await session.get(Transfer, UUID(body_r["transfer_id"]))
        td = await session.get(Transfer, UUID(body_d["transfer_id"]))
        assert tr.status == "revoked"
        assert tr.wrapped_key is not None  # kept
        assert td.status == "deleted"
        assert td.wrapped_key is None  # already shredded on delete
