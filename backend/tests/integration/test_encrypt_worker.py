"""End-to-end test: POST create → tus PATCH → worker encrypts → DB shows ready, MinIO has ciphertext."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import Transfer, TransferFile
from app.services.storage import StorageService

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _clean_state() -> None:
    import shutil

    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, "
                "downloads, audit_log "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

    # Clear staging dir (container-local path)
    shutil.rmtree(app_settings.staging_dir, ignore_errors=True)
    app_settings.staging_dir.mkdir(parents=True, exist_ok=True)

    from redis.asyncio import Redis

    r = Redis.from_url(app_settings.redis_url)
    await r.delete("upload:ready")
    await r.aclose()

    # Clear MinIO bucket
    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )
    # Best-effort: list and delete everything. Catch any failure silently since
    # the bucket might already be empty.
    try:
        for obj in storage._client.list_objects(storage.bucket, recursive=True):  # noqa: SLF001
            storage._client.remove_object(storage.bucket, obj.object_name)  # noqa: SLF001
    except Exception:
        pass


async def _wait_for_status(transfer_id: UUID, target: str, timeout: float = 15.0) -> Transfer:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        async with SessionLocal() as session:
            t = await session.get(Transfer, transfer_id)
            if t is not None and t.status == target:
                return t
        await asyncio.sleep(0.3)
    raise AssertionError(f"transfer {transfer_id} never reached status={target}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_upload_encrypt_pipeline() -> None:
    payload = b"The quick brown fox jumps over the lazy dog." * 10  # 440 bytes

    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        resp = await c.post(
            "/api/transfers",
            json={
                "sender_email": "s@e.co",
                "recipient_emails": ["r@e.co"],
                "ttl_days": 1,
                "files": [{"filename": "fox.txt", "size": len(payload)}],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        transfer_id = UUID(body["transfer_id"])
        file_url = body["upload_urls"]["fox.txt"]
        # file_url starts with the public_url (e.g. https://localhost/...) but
        # our BASE points at http://localhost:8000. Extract just the path.
        from urllib.parse import urlparse

        file_path = urlparse(file_url).path

        patch = await c.patch(
            file_path,
            content=payload,
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "0",
                "tus-resumable": "1.0.0",
            },
        )
        assert patch.status_code == 204

    # Worker should eventually flip status to ready
    transfer = await _wait_for_status(transfer_id, "ready", timeout=15.0)
    assert transfer.wrapped_key is not None
    assert len(transfer.wrapped_key) == 40  # AES-KW of 32-byte plaintext → 40 bytes

    # DB: TransferFile rows should be updated with iv, sha256_cipher, mime_type
    async with SessionLocal() as session:
        files = (
            (
                await session.execute(
                    select(TransferFile).where(TransferFile.transfer_id == transfer_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(files) == 1
    tf = files[0]
    assert tf.iv != b"\x00" * 12  # overwritten with random IV
    assert tf.sha256_cipher != b"\x00" * 32  # overwritten with ciphertext hash
    assert tf.mime_type.startswith("text/") or tf.mime_type == "application/octet-stream"

    # MinIO should have the encrypted object
    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )
    ct = b"".join(storage.get_stream(tf.object_key))
    assert len(ct) == len(payload) + 16  # plaintext + 16-byte GCM tag

    # Staging directory for this transfer should be cleaned up
    assert not (app_settings.staging_dir / str(transfer_id)).exists()
