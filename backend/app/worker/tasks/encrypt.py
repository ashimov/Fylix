"""Encrypt-and-store task.

Triggered when all files of a transfer are uploaded to staging.
Transforms plaintext in staging -> ciphertext in MinIO, updates DB, shreds staging.

Idempotency: a Redis ``SET NX`` lock on ``transfer:{id}:encrypting`` prevents
concurrent dequeues (queue race or DLQ replay) from encrypting the same
transfer twice. Double-encryption with a fresh IV would silently overwrite
MinIO ciphertext while any existing downloader is mid-stream; the lock
closes that window.
"""

from __future__ import annotations

import json as _json
import logging
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from uuid import UUID

import magic  # python-magic
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt_stream, wrap_key
from app.models import AuditLog, Transfer, TransferFile, TransferRecipient
from app.services.email import EmailRenderer, Locale
from app.services.staging import StagingService
from app.services.storage import StorageService
from app.worker.queues import EMAIL_QUEUE

log = logging.getLogger(__name__)

# Redis lock TTL — generous upper bound on any single encrypt, including
# worst-case 2 GB spill-to-disk + MinIO upload on a loaded box. Far longer
# than any realistic run; acts purely as a safety net if the worker crashes
# without releasing the lock.
_LOCK_TTL_SECONDS = 600


def _encrypt_lock_key(transfer_id: UUID) -> str:
    return f"transfer:{transfer_id}:encrypting"


class EncryptError(RuntimeError):
    pass


async def process_encrypt_job(
    *,
    session: AsyncSession,
    transfer_id: UUID,
    staging: StagingService,
    storage: StorageService,
    master_key: bytes,
    redis: Redis,
    renderer: EmailRenderer,
) -> None:
    # Atomic SET NX EX guards against DLQ replays and concurrent dequeues
    # that would otherwise encrypt the same transfer twice — overwriting
    # the MinIO object with a fresh IV and silently corrupting ciphertext
    # for any client already downloading.
    lock_key = _encrypt_lock_key(transfer_id)
    acquired = await redis.set(lock_key, b"1", nx=True, ex=_LOCK_TTL_SECONDS)
    if not acquired:
        log.warning(
            "encrypt: another worker is already processing transfer %s, skipping",
            transfer_id,
        )
        return

    try:
        transfer = await session.get(Transfer, transfer_id)
        if transfer is None:
            log.warning("encrypt: transfer %s not found", transfer_id)
            return
        if transfer.status != "uploading":
            # Already processed or in an unexpected state — e.g. admin
            # flipped status manually, or a previous worker completed.
            log.warning(
                "encrypt: transfer %s has status %s, skipping",
                transfer_id,
                transfer.status,
            )
            return

        files = (
            (
                await session.execute(
                    select(TransferFile).where(TransferFile.transfer_id == transfer_id)
                )
            )
            .scalars()
            .all()
        )

        try:
            # One file_key shared across all files in this transfer.
            file_key = secrets.token_bytes(32)

            for tf in files:
                plaintext_path = staging.file_path(transfer_id, tf.id, tf.safe_filename)
                if not plaintext_path.exists():
                    raise EncryptError(
                        f"staging file missing for transfer={transfer_id} "
                        f"file={tf.id}: {plaintext_path}"
                    )
                actual_size = plaintext_path.stat().st_size
                if actual_size != tf.size_bytes:
                    raise EncryptError(
                        f"size mismatch for {tf.filename}: "
                        f"declared={tf.size_bytes}, actual={actual_size}"
                    )

                # MIME sniff on first 2 KiB (python-magic).
                with open(plaintext_path, "rb") as f:
                    head = f.read(2048)
                mime = magic.from_buffer(head, mime=True) or "application/octet-stream"

                iv = secrets.token_bytes(12)
                # Use SpooledTemporaryFile: in-memory under 64 MiB, swaps to disk above.
                # Caps RAM at the threshold; swap target is the staging dir (already on
                # the encrypted-at-host LUKS volume per DEPLOYMENT.md).
                with SpooledTemporaryFile(
                    max_size=64 * 1024 * 1024,
                    dir=str(staging.transfer_dir(transfer_id)),
                ) as ct_buf:
                    with open(plaintext_path, "rb") as src:
                        sha256 = encrypt_stream(file_key, iv, src, ct_buf)
                    ct_len = ct_buf.tell()
                    ct_buf.seek(0)
                    storage.put_file(tf.object_key, ct_buf, ct_len)

                tf.iv = iv
                tf.sha256_cipher = sha256
                tf.mime_type = mime

            # Wrap the file_key with master_key and mark transfer ready.
            transfer.wrapped_key = wrap_key(master_key, file_key)
            transfer.status = "ready"

            session.add(
                AuditLog(
                    event_type="upload_complete",
                    severity="info",
                    transfer_id=transfer_id,
                    details={
                        "file_count": len(files),
                        "total_size": sum(f.size_bytes for f in files),
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )
            )

            # Zero out file_key from Python memory (best-effort).
            del file_key

            await session.commit()
            log.info("encrypt: transfer %s done, %d file(s)", transfer_id, len(files))

            # Enqueue recipient + sender-confirm emails.
            await _enqueue_transfer_emails(
                session=session,
                redis=redis,
                renderer=renderer,
                transfer=transfer,
                transfer_id=transfer_id,
                files=files,
            )

        except Exception as exc:
            log.exception("encrypt: transfer %s failed: %s", transfer_id, exc)
            await session.rollback()

            # Mark infected in a fresh transaction so we don't lose the status change.
            transfer = await session.get(Transfer, transfer_id)
            if transfer is not None:
                transfer.status = "infected"
                transfer.infected_at = datetime.now(UTC)
                session.add(
                    AuditLog(
                        event_type="upload_failed",
                        severity="error",
                        transfer_id=transfer_id,
                        details={"error": str(exc)},
                    )
                )
                await session.commit()

            # Best-effort: remove any partial MinIO objects.
            try:
                storage.delete_transfer(transfer_id)
            except Exception:
                log.exception("encrypt: cleanup MinIO failed for %s", transfer_id)

        finally:
            # Always shred staging plaintext whether success or failure.
            staging.secure_delete(transfer_id)

    finally:
        # Release the lock so future jobs for this transfer can proceed
        # (e.g., on manual re-queue after operator intervention). Best
        # effort — TTL will clear it if Redis is unreachable here.
        try:
            await redis.delete(lock_key)
        except Exception:
            log.warning("encrypt: failed to release lock %s", lock_key, exc_info=True)


async def _enqueue_transfer_emails(
    *,
    session: AsyncSession,
    redis: Redis,
    renderer: EmailRenderer,
    transfer: Transfer,
    transfer_id: UUID,
    files: Sequence[TransferFile],
) -> None:
    """Build and push email jobs for all recipients + sender confirm."""
    try:
        base = settings.public_url.rstrip("/")
        download_url = f"{base}/t/{transfer.token}"

        recipients = (
            (
                await session.execute(
                    select(TransferRecipient).where(TransferRecipient.transfer_id == transfer_id)
                )
            )
            .scalars()
            .all()
        )

        locale = Locale.RU  # default; per-recipient locale deferred to Phase 5

        jobs = []

        for r in recipients:
            mail = renderer.render_recipient(
                locale,
                sender_email=transfer.sender_email,
                message=transfer.message,
                download_url=download_url,
                file_count=len(files),
                total_bytes=transfer.total_size,
                expires_at=transfer.expires_at,
            )
            jobs.append(
                {
                    "to": r.email,
                    "subject": mail.subject,
                    "html": mail.html,
                    "text": mail.text,
                    "recipient_id": str(r.id),
                }
            )

        confirm = renderer.render_sender_confirm(
            locale,
            download_url=download_url,
            recipients=[r.email for r in recipients],
            file_count=len(files),
            expires_at=transfer.expires_at,
        )
        jobs.append(
            {
                "to": transfer.sender_email,
                "subject": confirm.subject,
                "html": confirm.html,
                "text": confirm.text,
            }
        )

        pipe = redis.pipeline()
        for job in jobs:
            pipe.lpush(EMAIL_QUEUE, _json.dumps(job))
        await pipe.execute()
        log.info("encrypt: enqueued %d email(s) for transfer %s", len(jobs), transfer_id)

    except Exception:
        log.exception("encrypt: failed to enqueue emails for transfer %s", transfer_id)
