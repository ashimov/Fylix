"""Defender file-disappearance watcher.

Scans for transfers whose staging files have vanished under `uploading` state
— indicating Microsoft Defender (or similar host AV) quarantined the file
mid-upload. Flags the transfer as infected and alerts admins.

Uses file-mtime-ish heuristic: wait at least `min_age_seconds` after transfer
creation before declaring a missing file as "disappeared" — since tus clients
only create the staging file on first PATCH.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Transfer, TransferFile
from app.services.alerts import AlertDispatcher
from app.services.staging import StagingService

log = logging.getLogger(__name__)


async def run_defender_poll_once(
    *,
    session: AsyncSession,
    staging: StagingService,
    alerts: AlertDispatcher,
    min_age_seconds: int = 10,
) -> int:
    """Inspect uploading transfers; flip infected on missing staging files.

    Returns the number of transfers flipped.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=min_age_seconds)

    candidates = (await session.execute(
        select(Transfer).where(
            Transfer.status == "uploading",
            Transfer.created_at < cutoff,
        )
    )).scalars().all()

    flipped = 0
    for transfer in candidates:
        files = (await session.execute(
            select(TransferFile).where(TransferFile.transfer_id == transfer.id)
        )).scalars().all()
        missing: list[str] = []
        for f in files:
            path = staging.file_path(transfer.id, f.id, f.safe_filename)
            # A file is "missing" only if it should have been partially written
            # by now — i.e. the tus HEAD was issued. We approximate by assuming
            # if the directory exists but the file is gone, it was quarantined.
            # If the directory doesn't exist at all, it's a transfer that
            # never started — skip.
            if not staging.transfer_dir(transfer.id).exists():
                continue
            if not path.exists():
                missing.append(f.safe_filename)
        if not missing:
            continue

        transfer.status = "infected"
        transfer.infected_at = now
        session.add(AuditLog(
            ts=now,
            event_type="defender_quarantine",
            severity="critical",
            transfer_id=transfer.id,
            ip=str(transfer.sender_ip),
            details={"missing_files": missing},
        ))
        flipped += 1

    if flipped == 0:
        return 0

    await session.commit()

    # Fire Telegram alerts in separate commits (AlertDispatcher commits each one).
    for transfer in candidates:
        if transfer.status == "infected":
            await alerts.alert(
                session,
                event_type="defender_quarantine_alert",
                severity="critical",
                message=f"Transfer {transfer.id} quarantined by Defender",
                ip=str(transfer.sender_ip),
                transfer_id=transfer.id,
                details={"sender": transfer.sender_email},
            )

    log.info("defender_poll: flipped %d transfer(s) to infected", flipped)
    return flipped
