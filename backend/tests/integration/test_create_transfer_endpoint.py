import os

import httpx
import pytest
from sqlalchemy import text

from app.db import SessionLocal

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _clean_db() -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, downloads "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_create_transfer_returns_tokens_and_upload_urls() -> None:
    async with httpx.AsyncClient(base_url=PUBLIC_URL, verify=False) as c:
        r = await c.post(
            "/api/transfers",
            json={
                "sender_email": "sender@example.com",
                "recipient_emails": ["rcpt@example.com"],
                "message": "hello",
                "ttl_days": 3,
                "files": [{"filename": "doc.pdf", "size": 1234}],
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "transfer_id" in body
    assert len(body["download_token"]) >= 32
    assert len(body["manage_token"]) >= 32
    assert "doc.pdf" in body["upload_urls"]
    assert (
        body["upload_urls"]["doc.pdf"].endswith(f"/api/transfers/{body['transfer_id']}/files/")
        is False
    )  # has file_id suffix
    assert "expires_at" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_rejects_empty_files_list() -> None:
    async with httpx.AsyncClient(base_url=PUBLIC_URL, verify=False) as c:
        r = await c.post(
            "/api/transfers",
            json={
                "sender_email": "sender@example.com",
                "recipient_emails": ["rcpt@example.com"],
                "ttl_days": 3,
                "files": [],
            },
        )
    assert r.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_rejects_invalid_sender_email() -> None:
    async with httpx.AsyncClient(base_url=PUBLIC_URL, verify=False) as c:
        r = await c.post(
            "/api/transfers",
            json={
                "sender_email": "not-email",
                "recipient_emails": ["x@y.co"],
                "ttl_days": 3,
                "files": [{"filename": "a.pdf", "size": 1}],
            },
        )
    assert r.status_code == 422
