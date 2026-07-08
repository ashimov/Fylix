import io
import os
import zipfile
import asyncio
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import Transfer

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _clean_state() -> None:
    import shutil

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


async def _wait_ready(transfer_id: UUID, timeout: float = 15.0) -> Transfer:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        async with SessionLocal() as session:
            t = await session.get(Transfer, transfer_id)
            if t is not None and t.status == "ready":
                return t
        await asyncio.sleep(0.3)
    raise AssertionError(f"transfer {transfer_id} never ready")


async def _upload(c: httpx.AsyncClient, file_map: dict[str, bytes]) -> tuple[str, str]:
    """POST create + PATCH each file. Returns (token, transfer_id)."""
    from urllib.parse import urlparse

    resp = await c.post(
        "/api/transfers",
        json={
            "sender_email": "s@e.co",
            "recipient_emails": ["r@e.co"],
            "message": "Here you go.",
            "ttl_days": 1,
            "files": [{"filename": n, "size": len(b)} for n, b in file_map.items()],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    for name, payload in file_map.items():
        url_path = urlparse(body["upload_urls"][name]).path
        patch = await c.patch(
            url_path,
            content=payload,
            headers={
                "content-type": "application/offset+octet-stream",
                "upload-offset": "0",
                "tus-resumable": "1.0.0",
            },
        )
        assert patch.status_code == 204
    await _wait_ready(UUID(body["transfer_id"]))
    return body["download_token"], body["transfer_id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_download_page_renders_html() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        token, _ = await _upload(c, {"hello.txt": b"hello world"})
        r = await c.get(f"/t/{token}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "hello.txt" in r.text
    assert "Download all as ZIP" in r.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_download_page_returns_404_for_unknown_token() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.get("/t/nonexistent_token_abc123")
    assert r.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_file_download_roundtrip() -> None:
    payload = b"The quick brown fox jumps over the lazy dog." * 100  # 4.4 KB
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        token, tid = await _upload(c, {"fox.txt": payload})
        # Get file_id from DB
        async with SessionLocal() as session:
            from app.models import TransferFile
            from sqlalchemy import select
            f = (await session.execute(
                select(TransferFile).where(TransferFile.transfer_id == UUID(tid))
            )).scalar_one()
            file_id = f.id

        r = await c.get(f"/t/{token}/file/{file_id}")
    assert r.status_code == 200
    assert r.content == payload
    assert r.headers["content-disposition"].startswith("attachment")
    assert 'filename="fox.txt"' in r.headers["content-disposition"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zip_download_multi_file() -> None:
    files = {
        "a.txt": b"alpha content" * 50,
        "b.bin": bytes(range(256)) * 4,
        "c.md": b"# heading\n\nparagraph.\n",
    }
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        token, _ = await _upload(c, files)
        r = await c.get(f"/t/{token}/zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert names == set(files.keys())
    for name, payload in files.items():
        assert zf.read(name) == payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_download_records_download_row() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        token, tid = await _upload(c, {"file.bin": b"xyz"})
        async with SessionLocal() as session:
            from app.models import TransferFile, Download
            from sqlalchemy import select
            f = (await session.execute(
                select(TransferFile).where(TransferFile.transfer_id == UUID(tid))
            )).scalar_one()
            file_id = f.id

        await c.get(f"/t/{token}/file/{file_id}")

    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Download).where(Download.transfer_id == UUID(tid))
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].file_id == file_id
    assert rows[0].bytes_sent == 3
