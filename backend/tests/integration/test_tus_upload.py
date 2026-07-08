import os
from uuid import UUID

import pytest
from sqlalchemy import text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import TransferFile
from app.schemas.transfer import CreateTransferRequest, FileDescriptor
from app.services.staging import StagingService
from app.services.transfer import TransferService

# When running inside the api container, hit uvicorn directly.
# When running from host, use the nginx TLS proxy via PUBLIC_URL.
_BASE_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _clean_db() -> None:
    import shutil

    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, downloads "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

    shutil.rmtree(app_settings.staging_dir, ignore_errors=True)
    app_settings.staging_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
async def _flush_redis() -> None:
    from redis.asyncio import Redis

    r = Redis.from_url(app_settings.redis_url, decode_responses=False)
    await r.delete("upload:ready")
    await r.aclose()


async def _create_single_file_transfer(size: int = 10) -> tuple[UUID, UUID]:
    staging = StagingService(root=app_settings.staging_dir)
    svc = TransferService(staging=staging)
    req = CreateTransferRequest(
        sender_email="a@b.co",
        recipient_emails=["x@y.co"],
        ttl_days=1,
        files=[FileDescriptor(filename="blob.bin", size=size)],
    )
    async with SessionLocal() as session:
        resp = await svc.create(session, req, sender_ip="127.0.0.1", sender_ua="pt")
        await session.commit()
    async with SessionLocal() as session:
        files = (
            await session.execute(
                TransferFile.__table__.select().where(TransferFile.transfer_id == resp.transfer_id)
            )
        ).all()
        file_id = files[0].id
    return resp.transfer_id, file_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_head_returns_zero_offset_and_declared_length() -> None:
    import httpx

    tid, fid = await _create_single_file_transfer(size=10)
    async with httpx.AsyncClient(base_url=_BASE_URL, verify=False) as c:
        r = await c.head(f"/api/transfers/{tid}/files/{fid}")
    assert r.status_code == 200
    assert r.headers["upload-offset"] == "0"
    assert r.headers["upload-length"] == "10"
    assert r.headers["tus-resumable"] == "1.0.0"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_full_file_triggers_worker_to_ready() -> None:
    """End-to-end: final chunk queues the job, worker picks it up, status=ready.

    The worker is running in this environment, so we can't assert the queue entry
    directly (worker consumes it within milliseconds). Instead we wait for the
    transfer row to flip to status='ready'.
    """
    import asyncio

    import httpx

    from app.models import Transfer

    tid, fid = await _create_single_file_transfer(size=11)
    body = b"hello world"
    async with httpx.AsyncClient(base_url=_BASE_URL, verify=False) as c:
        r = await c.patch(
            f"/api/transfers/{tid}/files/{fid}",
            content=body,
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "0",
                "tus-resumable": "1.0.0",
            },
        )
    assert r.status_code == 204
    assert r.headers["upload-offset"] == "11"

    # Poll for worker to flip status to 'ready'.
    deadline = asyncio.get_running_loop().time() + 15.0
    while asyncio.get_running_loop().time() < deadline:
        async with SessionLocal() as session:
            t = await session.get(Transfer, tid)
            if t is not None and t.status == "ready":
                assert t.wrapped_key is not None
                return
        await asyncio.sleep(0.3)
    pytest.fail(f"transfer {tid} did not reach status=ready within 15s")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_in_two_chunks() -> None:
    import httpx

    tid, fid = await _create_single_file_transfer(size=11)
    async with httpx.AsyncClient(base_url=_BASE_URL, verify=False) as c:
        r1 = await c.patch(
            f"/api/transfers/{tid}/files/{fid}",
            content=b"hello ",
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "0",
            },
        )
        assert r1.status_code == 204
        assert r1.headers["upload-offset"] == "6"

        r2 = await c.patch(
            f"/api/transfers/{tid}/files/{fid}",
            content=b"world",
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "6",
            },
        )
        assert r2.status_code == 204
        assert r2.headers["upload-offset"] == "11"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_rejects_offset_mismatch() -> None:
    import httpx

    tid, fid = await _create_single_file_transfer(size=10)
    async with httpx.AsyncClient(base_url=_BASE_URL, verify=False) as c:
        r = await c.patch(
            f"/api/transfers/{tid}/files/{fid}",
            content=b"x",
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "5",  # file is empty, 5 is wrong
            },
        )
    assert r.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_rejects_chunk_exceeding_declared_length() -> None:
    import httpx

    tid, fid = await _create_single_file_transfer(size=5)
    async with httpx.AsyncClient(base_url=_BASE_URL, verify=False) as c:
        r = await c.patch(
            f"/api/transfers/{tid}/files/{fid}",
            content=b"too-many-bytes",
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "0",
            },
        )
    assert r.status_code == 413
