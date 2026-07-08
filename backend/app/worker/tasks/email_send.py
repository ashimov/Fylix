"""Consume email:queue and send via SmtpSender."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TransferRecipient
from app.services.email import SmtpSender

log = logging.getLogger(__name__)


async def process_email_job(
    *,
    job: dict,
    session: AsyncSession,
    sender: SmtpSender,
) -> None:
    to = job.get("to")
    subject = job.get("subject")
    html = job.get("html")
    text = job.get("text")
    recipient_id = job.get("recipient_id")

    if not (to and subject and html and text):
        log.warning("email: bad job payload missing fields: %r", job)
        return

    try:
        await sender.send(to=to, subject=subject, html=html, text=text)
        status = "sent"
    except Exception:  # aiosmtplib.SMTPException and friends
        log.exception("email send failed: to=%s", to)
        status = "failed"

    if recipient_id:
        try:
            r = await session.get(TransferRecipient, UUID(recipient_id))
            if r is not None:
                r.email_status = status
                if status == "sent":
                    r.email_sent_at = datetime.now(timezone.utc)
                await session.commit()
        except Exception:
            log.exception("email: failed to update recipient %s", recipient_id)
