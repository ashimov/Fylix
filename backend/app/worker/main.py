"""Worker entrypoint: loop over Redis queues, dispatch encrypt + email tasks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.config import settings
from app.crypto import load_master_key
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.services.alerts import AlertDispatcher
from app.services.email import EmailRenderer, SmtpSender
from app.services.staging import StagingService
from app.services.storage import StorageService
from app.services.telegram import TelegramClient
from app.worker.dlq import run_consumer_iteration
from app.worker.queues import EMAIL_QUEUE, UPLOAD_READY, pop_job
from app.worker.tasks.cleanup import run_cleanup_once
from app.worker.tasks.defender_poll import run_defender_poll_once
from app.worker.tasks.email_send import process_email_job
from app.worker.tasks.encrypt import process_encrypt_job

log = logging.getLogger("fylix.worker")


async def run_loop() -> None:  # noqa: PLR0915 — composition root, complexity accepted.
    configure_logging(level=settings.log_level.upper())
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            send_default_pii=False,
        )
    # OpenTelemetry bootstrap — links worker spans to the originating
    # api request via the traceparent propagated through the job payload
    # (see hawkapi.observability.tracing.inject_context / extract_context).
    from app.observability import setup_otel

    setup_otel(service_name="fylix-worker")

    master_key = load_master_key(
        settings.master_key_path,
        enforce_perms=(settings.app_env != "development"),
    )
    log.info("worker: master key loaded (%d bytes)", len(master_key))

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    staging = StagingService(root=settings.staging_dir)
    telegram = TelegramClient(
        bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id
    )
    alerts = AlertDispatcher(telegram)
    storage = StorageService(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    storage.ensure_bucket()

    smtp = SmtpSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password,
        sender=settings.smtp_from,
        verify_cert=settings.smtp_verify_cert,
    )

    renderer = EmailRenderer()

    # Periodic cleanup
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    async def _cleanup_tick() -> None:
        import time as _time

        async with SessionLocal() as session:
            try:
                await run_cleanup_once(session=session, staging=staging, storage=storage)
            except Exception:
                log.exception("cleanup tick failed")
                return
        # Write the liveness heartbeat only on success — a failed tick must
        # NOT refresh the timestamp, otherwise the fylix_cleanup_last_run_
        # timestamp alert stays green while crypto-shredding is broken.
        try:
            await redis.set("metrics:cleanup_last_run_ts", int(_time.time()))
        except Exception:
            log.warning("cleanup tick: heartbeat write failed", exc_info=True)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _cleanup_tick,
        "interval",
        seconds=settings.cleanup_interval_seconds,
        id="cleanup_expired",
        max_instances=1,
    )

    if settings.defender_poll_enabled:

        async def _defender_tick() -> None:
            async with SessionLocal() as session:
                try:
                    await run_defender_poll_once(
                        session=session,
                        staging=staging,
                        alerts=alerts,
                    )
                except Exception:
                    log.exception("defender_poll tick failed")

        scheduler.add_job(
            _defender_tick,
            "interval",
            seconds=30,
            id="defender_poll",
            max_instances=1,
        )
    else:
        log.info("defender_poll disabled via DEFENDER_POLL_ENABLED=false")

    scheduler.start()
    log.info(
        "worker: ready — listening on %s + %s, cleanup every %ds",
        UPLOAD_READY,
        EMAIL_QUEUE,
        settings.cleanup_interval_seconds,
    )

    async def _handle_upload(job: dict[str, Any]) -> None:
        try:
            transfer_id = UUID(job["transfer_id"])
        except (KeyError, ValueError) as exc:
            raise ValueError("bad upload job payload: missing or invalid transfer_id") from exc
        async with SessionLocal() as session:
            await process_encrypt_job(
                transfer_id=transfer_id,
                session=session,
                staging=staging,
                storage=storage,
                master_key=master_key,
                redis=redis,
                renderer=renderer,
            )

    async def _handle_email(job: dict[str, Any]) -> None:
        async with SessionLocal() as session:
            await process_email_job(job=job, session=session, sender=smtp)

    async def upload_consumer() -> None:
        while True:
            job = await pop_job(redis, UPLOAD_READY, timeout=10)
            if job is None:
                continue
            await run_consumer_iteration(
                queue_name=UPLOAD_READY,
                job=job,
                redis=redis,
                handler=_handle_upload,
            )

    async def email_consumer() -> None:
        while True:
            job = await pop_job(redis, EMAIL_QUEUE, timeout=10)
            if job is None:
                continue
            await run_consumer_iteration(
                queue_name=EMAIL_QUEUE,
                job=job,
                redis=redis,
                handler=_handle_email,
            )

    try:
        await asyncio.gather(upload_consumer(), email_consumer())
    finally:
        scheduler.shutdown(wait=False)
        await redis.aclose()


def main() -> None:
    asyncio.run(run_loop())
