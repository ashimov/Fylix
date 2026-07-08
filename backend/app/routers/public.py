from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from html import escape
from http.client import IncompleteRead
from uuid import UUID

from urllib3.exceptions import ProtocolError

_aiter_log = logging.getLogger("fylix.public.stream")

# Errors that mean "the HTTP client went away mid-download". They are
# normal user behaviour (closed tab, lost Wi-Fi, browser cancel button)
# but urllib3 surfaces them as exceptions which would otherwise be
# captured as ERRORs by Sentry/GlitchTip and pollute the issue tracker.
_CLIENT_DISCONNECT_EXC = (
    ProtocolError,  # urllib3 — wraps IncompleteRead in chunked replies
    IncompleteRead,  # http.client — raw socket close mid-body
    BrokenPipeError,
    ConnectionResetError,
    asyncio.CancelledError,  # ASGI cancels the task when the client drops
)


async def _aiter_from_sync(it: Iterator[bytes]) -> AsyncIterator[bytes]:
    """Wrap a synchronous byte-iterator as an async generator.

    HawkAPI's ``StreamingResponse`` consumes its body via ``async for`` —
    sync generators must be adapted. We iterate in the current task
    (MinIO + decrypt produce chunks in the 4-16 KiB range, small enough
    that yielding to the loop between chunks keeps the event loop
    responsive).

    Client disconnects mid-stream show up here as ProtocolError /
    IncompleteRead from urllib3 once the upstream realises the socket
    is dead, or as CancelledError when the ASGI server cancels our
    task. Either way they are not bugs — log INFO and return.
    """
    try:
        for chunk in it:
            yield chunk
    except _CLIENT_DISCONNECT_EXC as exc:
        _aiter_log.info("client disconnected during stream: %s: %s", type(exc).__name__, exc)
        return


from hawkapi import Depends, Request, Response, Router, status
from hawkapi.responses import HTMLResponse, StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from stream_zip import ZIP_64, stream_zip

from app.config import settings
from app.crypto import unwrap_key
from app.crypto.stream import decrypt_stream_iter
from app.db import SessionLocal
from app.http import HTTPException
from app.models import AuditLog, Download, Transfer, TransferFile, TransferRecipient
from app.schemas.transfer import (
    CreateTransferRequest,
    CreateTransferResponse,
    DownloadInfo,
    FileInfo,
    SenderPanelResponse,
)
from app.services.alerts import AlertDispatcher
from app.services.blocklist import BlocklistChecker
from app.services.captcha import CaptchaVerifier
from app.services.email import EmailRenderer, Locale
from app.services.geoip import GeoIPReader
from app.services.policy import PolicyViolation, UploadPolicy
from app.services.settings_service import SettingsService
from app.services.staging import StagingService
from app.services.storage import StorageService, _IteratorIO
from app.services.telegram import TelegramClient
from app.services.transfer import TransferService
from app.state import get_master_key, get_previous_master_key
from app.tus.handler import TUS_VERSION, TusError, TusHandler
from app.utils.http import content_disposition_attachment

router = Router(prefix="/api/transfers", tags=["public"])
download_router = Router(tags=["download"])
config_router = Router(prefix="/api", tags=["public"])


# ---------------------------------------------------------------------------
# Security headers shared by all download endpoints
# ---------------------------------------------------------------------------

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:"


# ---------------------------------------------------------------------------
# Download-page HTML template (hand-rolled; no Jinja dependency needed)
# ---------------------------------------------------------------------------

_DOWNLOAD_PAGE_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Download — Fylix</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
          max-width: 720px; margin: 48px auto; padding: 24px;
          color: #2D2D3A; background: #F7F8FC; }}
  h1 {{ color: #272666; font-size: 28px; margin: 0 0 24px; }}
  .card {{ background: #fff; border: 1px solid #DDE0EC; border-radius: 10px; padding: 24px;
           box-shadow: 0 1px 3px rgba(39,38,102,0.04), 0 4px 12px rgba(39,38,102,0.06); }}
  .meta {{ color: #5A5E7A; font-size: 14px; margin-bottom: 16px; }}
  .msg {{ background: #EDEEF5; padding: 12px 16px; border-radius: 8px;
          white-space: pre-wrap; margin-bottom: 20px; }}
  ul {{ list-style: none; padding: 0; margin: 0 0 24px; }}
  li {{ padding: 10px 0; border-bottom: 1px solid #E8EBF4; display: flex;
        justify-content: space-between; }}
  li:last-child {{ border-bottom: none; }}
  a.btn {{ display: inline-block; background: #272666; color: #fff; padding: 12px 24px;
           border-radius: 8px; text-decoration: none; font-weight: 600; }}
  a.btn:hover {{ background: #1c1c50; }}
  footer {{ margin-top: 48px; text-align: center; color: #8A8EA8; font-size: 12px; }}
</style>
</head>
<body>
  <h1>Fylix</h1>
  <div class="card">
    <div class="meta">Expires: {expires_at}</div>
    {message_block}
    <ul>{files_html}</ul>
    <a class="btn" href="/t/{token}/zip" rel="nofollow noreferrer">Download all as ZIP</a>
  </div>
  <footer>Fylix — secure file transfer</footer>
</body>
</html>
"""


def _humansize(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n = n / 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


async def _session() -> AsyncSession:
    async with SessionLocal() as s:
        yield s


_redis_pool: Redis | None = None


def _redis() -> Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis_pool


_email_renderer = EmailRenderer()

_captcha = CaptchaVerifier(secret=settings.hcaptcha_secret)
_blocklist = BlocklistChecker()
_settings_service = SettingsService()
_policy = UploadPolicy(_settings_service)
_telegram = TelegramClient(
    bot_token=settings.telegram_bot_token,
    chat_id=settings.telegram_chat_id,
)
_alerts = AlertDispatcher(_telegram)
_geoip: GeoIPReader | None = None


def _get_geoip() -> GeoIPReader:
    global _geoip
    if _geoip is None:
        _geoip = GeoIPReader(db_path=settings.maxmind_db_path)
    return _geoip


from app.utils.http import client_ip as _client_ip  # noqa: E402, I001


def _email_renderer_dep() -> EmailRenderer:
    return _email_renderer


def _tus_handler(redis: Redis = Depends(_redis)) -> TusHandler:
    staging = StagingService(root=settings.staging_dir)
    return TusHandler(staging=staging, redis=redis)


def _transfer_service() -> TransferService:
    return TransferService(staging=StagingService(root=settings.staging_dir))


def _storage() -> StorageService:
    return StorageService(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )


async def _load_ready_transfer(
    session: AsyncSession, token: str
) -> tuple[Transfer, list[TransferFile]]:
    row = await session.execute(select(Transfer).where(Transfer.token == token))
    t = row.scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "not found")
    if t.status != "ready":
        raise HTTPException(404, "not found")
    if t.expires_at <= datetime.now(UTC):
        raise HTTPException(410, "gone")
    if t.wrapped_key is None:
        raise HTTPException(404, "not found")
    files = (
        (await session.execute(select(TransferFile).where(TransferFile.transfer_id == t.id)))
        .scalars()
        .all()
    )
    return t, list(files)


@config_router.get("/public-config", include_in_schema=False)
async def public_config() -> dict:
    return {
        "hcaptcha_site_key": settings.hcaptcha_site_key,
        "hcaptcha_required": bool(settings.hcaptcha_secret),
    }


@router.post(
    "",
    response_model=CreateTransferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_transfer(
    payload: CreateTransferRequest,
    request: Request,
    session: AsyncSession = Depends(_session),
    svc: TransferService = Depends(_transfer_service),
) -> CreateTransferResponse:
    client_ip = _client_ip(request)

    # 0) hCaptcha — checked before blocklist so we don't leak blocklist membership
    if _captcha.required:
        ok = await _captcha.verify(payload.captcha_token or "", remote_ip=client_ip)
        if not ok:
            await _alerts.alert(
                session,
                event_type="captcha_failed",
                severity="info",
                message="hCaptcha verification failed",
                ip=client_ip,
                details={"had_token": bool(payload.captcha_token)},
            )
            raise HTTPException(
                status_code=403,
                detail={"error": "captcha_required", "site_key": settings.hcaptcha_site_key},
            )

    # 1) Blocklist
    if await _blocklist.check_ip(session, client_ip):
        await _alerts.alert(
            session,
            event_type="blocklist_hit",
            severity="warn",
            message=f"IP {client_ip} is on blocklist",
            ip=client_ip,
            details={"kind": "ip"},
        )
        raise HTTPException(status_code=403, detail={"error": "blocked"})
    sender = str(payload.sender_email)
    if await _blocklist.check_email(session, sender):
        await _alerts.alert(
            session,
            event_type="blocklist_hit",
            severity="warn",
            message=f"email {sender} is on blocklist",
            ip=client_ip,
            details={"kind": "email", "email": sender},
        )
        raise HTTPException(status_code=403, detail={"error": "blocked"})
    if await _blocklist.check_email_domain(session, sender):
        await _alerts.alert(
            session,
            event_type="blocklist_hit",
            severity="warn",
            message=f"domain of {sender} is on blocklist",
            ip=client_ip,
            details={"kind": "domain", "email": sender},
        )
        raise HTTPException(status_code=403, detail={"error": "blocked"})

    # 2) GeoIP
    sender_country: str | None = None
    geoip = _get_geoip()
    geoip_enabled = await _settings_service.get_bool(session, "geoip_enabled", False)
    allowed_countries = await _settings_service.get_list(
        session, "geoip_countries", ["KZ", "UZ", "KG"]
    )
    if geoip.enabled:
        sender_country = geoip.country(client_ip)
        if geoip_enabled and not geoip.is_country_allowed(client_ip, allowed=allowed_countries):
            await _alerts.alert(
                session,
                event_type="geo_blocked",
                severity="warn",
                message=f"country {sender_country} not allowed",
                ip=client_ip,
                details={"country": sender_country, "allowed": allowed_countries},
            )
            raise HTTPException(status_code=403, detail={"error": "country_not_allowed"})

    # 3) Upload policy
    try:
        await _policy.check(
            session,
            files=payload.files,
            recipient_count=len(payload.recipient_emails),
        )
    except PolicyViolation as e:
        await _alerts.alert(
            session,
            event_type="policy_reject",
            severity="info",
            message=e.reason,
            ip=client_ip,
            details={"reason": e.reason, "status": e.status_code},
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": "policy_violation", "reason": e.reason},
        ) from None

    # Good — create the transfer.
    resp = await svc.create(
        session,
        payload,
        sender_ip=client_ip,
        sender_ua=request.headers.get("user-agent"),
        sender_country=sender_country,
        public_base_url="",  # relative URLs: same-origin in prod, vite-proxied in dev
    )
    await session.commit()
    return resp


@router.head(
    "/{transfer_id:uuid}/files/{file_id:uuid}",
    status_code=status.HTTP_200_OK,
)
async def tus_head(
    transfer_id: UUID,
    file_id: UUID,
    session: AsyncSession = Depends(_session),
    tus: TusHandler = Depends(_tus_handler),
) -> Response:
    try:
        state = await tus.handle_head(session, transfer_id, file_id)
    except TusError as e:
        raise HTTPException(e.status_code, e.detail) from None
    return Response(
        status_code=200,
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Offset": str(state.current_offset),
            "Upload-Length": str(state.declared_length),
            "Cache-Control": "no-store",
        },
    )


@router.patch(
    "/{transfer_id:uuid}/files/{file_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def tus_patch(
    transfer_id: UUID,
    file_id: UUID,
    request: Request,
    session: AsyncSession = Depends(_session),
    tus: TusHandler = Depends(_tus_handler),
) -> Response:
    content_type = request.headers.get("content-type", "")
    if content_type != "application/offset+octet-stream":
        raise HTTPException(415, "Content-Type must be application/offset+octet-stream")
    try:
        upload_offset = int(request.headers.get("upload-offset", ""))
    except ValueError:
        raise HTTPException(400, "invalid Upload-Offset header") from None

    body = await request.body()
    try:
        state = await tus.handle_patch(
            session, transfer_id, file_id, upload_offset, io.BytesIO(body)
        )
    except TusError as e:
        raise HTTPException(e.status_code, e.detail) from None
    await session.commit()
    return Response(
        status_code=204,
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Upload-Offset": str(state.current_offset),
        },
    )


# ---------------------------------------------------------------------------
# Download endpoints — mounted on download_router (no prefix, /t/{token}/...)
# ---------------------------------------------------------------------------


@download_router.get("/t/{token}")
async def download_page(
    token: str,
    session: AsyncSession = Depends(_session),
) -> HTMLResponse:
    t, files = await _load_ready_transfer(session, token)
    files_html = "".join(
        f"<li><span>{escape(f.filename)}</span>" f"<span>{_humansize(f.size_bytes)}</span></li>"
        for f in files
    )
    message_block = f'<div class="msg">{escape(t.message)}</div>' if t.message else ""
    html = _DOWNLOAD_PAGE_TMPL.format(
        expires_at=t.expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        message_block=message_block,
        files_html=files_html,
        token=escape(token),
    )
    return HTMLResponse(
        content=html,
        headers={**SECURITY_HEADERS, "Content-Security-Policy": PAGE_CSP},
    )


@download_router.get("/t/{token}/file/{file_id:uuid}")
async def download_file(
    token: str,
    file_id: UUID,
    request: Request,
    session: AsyncSession = Depends(_session),
    storage: StorageService = Depends(_storage),
    redis: Redis = Depends(_redis),
    email_renderer: EmailRenderer = Depends(_email_renderer_dep),
) -> StreamingResponse:
    import json as _json

    t, files = await _load_ready_transfer(session, token)
    tf = next((f for f in files if f.id == file_id), None)
    if tf is None:
        raise HTTPException(404, "not found")

    master_key = get_master_key()
    file_key = unwrap_key(
        master_key,
        t.wrapped_key,
        previous_master_key=get_previous_master_key(),
    )

    client_ip = _client_ip(request)
    geoip = _get_geoip()
    download_country = None
    with contextlib.suppress(Exception):
        download_country = geoip.country(client_ip)

    # Record the Download row BEFORE returning StreamingResponse so it is
    # persisted even if the client disconnects mid-transfer.
    session.add(
        Download(
            transfer_id=t.id,
            file_id=tf.id,
            ip=client_ip,
            country=download_country,
            ua=request.headers.get("user-agent"),
            bytes_sent=tf.size_bytes,
        )
    )

    # Enqueue download-notice email to sender before committing the session.
    try:
        notice = email_renderer.render_download_notice(
            Locale.RU,
            download_ip=client_ip,
            download_country=download_country,
            file_count=1,
            at=datetime.now(UTC),
        )
        await redis.lpush(  # type: ignore[misc]
            "email:queue",
            _json.dumps(
                {
                    "to": t.sender_email,
                    "subject": notice.subject,
                    "html": notice.html,
                    "text": notice.text,
                }
            ),
        )
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).exception("download_file: failed to enqueue notice email")

    await session.commit()

    # Capture locals for the generator closure (avoid holding session open).
    _object_key = tf.object_key
    _iv = tf.iv
    _file_key = file_key

    def _stream_decrypted_file() -> Iterator[bytes]:
        """Generator: pipes MinIO ciphertext stream through decrypt_stream_iter."""
        ciphertext_stream = storage.get_stream(_object_key)
        wrapped = _IteratorIO(iter(ciphertext_stream))
        yield from decrypt_stream_iter(_file_key, _iv, wrapped)

    return StreamingResponse(
        _aiter_from_sync(_stream_decrypted_file()),
        content_type="application/octet-stream",
        headers={
            **SECURITY_HEADERS,
            "Content-Length": str(tf.size_bytes),
            "Content-Disposition": content_disposition_attachment(
                tf.filename, ascii_fallback=tf.safe_filename
            ),
        },
    )


@download_router.get("/t/{token}/zip")
async def download_zip(
    token: str,
    request: Request,
    session: AsyncSession = Depends(_session),
    storage: StorageService = Depends(_storage),
    redis: Redis = Depends(_redis),
    email_renderer: EmailRenderer = Depends(_email_renderer_dep),
) -> StreamingResponse:
    import json as _json

    t, files = await _load_ready_transfer(session, token)
    master_key = get_master_key()
    file_key = unwrap_key(
        master_key,
        t.wrapped_key,
        previous_master_key=get_previous_master_key(),
    )

    client_ip = _client_ip(request)
    geoip = _get_geoip()
    download_country = None
    with contextlib.suppress(Exception):
        download_country = geoip.country(client_ip)

    # Record one Download row per file in the ZIP (per-file telemetry).
    total_bytes = 0
    for f in files:
        session.add(
            Download(
                transfer_id=t.id,
                file_id=f.id,
                ip=client_ip,
                country=download_country,
                ua=request.headers.get("user-agent"),
                bytes_sent=f.size_bytes,
            )
        )
        total_bytes += f.size_bytes or 0

    # Enqueue email notice to sender
    try:
        notice = email_renderer.render_download_notice(
            Locale.RU,
            download_ip=client_ip,
            download_country=download_country,
            file_count=len(files),
            at=datetime.now(UTC),
        )
        await redis.lpush(  # type: ignore[misc]
            "email:queue",
            _json.dumps(
                {
                    "to": t.sender_email,
                    "subject": notice.subject,
                    "html": notice.html,
                    "text": notice.text,
                }
            ),
        )
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).exception("download_zip: failed to enqueue notice email")

    # Telegram notification (direct, not through alerts which is for security severity)
    try:
        country_str = download_country or "—"
        await _telegram.send(
            f"📥 *Fylix download*\n"
            f"Transfer: `{t.id}`\n"
            f"Files: {len(files)}  Size: {total_bytes} bytes\n"
            f"IP: `{client_ip}`  Country: {country_str}\n"
            f"To: {t.sender_email}"
        )
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).exception("telegram download notice failed")

    await session.commit()

    # UTC-aware — stream_zip expects tz-aware; naive datetime produces wrong
    # timestamps on any non-UTC host.
    now = datetime.now(UTC)
    # 0o600: owner rw-only when extracted
    perms = 0o600
    _zip_file_key = file_key

    def _file_plaintext_iter(object_key: str, iv: bytes) -> Iterator[bytes]:
        ciphertext_stream = storage.get_stream(object_key)
        wrapped = _IteratorIO(iter(ciphertext_stream))
        yield from decrypt_stream_iter(_zip_file_key, iv, wrapped)

    def _entries():  # type: ignore[return]
        for f in files:
            yield (
                f.safe_filename,
                now,
                perms,
                ZIP_64,
                _file_plaintext_iter(f.object_key, f.iv),
            )

    zip_stream = stream_zip(_entries())

    return StreamingResponse(
        _aiter_from_sync(zip_stream),
        content_type="application/zip",
        headers={
            **SECURITY_HEADERS,
            "Content-Disposition": content_disposition_attachment(f"{t.id}.zip"),
        },
    )


# ---------------------------------------------------------------------------
# Sender management panel — /s/{manage_token}
# ---------------------------------------------------------------------------


async def _load_by_manage_token(session: AsyncSession, manage_token: str) -> Transfer:
    row = await session.execute(select(Transfer).where(Transfer.manage_token == manage_token))
    t = row.scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "not found")
    return t


@download_router.get("/s/{manage_token}", response_model=SenderPanelResponse)
async def sender_panel(
    manage_token: str,
    session: AsyncSession = Depends(_session),
) -> SenderPanelResponse:
    t = await _load_by_manage_token(session, manage_token)
    files = (
        (await session.execute(select(TransferFile).where(TransferFile.transfer_id == t.id)))
        .scalars()
        .all()
    )
    recipients = (
        (
            await session.execute(
                select(TransferRecipient).where(TransferRecipient.transfer_id == t.id)
            )
        )
        .scalars()
        .all()
    )
    downloads = (
        (
            await session.execute(
                select(Download)
                .where(Download.transfer_id == t.id)
                .order_by(Download.started_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return SenderPanelResponse(
        transfer_id=t.id,
        status=t.status,
        sender_email=t.sender_email,
        recipient_emails=[r.email for r in recipients],
        message=t.message,
        created_at=t.created_at,
        expires_at=t.expires_at,
        download_token=t.token if t.status == "ready" else None,
        files=[
            FileInfo(
                filename=f.filename,
                size_bytes=f.size_bytes,
                mime_type=f.mime_type,
            )
            for f in files
        ],
        downloads=[
            DownloadInfo(
                ip=str(d.ip),
                country=d.country,
                ua=d.ua,
                started_at=d.started_at,
                completed_at=d.completed_at,
                bytes_sent=d.bytes_sent,
                aborted=d.aborted,
            )
            for d in downloads
        ],
    )


@download_router.delete("/s/{manage_token}", status_code=status.HTTP_204_NO_CONTENT)
async def sender_delete(
    manage_token: str,
    request: Request,
    session: AsyncSession = Depends(_session),
    storage: StorageService = Depends(_storage),
) -> Response:
    t = await _load_by_manage_token(session, manage_token)
    if t.status in ("deleted",):
        # idempotent — already deleted
        return Response(status_code=204)
    # even if MinIO has trouble, proceed with DB state change so the
    # link no longer resolves. Admin can sweep orphaned objects later.
    with contextlib.suppress(Exception):
        storage.delete_transfer(t.id)
    t.status = "deleted"
    t.wrapped_key = None
    t.deleted_at = datetime.now(UTC)
    session.add(
        AuditLog(
            ts=datetime.now(UTC),
            event_type="sender_delete",
            severity="info",
            ip=(_client_ip(request) if request.client else None),
            transfer_id=t.id,
            details={"by": "manage_token"},
        )
    )
    await session.commit()
    return Response(status_code=204)


@download_router.post("/s/{manage_token}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def sender_revoke(
    manage_token: str,
    request: Request,
    session: AsyncSession = Depends(_session),
) -> Response:
    t = await _load_by_manage_token(session, manage_token)
    if t.status in ("revoked", "deleted", "expired", "infected"):
        return Response(status_code=204)
    t.status = "revoked"
    t.revoked_at = datetime.now(UTC)
    session.add(
        AuditLog(
            ts=datetime.now(UTC),
            event_type="sender_revoke",
            severity="info",
            ip=(_client_ip(request) if request.client else None),
            transfer_id=t.id,
            details={"by": "manage_token"},
        )
    )
    await session.commit()
    return Response(status_code=204)
