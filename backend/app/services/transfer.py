"""Create and look up Transfer aggregates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transfer, TransferFile, TransferRecipient
from app.schemas.transfer import CreateTransferRequest, CreateTransferResponse
from app.services.staging import StagingService
from app.services.tokens import generate_download_token, generate_manage_token


class TransferService:
    def __init__(self, *, staging: StagingService) -> None:
        self.staging = staging

    async def create(
        self,
        session: AsyncSession,
        req: CreateTransferRequest,
        *,
        sender_ip: str,
        sender_ua: str | None,
        sender_country: str | None = None,
        sender_city: str | None = None,
        public_base_url: str = "",
    ) -> CreateTransferResponse:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=req.ttl_days)
        transfer_id = uuid4()

        transfer = Transfer(
            id=transfer_id,
            token=generate_download_token(),
            manage_token=generate_manage_token(),
            sender_email=str(req.sender_email),
            sender_ip=sender_ip,
            sender_ua=sender_ua,
            sender_country=sender_country,
            sender_city=sender_city,
            message=req.message,
            status="uploading",
            total_size=req.total_size,
            file_count=req.file_count,
            expires_at=expires,
        )
        session.add(transfer)

        for recipient in req.recipient_emails:
            session.add(
                TransferRecipient(
                    transfer_id=transfer_id,
                    email=str(recipient),
                    email_status="queued",
                )
            )

        upload_urls: dict[str, str] = {}
        for f in req.files:
            safe = self.staging.safe_filename(f.filename)
            ext = "".join(Path(safe).suffixes[-1:]) or None
            file_id = uuid4()
            session.add(
                TransferFile(
                    id=file_id,
                    transfer_id=transfer_id,
                    filename=f.filename,
                    safe_filename=safe,
                    mime_type="application/octet-stream",  # sniffed later by worker
                    extension=ext,
                    size_bytes=f.size,
                    object_key=f"{transfer_id}/{file_id}.enc",
                    iv=b"\x00" * 12,          # placeholder — worker overwrites
                    sha256_cipher=b"\x00" * 32,
                )
            )
            upload_urls[f.filename] = (
                f"{public_base_url}/api/transfers/{transfer_id}/files/{file_id}"
            )

        # Do NOT create the staging dir here — it would trigger the Defender
        # poll false-positive for abandoned transfers (dir exists + file never
        # arrives = looks like AV quarantine). The tus PATCH handler creates
        # the dir lazily on the first chunk via staging.open_write().

        return CreateTransferResponse(
            transfer_id=transfer_id,
            download_token=transfer.token,
            manage_token=transfer.manage_token,
            upload_urls=upload_urls,
            expires_at=expires,
        )

    async def get_by_download_token(
        self, session: AsyncSession, token: str
    ) -> Transfer | None:
        row = await session.execute(
            select(Transfer).where(Transfer.token == token)
        )
        return row.scalar_one_or_none()

    async def get_by_manage_token(
        self, session: AsyncSession, manage_token: str
    ) -> Transfer | None:
        row = await session.execute(
            select(Transfer).where(Transfer.manage_token == manage_token)
        )
        return row.scalar_one_or_none()

    async def get_by_id(
        self, session: AsyncSession, transfer_id: UUID
    ) -> Transfer | None:
        return await session.get(Transfer, transfer_id)
