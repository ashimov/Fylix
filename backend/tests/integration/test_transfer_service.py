from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Transfer, TransferFile, TransferRecipient
from app.schemas.transfer import CreateTransferRequest, FileDescriptor
from app.services.staging import StagingService
from app.services.transfer import TransferService


@pytest.fixture(autouse=True)
async def _clean_db() -> None:
    """Truncate transfer-related tables before each test to keep them isolated."""
    async with SessionLocal() as session:
        await session.execute(text(
            "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, downloads "
            "RESTART IDENTITY CASCADE"
        ))
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_transfer_persists_rows(tmp_path) -> None:
    staging = StagingService(root=tmp_path)
    svc = TransferService(staging=staging)
    req = CreateTransferRequest(
        sender_email="alice@example.com",
        recipient_emails=["bob@example.com", "carol@example.com"],
        message="please review",
        ttl_days=3,
        files=[
            FileDescriptor(filename="report.pdf", size=1024),
            FileDescriptor(filename="notes.txt", size=256),
        ],
    )
    async with SessionLocal() as session:
        resp = await svc.create(
            session,
            req,
            sender_ip="127.0.0.1",
            sender_ua="pytest",
            sender_country="KZ",
        )
        await session.commit()

    assert isinstance(resp.transfer_id, UUID)
    assert len(resp.download_token) >= 32
    assert len(resp.manage_token) >= 32
    assert resp.expires_at > datetime.now(timezone.utc) + timedelta(days=2)

    async with SessionLocal() as session:
        t = await session.get(Transfer, resp.transfer_id)
        assert t is not None
        assert t.status == "uploading"
        assert t.file_count == 2
        assert t.total_size == 1280
        assert t.sender_country == "KZ"
        recs = (await session.execute(
            select(TransferRecipient).where(TransferRecipient.transfer_id == t.id)
        )).scalars().all()
        assert {r.email for r in recs} == {"bob@example.com", "carol@example.com"}
        files = (await session.execute(
            select(TransferFile).where(TransferFile.transfer_id == t.id)
        )).scalars().all()
        assert {f.filename for f in files} == {"report.pdf", "notes.txt"}

    # Staging dir is NOT created up-front — the tus handler creates it lazily
    # on the first PATCH chunk. This prevents the Defender poll from flagging
    # abandoned transfers as infected (empty dir + missing file = false positive).
    assert not (tmp_path / str(resp.transfer_id)).exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_download_token(tmp_path) -> None:
    staging = StagingService(root=tmp_path)
    svc = TransferService(staging=staging)
    req = CreateTransferRequest(
        sender_email="a@b.co",
        recipient_emails=["x@y.co"],
        ttl_days=1,
        files=[FileDescriptor(filename="a", size=1)],
    )
    async with SessionLocal() as session:
        resp = await svc.create(session, req, sender_ip="127.0.0.1", sender_ua="pt")
        await session.commit()

    async with SessionLocal() as session:
        t = await svc.get_by_download_token(session, resp.download_token)
        assert t is not None
        assert t.id == resp.transfer_id

        assert await svc.get_by_download_token(session, "wrong") is None
