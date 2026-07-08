"""Cleanup task: sweep expired transfers, crypto-shred them, delete MinIO objects."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Transfer
from app.services.staging import StagingService
from app.services.storage import StorageService

log = logging.getLogger(__name__)


async def run_cleanup_once(
    *,
    session: AsyncSession,
    staging: StagingService,
    storage: StorageService,
) -> int:
    """Find all expired ready transfers and crypto-shred them.

    Returns the number of transfers processed.
    """
    now = datetime.now(UTC)
    rows = (
        (
            await session.execute(
                select(Transfer).where(
                    Transfer.status == "ready",
                    Transfer.expires_at < now,
                )
            )
        )
        .scalars()
        .all()
    )

    processed = 0
    for t in rows:
        try:
            storage.delete_transfer(t.id)
        except Exception:
            log.exception("cleanup: MinIO delete failed for %s", t.id)

        t.wrapped_key = None
        t.status = "expired"
        t.deleted_at = now

        session.add(
            AuditLog(
                ts=now,
                event_type="expired",
                severity="info",
                transfer_id=t.id,
                details={"reason": "ttl"},
            )
        )

        staging.secure_delete(t.id)
        processed += 1

    if processed > 0:
        await session.commit()
        log.info("cleanup: processed %d expired transfer(s)", processed)

    return processed
