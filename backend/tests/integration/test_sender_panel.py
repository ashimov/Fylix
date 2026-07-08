"""Sender panel: view, delete, revoke."""

import asyncio
import os
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import AuditLog, Transfer

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

    from app.services.storage import StorageService

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


async def _wait_ready(tid: UUID, timeout: float = 15.0) -> Transfer:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        async with SessionLocal() as session:
            t = await session.get(Transfer, tid)
            if t is not None and t.status == "ready":
                return t
        await asyncio.sleep(0.3)
    raise AssertionError(f"{tid} not ready")


async def _create(c: httpx.AsyncClient, payload: bytes) -> dict:
    r = await c.post(
        "/api/transfers",
        json={
            "sender_email": "alice@example.com",
            "recipient_emails": ["bob@example.com"],
            "message": "hi bob",
            "ttl_days": 1,
            "files": [{"filename": "note.txt", "size": len(payload)}],
        },
    )
    assert r.status_code == 201
    body = r.json()
    patch = await c.patch(
        urlparse(body["upload_urls"]["note.txt"]).path,
        content=payload,
        headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
    )
    assert patch.status_code == 204
    await _wait_ready(UUID(body["transfer_id"]))
    return body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sender_panel_returns_transfer_details_and_downloads() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        body = await _create(c, b"hello bob")
        # download once so there is a Download row
        async with SessionLocal() as session:
            from app.models import TransferFile

            f = (
                await session.execute(
                    select(TransferFile).where(
                        TransferFile.transfer_id == UUID(body["transfer_id"])
                    )
                )
            ).scalar_one()
            file_id = f.id
        await c.get(f"/t/{body['download_token']}/file/{file_id}")

        r = await c.get(f"/s/{body['manage_token']}")
    assert r.status_code == 200
    data = r.json()
    assert data["transfer_id"] == body["transfer_id"]
    assert data["status"] == "ready"
    assert data["sender_email"] == "alice@example.com"
    assert "bob@example.com" in data["recipient_emails"]
    assert data["message"] == "hi bob"
    assert data["download_token"] == body["download_token"]
    assert len(data["files"]) == 1
    assert data["files"][0]["filename"] == "note.txt"
    assert len(data["downloads"]) == 1
    assert data["downloads"][0]["bytes_sent"] == len(b"hello bob")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sender_panel_unknown_token_returns_404() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.get("/s/unknown-manage-token-abc")
    assert r.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sender_delete_crypto_shreds_and_denies_download() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        body = await _create(c, b"secret data")
        token = body["download_token"]
        manage_token = body["manage_token"]

        # Pre-delete: download works
        r = await c.get(f"/t/{token}")
        assert r.status_code == 200

        d = await c.delete(f"/s/{manage_token}")
        assert d.status_code == 204

        # Post-delete: page returns 404
        r2 = await c.get(f"/t/{token}")
        assert r2.status_code == 404

    # DB: wrapped_key is NULL, status=deleted
    async with SessionLocal() as session:
        t = await session.get(Transfer, UUID(body["transfer_id"]))
        assert t.status == "deleted"
        assert t.wrapped_key is None
        assert t.deleted_at is not None
        # Audit
        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.event_type == "sender_delete")))
            .scalars()
            .all()
        )
        assert len(audits) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sender_revoke_denies_download_but_keeps_key() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        body = await _create(c, b"confidential")
        token = body["download_token"]
        manage_token = body["manage_token"]

        revoke = await c.post(f"/s/{manage_token}/revoke")
        assert revoke.status_code == 204

        r = await c.get(f"/t/{token}")
        assert r.status_code == 404

    async with SessionLocal() as session:
        t = await session.get(Transfer, UUID(body["transfer_id"]))
        assert t.status == "revoked"
        assert t.wrapped_key is not None  # kept for forensics
        assert t.revoked_at is not None
