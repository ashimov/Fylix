"""Admin auth + management endpoints.

Mounted under /api/admin (without a router-level prefix here — main.py
sets prefix="/api/admin" when including this router).
"""
from __future__ import annotations

import ipaddress
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from hawkapi import Depends, Request, Response, Router, status
from hawkapi.responses import JSONResponse

from app.http import HTTPException, delete_cookie, set_cookie
from redis.asyncio import Redis
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Admin, AdminAction, AuditLog,
    BlocklistEmail, BlocklistEmailDomain, BlocklistIP,
    Download, Setting, Transfer, TransferFile, TransferRecipient,
)
from app.schemas.admin import (
    AdminActionListResponse, AdminActionRow,
    AdminCreateRequest, AdminCreateResponse, AdminRow, AdminUpdateRequest,
    AdminPublic, AuditListResponse, AuditRow,
    BlocklistAddRequest, BlocklistEntry,
    DownloadDetail, FileDetail, LoginRequest, LoginResponse,
    PatchSettingsRequest,
    RecipientDetail,
    ResetTotpResponse,
    TelegramConfig, TelegramConfigUpdate,
    TransferDetailResponse, TransferListResponse, TransferRow,
)
from app.services.auth import wrap_totp_secret
from app.services import admin_actions
from app.services.auth import AuthService
from app.services.session import SessionStore
from app.services.settings_service import SettingsService
from app.services.storage import StorageService
from app.state import get_master_key, get_previous_master_key

log = logging.getLogger(__name__)

router = Router(prefix="/api/admin", tags=["admin"])


# --- Composite-cursor helpers -------------------------------------------------
# Timestamps alone are NOT a safe cursor under concurrent writes: two rows may
# share a timestamp, and `WHERE created_at < cursor_ts` skips the tail of them.
# Encode and compare (ts, id) as a tuple to guarantee deterministic paging.


def _encode_cursor(ts: datetime, id_: UUID) -> str:
    return f"{ts.isoformat()}|{id_}"


def _decode_cursor(raw: str) -> tuple[datetime, UUID] | None:
    try:
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), UUID(id_str)
    except (ValueError, AttributeError):
        return None


def _cookie_secure() -> bool:
    """Return True unless explicitly disabled via DEV_INSECURE_COOKIES for local dev."""
    if settings.dev_insecure_cookies:
        return False
    return True

# ---------------------------------------------------------------------------
# Module-level service singletons
# ---------------------------------------------------------------------------

_auth = AuthService(
    max_failed_attempts=5,
    lockout_minutes=15,
)
_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


_session_store: SessionStore | None = None


def _get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(_get_redis(), ttl_seconds=30 * 60)
    return _session_store


_storage_svc: StorageService | None = None
_settings_service = SettingsService()


def _get_storage() -> StorageService:
    global _storage_svc
    if _storage_svc is None:
        _storage_svc = StorageService(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    return _storage_svc


async def _session() -> AsyncSession:
    async with SessionLocal() as s:
        yield s


SESSION_COOKIE = "session_id"


from app.utils.http import client_ip as _client_ip  # noqa: E402, I001


# ---------------------------------------------------------------------------
# Auth: login / logout / me
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(_session),
) -> JSONResponse:
    # Lookup admin (citext email → case-insensitive match)
    result = await session.execute(select(Admin).where(Admin.email == payload.email))
    admin = result.scalar_one_or_none()

    # Constant-time dummy verification when user not found.
    if admin is None:
        _auth.verify_password(payload.password, _auth.dummy_hash())
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})

    if admin.disabled:
        raise HTTPException(status_code=403, detail={"error": "disabled"})

    if _auth.is_locked(admin):
        raise HTTPException(status_code=423, detail={"error": "locked"})

    if not _auth.verify_password(payload.password, admin.password_hash):
        _auth.register_failure(admin)
        await session.commit()
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})

    if not admin.totp_enrolled:
        raise HTTPException(status_code=400, detail={"error": "totp_not_enrolled"})

    if admin.totp_secret is None:
        raise HTTPException(status_code=500, detail={"error": "totp_missing"})

    # Support migration: wrapped secrets are 40 bytes (AES-KW), plain base32 is shorter.
    from app.services.auth import is_wrapped_totp, unwrap_totp_secret

    if is_wrapped_totp(admin.totp_secret):
        master = get_master_key()
        totp_secret_str = unwrap_totp_secret(
            master,
            admin.totp_secret,
            previous_master_key=get_previous_master_key(),
        )
    else:
        # Legacy plaintext — still works; run wrap_totp_secrets.py to migrate.
        totp_secret_str = admin.totp_secret.decode("utf-8")
    if not _auth.verify_totp(totp_secret_str, payload.totp_code):
        _auth.register_failure(admin)
        await session.commit()
        raise HTTPException(status_code=401, detail={"error": "invalid_totp"})

    # Success.
    _auth.reset_failures(admin)
    admin.last_login_at = datetime.now(timezone.utc)
    await session.commit()

    sid = await _get_session_store().create(admin_id=admin.id)
    _secure = _cookie_secure()
    body = LoginResponse(
        admin=AdminPublic(
            id=admin.id,
            email=admin.email,
            role=admin.role,
            disabled=admin.disabled,
            totp_enrolled=admin.totp_enrolled,
            last_login_at=admin.last_login_at,
        )
    )
    resp = JSONResponse(body.model_dump(mode="json"))
    set_cookie(
        resp,
        SESSION_COOKIE,
        sid,
        max_age=30 * 60,
        secure=_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return resp


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await _get_session_store().destroy(sid)
    resp = Response(status_code=204)
    delete_cookie(resp, SESSION_COOKIE, path="/")
    return resp


class _AdminCtx:
    """Resolved admin context attached to a protected request."""

    def __init__(self, admin: Admin) -> None:
        self.admin = admin

    @property
    def role(self) -> str:
        return self.admin.role


async def require_session(
    request: Request,
    session: AsyncSession = Depends(_session),
) -> _AdminCtx:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        raise HTTPException(status_code=401, detail={"error": "no_session"})
    data = await _get_session_store().load(sid)
    if data is None:
        raise HTTPException(status_code=401, detail={"error": "expired"})
    # Sliding TTL
    await _get_session_store().touch(sid)

    admin = await session.get(Admin, data.admin_id)
    if admin is None or admin.disabled:
        raise HTTPException(status_code=401, detail={"error": "admin_gone"})
    return _AdminCtx(admin)


async def require_admin_role(
    ctx: _AdminCtx = Depends(require_session),
) -> _AdminCtx:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail={"error": "admin_role_required"})
    return ctx


async def require_viewer_or_admin(
    ctx: _AdminCtx = Depends(require_session),
) -> _AdminCtx:
    if ctx.role not in ("admin", "viewer"):
        raise HTTPException(status_code=403, detail={"error": "role_forbidden"})
    return ctx


@router.get("/me", response_model=AdminPublic)
async def me(ctx: _AdminCtx = Depends(require_session)) -> AdminPublic:
    admin = ctx.admin
    return AdminPublic(
        id=admin.id,
        email=admin.email,
        role=admin.role,
        disabled=admin.disabled,
        totp_enrolled=admin.totp_enrolled,
        last_login_at=admin.last_login_at,
    )


# ---------------------------------------------------------------------------
# Transfers: list / detail / delete / revoke
# ---------------------------------------------------------------------------

@router.get("/transfers", response_model=TransferListResponse)
async def admin_list_transfers(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
    status: str | None = None,
    country: str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> TransferListResponse:
    limit = max(1, min(limit, 200))
    stmt = select(Transfer).order_by(Transfer.created_at.desc(), Transfer.id.desc())
    if status:
        stmt = stmt.where(Transfer.status == status)
    if country:
        stmt = stmt.where(Transfer.sender_country == country)
    if size_min is not None:
        stmt = stmt.where(Transfer.total_size >= size_min)
    if size_max is not None:
        stmt = stmt.where(Transfer.total_size <= size_max)
    # pg_trgm (GIN indexes idx_transfers_sender_email_trgm +
    # idx_transfer_files_filename_trgm) requires >= 3 chars to use the
    # trigram index; shorter queries would trigger a double sequential
    # scan. Ignore short `q` outright rather than degrading the whole
    # admin table scan.
    if q and len(q) >= 3:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Transfer.sender_email.ilike(like),
                Transfer.id.in_(
                    select(TransferFile.transfer_id).where(
                        TransferFile.filename.ilike(like)
                    )
                ),
            )
        )
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is not None:
            cursor_ts, cursor_id = decoded
            stmt = stmt.where(
                tuple_(Transfer.created_at, Transfer.id)
                < tuple_(cursor_ts, cursor_id)  # type: ignore[arg-type]
            )
    stmt = stmt.limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode_cursor(rows[-1].created_at, rows[-1].id)
        if has_more and rows
        else None
    )

    items = [
        TransferRow(
            id=t.id,
            sender_email=t.sender_email,
            sender_ip=str(t.sender_ip),
            sender_country=t.sender_country,
            total_size=t.total_size,
            file_count=t.file_count,
            status=t.status,
            created_at=t.created_at,
            expires_at=t.expires_at,
        )
        for t in rows
    ]
    return TransferListResponse(items=items, next_cursor=next_cursor)


@router.get("/transfers/{transfer_id:uuid}", response_model=TransferDetailResponse)
async def admin_get_transfer(
    transfer_id: UUID,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
) -> TransferDetailResponse:
    t = await session.get(Transfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    files = (await session.execute(
        select(TransferFile).where(TransferFile.transfer_id == transfer_id)
    )).scalars().all()
    recipients = (await session.execute(
        select(TransferRecipient).where(TransferRecipient.transfer_id == transfer_id)
    )).scalars().all()
    downloads = (await session.execute(
        select(Download).where(Download.transfer_id == transfer_id)
        .order_by(Download.started_at.desc())
    )).scalars().all()
    return TransferDetailResponse(
        id=t.id,
        sender_email=t.sender_email,
        sender_ip=str(t.sender_ip),
        sender_country=t.sender_country,
        sender_city=t.sender_city,
        message=t.message,
        status=t.status,
        total_size=t.total_size,
        file_count=t.file_count,
        created_at=t.created_at,
        expires_at=t.expires_at,
        revoked_at=t.revoked_at,
        deleted_at=t.deleted_at,
        infected_at=t.infected_at,
        files=[
            FileDetail(id=f.id, filename=f.filename, size_bytes=f.size_bytes, mime_type=f.mime_type)
            for f in files
        ],
        recipients=[
            RecipientDetail(email=r.email, email_sent_at=r.email_sent_at, email_status=r.email_status)
            for r in recipients
        ],
        downloads=[
            DownloadDetail(
                ip=str(d.ip), country=d.country, ua=d.ua,
                started_at=d.started_at, completed_at=d.completed_at,
                bytes_sent=d.bytes_sent, aborted=d.aborted,
            )
            for d in downloads
        ],
    )


@router.delete("/transfers/{transfer_id:uuid}", status_code=204)
async def admin_delete_transfer(
    transfer_id: UUID,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> Response:
    t = await session.get(Transfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if t.status == "deleted":
        return Response(status_code=204)
    try:
        _get_storage().delete_transfer(transfer_id)
    except Exception:
        # MinIO delete failed — do NOT silently orphan. DB row still gets
        # marked deleted + wrapped_key=NULL (crypto-shred is effective), but
        # the MinIO objects leak until next reconciliation. Log so ops can
        # audit and re-run the cleanup task.
        log.exception(
            "admin_delete_transfer: MinIO delete failed for transfer_id=%s "
            "(DB will be marked deleted, objects may remain in bucket)",
            transfer_id,
        )
    t.status = "deleted"
    t.wrapped_key = None
    t.deleted_at = datetime.now(timezone.utc)
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="delete_transfer",
        target_type="transfer",
        target_id=str(transfer_id),
        ip=_client_ip(request),
    )
    await session.commit()
    return Response(status_code=204)


@router.post("/transfers/{transfer_id:uuid}/revoke", status_code=204)
async def admin_revoke_transfer(
    transfer_id: UUID,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> Response:
    t = await session.get(Transfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if t.status in ("revoked", "deleted", "expired", "infected"):
        return Response(status_code=204)
    t.status = "revoked"
    t.revoked_at = datetime.now(timezone.utc)
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="revoke_transfer",
        target_type="transfer",
        target_id=str(transfer_id),
        ip=_client_ip(request),
    )
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Blocklist CRUD
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)

_BLOCKLIST_KINDS = {"ips", "domains", "emails"}


def _validate_blocklist_value(kind: str, value: str) -> None:
    if kind == "ips":
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": "invalid_ip_or_cidr"})
    elif kind == "domains":
        if not _DOMAIN_RE.match(value.lower()):
            raise HTTPException(status_code=400, detail={"error": "invalid_domain"})
    elif kind == "emails":
        # Basic email check — pydantic EmailStr requires building a model; do simple validation
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise HTTPException(status_code=400, detail={"error": "invalid_email"})
    else:
        raise HTTPException(status_code=404, detail={"error": "unknown_kind"})


@router.get("/blocklist/{kind}", response_model=list[BlocklistEntry])
async def admin_blocklist_list(
    kind: str,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
) -> list[BlocklistEntry]:
    if kind not in _BLOCKLIST_KINDS:
        raise HTTPException(status_code=404, detail={"error": "unknown_kind"})
    if kind == "ips":
        rows = (await session.execute(select(BlocklistIP))).scalars().all()
        return [BlocklistEntry(value=str(r.cidr), reason=r.reason, added_at=r.added_at, expires_at=r.expires_at) for r in rows]
    elif kind == "domains":
        rows = (await session.execute(select(BlocklistEmailDomain))).scalars().all()
        return [BlocklistEntry(value=r.domain, reason=r.reason, added_at=r.added_at, expires_at=r.expires_at) for r in rows]
    else:  # emails
        rows = (await session.execute(select(BlocklistEmail))).scalars().all()
        return [BlocklistEntry(value=r.email, reason=r.reason, added_at=r.added_at, expires_at=r.expires_at) for r in rows]


@router.post("/blocklist/{kind}", status_code=201)
async def admin_blocklist_add(
    kind: str,
    payload: BlocklistAddRequest,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> BlocklistEntry:
    if kind not in _BLOCKLIST_KINDS:
        raise HTTPException(status_code=404, detail={"error": "unknown_kind"})
    _validate_blocklist_value(kind, payload.value)
    now = datetime.now(timezone.utc)
    if kind == "ips":
        # Normalise: store canonical CIDR
        cidr = str(ipaddress.ip_network(payload.value, strict=False))
        existing = await session.get(BlocklistIP, cidr)
        if existing:
            raise HTTPException(status_code=409, detail={"error": "already_exists"})
        row = BlocklistIP(
            cidr=cidr, reason=payload.reason,
            added_by=ctx.admin.id, added_at=now, expires_at=payload.expires_at
        )
        session.add(row)
        result_value = cidr
        result_added_at = now
        result_expires_at = payload.expires_at
    elif kind == "domains":
        domain = payload.value.lower()
        existing = await session.get(BlocklistEmailDomain, domain)
        if existing:
            raise HTTPException(status_code=409, detail={"error": "already_exists"})
        row = BlocklistEmailDomain(
            domain=domain, reason=payload.reason,
            added_by=ctx.admin.id, added_at=now, expires_at=payload.expires_at
        )
        session.add(row)
        result_value = domain
        result_added_at = now
        result_expires_at = payload.expires_at
    else:  # emails
        email = payload.value.lower()
        existing = await session.get(BlocklistEmail, email)
        if existing:
            raise HTTPException(status_code=409, detail={"error": "already_exists"})
        row = BlocklistEmail(
            email=email, reason=payload.reason,
            added_by=ctx.admin.id, added_at=now, expires_at=payload.expires_at
        )
        session.add(row)
        result_value = email
        result_added_at = now
        result_expires_at = payload.expires_at
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action=f"blocklist_add_{kind}",
        target_type=kind,
        target_id=payload.value,
        ip=_client_ip(request),
        details={"reason": payload.reason},
    )
    await session.commit()
    return BlocklistEntry(value=result_value, reason=payload.reason, added_at=result_added_at, expires_at=result_expires_at)


@router.delete("/blocklist/{kind}/{value}", status_code=204)
async def admin_blocklist_delete(
    kind: str,
    value: str,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> Response:
    if kind not in _BLOCKLIST_KINDS:
        raise HTTPException(status_code=404, detail={"error": "unknown_kind"})
    if kind == "ips":
        try:
            cidr = str(ipaddress.ip_network(value, strict=False))
        except ValueError:
            cidr = value
        row = await session.get(BlocklistIP, cidr)
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        await session.delete(row)
    elif kind == "domains":
        row = await session.get(BlocklistEmailDomain, value.lower())
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        await session.delete(row)
    else:  # emails
        row = await session.get(BlocklistEmail, value.lower())
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        await session.delete(row)
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action=f"blocklist_remove_{kind}",
        target_type=kind,
        target_id=value,
        ip=_client_ip(request),
    )
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Settings + extensions
# ---------------------------------------------------------------------------

MUTABLE_SETTINGS_KEYS = {
    "max_transfer_size_gb",
    "max_ttl_days",
    "rate_hourly",
    "rate_daily",
    "rate_download_hourly",
    "geoip_enabled",
    "geoip_countries",
    "extension_blacklist",
    "max_recipients",
    "max_message_length",
    "audit_retention_days",
}


@router.get("/settings")
async def admin_get_settings(
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
) -> dict[str, Any]:
    rows = (await session.execute(select(Setting))).scalars().all()
    return {r.key: r.value for r in rows}


@router.patch("/settings")
async def admin_patch_settings(
    payload: PatchSettingsRequest,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> dict[str, Any]:
    # PatchSettingsRequest has model_config = {"extra": "forbid"}, so
    # unknown keys produce a 422 ValidationError at the Pydantic layer
    # before this handler runs. No separate set-difference check needed.
    changes = payload.to_changes()
    result: dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    for key, new_value in changes.items():
        row = await session.get(Setting, key)
        old_value = row.value if row else None
        if row is None:
            row = Setting(key=key, value=new_value, updated_at=now, updated_by=ctx.admin.id)
            session.add(row)
        else:
            row.value = new_value
            row.updated_at = now
            row.updated_by = ctx.admin.id
        await admin_actions.record(
            session,
            admin_id=ctx.admin.id,
            action="update_setting",
            target_type="setting",
            target_id=key,
            ip=_client_ip(request),
            details={"old": old_value, "new": new_value},
        )
        result[key] = new_value
    await session.commit()
    return result


@router.get("/extensions")
async def admin_get_extensions(
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
) -> list[str]:
    row = await session.get(Setting, "extension_blacklist")
    if row is None:
        return []
    v = row.value
    return v if isinstance(v, list) else []


@router.post("/extensions", status_code=201)
async def admin_add_extension(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> list[str]:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "invalid JSON body"})
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={"error": "body must be an object"})
    ext = str(payload.get("extension", "")).strip().lower()
    if not ext or not ext.startswith("."):
        raise HTTPException(status_code=400, detail={"error": "extension must start with '.'"})
    # Cap at 16 chars to prevent storing arbitrarily-large strings in the
    # JSONB `Setting.value` list (compound exts like ".tar.xz.age" still fit).
    if len(ext) > 16:
        raise HTTPException(status_code=400, detail={"error": "extension too long (max 16 chars)"})
    row = await session.get(Setting, "extension_blacklist")
    now = datetime.now(timezone.utc)
    if row is None:
        current: list[str] = []
        row = Setting(key="extension_blacklist", value=[], updated_at=now, updated_by=ctx.admin.id)
        session.add(row)
    else:
        current = row.value if isinstance(row.value, list) else []
    if ext not in current:
        new_list = current + [ext]
        row.value = new_list
        row.updated_at = now
        row.updated_by = ctx.admin.id
    else:
        new_list = current
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="add_extension",
        target_type="setting",
        target_id="extension_blacklist",
        ip=_client_ip(request),
        details={"extension": ext},
    )
    await session.commit()
    return new_list


@router.delete("/extensions/{ext}", status_code=204)
async def admin_remove_extension(
    ext: str,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> Response:
    row = await session.get(Setting, "extension_blacklist")
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    current = row.value if isinstance(row.value, list) else []
    if ext not in current:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    row.value = [e for e in current if e != ext]
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = ctx.admin.id
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="remove_extension",
        target_type="setting",
        target_id="extension_blacklist",
        ip=_client_ip(request),
        details={"extension": ext},
    )
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Audit log list + CSV export
# ---------------------------------------------------------------------------

@router.get("/audit", response_model=AuditListResponse)
async def admin_list_audit(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
    event_type: str | None = None,
    severity: str | None = None,
    ip: str | None = None,
    transfer_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> AuditListResponse:
    limit = max(1, min(limit, 500))
    stmt = select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)
    if ip:
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import INET
        stmt = stmt.where(AuditLog.ip == cast(ip, INET))
    if transfer_id:
        stmt = stmt.where(AuditLog.transfer_id == transfer_id)
    if since:
        stmt = stmt.where(AuditLog.ts >= since)
    if until:
        stmt = stmt.where(AuditLog.ts <= until)
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is not None:
            cursor_ts, cursor_id = decoded
            stmt = stmt.where(
                tuple_(AuditLog.ts, AuditLog.id)
                < tuple_(cursor_ts, cursor_id)  # type: ignore[arg-type]
            )
    stmt = stmt.limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode_cursor(rows[-1].ts, rows[-1].id) if has_more and rows else None
    )

    items = [
        AuditRow(
            id=r.id, ts=r.ts, event_type=r.event_type, severity=r.severity,
            ip=str(r.ip) if r.ip else None, country=r.country,
            transfer_id=r.transfer_id, admin_id=r.admin_id, details=r.details,
        )
        for r in rows
    ]
    return AuditListResponse(items=items, next_cursor=next_cursor)


_CSV_MAX_WINDOW_DAYS = 90


def _validate_audit_window(
    since: datetime | None, until: datetime | None
) -> tuple[datetime, datetime]:
    """Normalise + constrain the since/until range for audit CSV export.

    * both endpoints are required (prevents accidental "dump everything")
    * `until > since`
    * window must not exceed `_CSV_MAX_WINDOW_DAYS` days

    Returns the normalised (since, until) pair.
    """
    if since is None or until is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_range",
                "hint": (
                    "audit.csv export requires both `since` and `until` query "
                    f"params; max window is {_CSV_MAX_WINDOW_DAYS} days"
                ),
            },
        )
    if until <= since:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_range", "hint": "until must be > since"},
        )
    max_delta = timedelta(days=_CSV_MAX_WINDOW_DAYS)
    if until - since > max_delta:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "window_too_large",
                "hint": f"max window is {_CSV_MAX_WINDOW_DAYS} days",
            },
        )
    return since, until


@router.get("/audit.csv")
async def admin_audit_csv(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
    event_type: str | None = None,
    severity: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Any:
    """Stream the audit log as CSV for a bounded date window.

    The previous implementation materialised the entire filtered table into
    RAM before yielding the first byte — that is an OOM risk at 10M+ rows.
    This version streams via `session.stream_scalars` and enforces a hard
    90-day window ceiling so a single export can't drag the database into
    an unbounded sequential scan either.
    """
    from hawkapi.responses import StreamingResponse as SR

    # HawkAPI query params arrive as plain strings; coerce datetime-typed
    # ones here (FastAPI did this automatically via pydantic).
    if isinstance(since, str):
        since = datetime.fromisoformat(since)
    if isinstance(until, str):
        until = datetime.fromisoformat(until)

    since, until = _validate_audit_window(since, until)

    # Record that admin exported audit CSV
    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="export_audit_csv",
        ip=_client_ip(request),
        details={
            "since": since.isoformat(),
            "until": until.isoformat(),
            "event_type": event_type,
            "severity": severity,
        },
    )
    await session.commit()

    stmt = (
        select(AuditLog)
        .where(AuditLog.ts >= since)
        .where(AuditLog.ts <= until)
        .order_by(AuditLog.ts.desc(), AuditLog.id.desc())
    )
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)

    async def _generate() -> Any:
        # HawkAPI's StreamingResponse ASGI transport requires bytes chunks.
        yield b"id,ts,event_type,severity,ip,country,transfer_id,admin_id\n"
        # stream_scalars yields rows one-by-one without materialising the
        # full result set — constant memory regardless of row count.
        async for r in await session.stream_scalars(stmt):
            yield (
                f"{r.id},{r.ts.isoformat()},{r.event_type},{r.severity},"
                f"{r.ip or ''},{r.country or ''},{r.transfer_id or ''},"
                f"{r.admin_id or ''}\n"
            ).encode("utf-8")

    return SR(
        _generate(),
        content_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )


# ---------------------------------------------------------------------------
# Admin-actions list
# ---------------------------------------------------------------------------

@router.get("/admin-actions", response_model=AdminActionListResponse)
async def admin_list_actions(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
    admin_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> AdminActionListResponse:
    limit = max(1, min(limit, 500))
    stmt = select(AdminAction).order_by(AdminAction.ts.desc(), AdminAction.id.desc())
    if admin_id:
        stmt = stmt.where(AdminAction.admin_id == admin_id)
    if since:
        stmt = stmt.where(AdminAction.ts >= since)
    if until:
        stmt = stmt.where(AdminAction.ts <= until)
    if cursor:
        try:
            cursor_ts = datetime.fromisoformat(cursor)
            stmt = stmt.where(AdminAction.ts < cursor_ts)
        except ValueError:
            pass
    stmt = stmt.limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].ts.isoformat() if has_more and rows else None

    items = [
        AdminActionRow(
            id=r.id, ts=r.ts, admin_id=r.admin_id, action=r.action,
            target_type=r.target_type, target_id=r.target_id,
            ip=str(r.ip) if r.ip else None, details=r.details,
        )
        for r in rows
    ]
    return AdminActionListResponse(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def admin_analytics(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
    days: int = 30,
) -> Any:
    from app.services.analytics import AnalyticsService
    svc = AnalyticsService(_get_redis())
    return await svc.get(session, days=days)


# ---------------------------------------------------------------------------
# Admins CRUD
# ---------------------------------------------------------------------------

def _active_admin_count_stmt():
    return select(func.count(Admin.id)).where(
        Admin.disabled.is_(False), Admin.role == "admin"
    )


@router.get("/admins", response_model=list[AdminRow])
async def admin_list_admins(
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
) -> list[AdminRow]:
    rows = (await session.execute(
        select(Admin).order_by(Admin.created_at.asc())
    )).scalars().all()
    return [
        AdminRow(
            id=a.id,
            email=a.email,
            role=a.role,
            disabled=a.disabled,
            totp_enrolled=a.totp_enrolled,
            last_login_at=a.last_login_at,
            created_at=a.created_at,
            failed_attempts=a.failed_attempts,
            locked_until=a.locked_until,
        )
        for a in rows
    ]


@router.post("/admins", response_model=AdminCreateResponse, status_code=201)
async def admin_create_admin(
    payload: AdminCreateRequest,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> AdminCreateResponse:
    # Check duplicate
    existing = (await session.execute(
        select(Admin).where(Admin.email == payload.email)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, detail={"error": "duplicate_email"})

    master = get_master_key()

    secret = _auth.generate_totp_secret()
    wrapped = wrap_totp_secret(master, secret)

    a = Admin(
        email=str(payload.email),
        password_hash=_auth.hash_password(payload.password),
        totp_secret=wrapped,
        totp_enrolled=True,
        role=payload.role,
        disabled=False,
    )
    session.add(a)
    await session.flush()

    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="create_admin",
        target_type="admin",
        target_id=str(a.id),
        ip=_client_ip(request),
        details={"email": str(payload.email), "role": payload.role},
    )
    await session.commit()

    uri = _auth.build_totp_uri(secret, email=a.email, issuer="Fylix")
    return AdminCreateResponse(
        admin=AdminRow(
            id=a.id, email=a.email, role=a.role, disabled=a.disabled,
            totp_enrolled=a.totp_enrolled, last_login_at=a.last_login_at,
            created_at=a.created_at, failed_attempts=a.failed_attempts,
            locked_until=a.locked_until,
        ),
        totp_uri=uri,
    )


@router.patch("/admins/{admin_id:uuid}", response_model=AdminRow)
async def admin_update_admin(
    admin_id: UUID,
    payload: AdminUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> AdminRow:
    a = await session.get(Admin, admin_id)
    if a is None:
        raise HTTPException(404, detail={"error": "not_found"})

    changes: dict = {}
    # If we're about to disable or demote the last active admin, block.
    would_reduce_active = (
        payload.disabled is True
        or (payload.role == "viewer" and a.role == "admin")
    )
    if would_reduce_active and not a.disabled and a.role == "admin":
        count = (await session.execute(_active_admin_count_stmt())).scalar_one()
        if count <= 1:
            raise HTTPException(409, detail={"error": "min_admins"})

    if payload.role is not None and payload.role != a.role:
        changes["role"] = {"old": a.role, "new": payload.role}
        a.role = payload.role
    if payload.disabled is not None and payload.disabled != a.disabled:
        changes["disabled"] = {"old": a.disabled, "new": payload.disabled}
        a.disabled = payload.disabled

    if changes:
        await admin_actions.record(
            session,
            admin_id=ctx.admin.id,
            action="update_admin",
            target_type="admin",
            target_id=str(admin_id),
            ip=_client_ip(request),
            details=changes,
        )
    await session.commit()

    return AdminRow(
        id=a.id, email=a.email, role=a.role, disabled=a.disabled,
        totp_enrolled=a.totp_enrolled, last_login_at=a.last_login_at,
        created_at=a.created_at, failed_attempts=a.failed_attempts,
        locked_until=a.locked_until,
    )


@router.post("/admins/{admin_id:uuid}/reset-totp", response_model=ResetTotpResponse)
async def admin_reset_totp(
    admin_id: UUID,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> ResetTotpResponse:
    a = await session.get(Admin, admin_id)
    if a is None:
        raise HTTPException(404, detail={"error": "not_found"})

    master = get_master_key()

    secret = _auth.generate_totp_secret()
    a.totp_secret = wrap_totp_secret(master, secret)
    a.totp_enrolled = True

    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="reset_totp",
        target_type="admin",
        target_id=str(admin_id),
        ip=_client_ip(request),
    )
    await session.commit()

    return ResetTotpResponse(
        totp_uri=_auth.build_totp_uri(secret, email=a.email, issuer="Fylix")
    )


@router.delete("/admins/{admin_id:uuid}", status_code=204)
async def admin_delete_admin(
    admin_id: UUID,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> Response:
    a = await session.get(Admin, admin_id)
    if a is None:
        raise HTTPException(404, detail={"error": "not_found"})

    # Prevent delete if it would leave < 1 active admin
    count = (await session.execute(_active_admin_count_stmt())).scalar_one()
    is_active_admin = not a.disabled and a.role == "admin"
    if is_active_admin and count <= 1:
        raise HTTPException(409, detail={"error": "min_admins"})

    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="delete_admin",
        target_type="admin",
        target_id=str(admin_id),
        ip=_client_ip(request),
        details={"email": a.email},
    )

    await session.delete(a)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Telegram config
# ---------------------------------------------------------------------------

_TELEGRAM_KEYS = [
    "telegram_bot_token",
    "telegram_chat_id",
    "telegram_alert_on_infected",
    "telegram_alert_on_rate_limit_spike",
    "telegram_alert_on_admin_login_fail_spike",
    "telegram_alert_on_storage_high",
    "telegram_alert_on_defender_event",
    "telegram_rate_limit_spike_threshold",
]


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@router.get("/telegram", response_model=TelegramConfig)
async def admin_get_telegram(
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_session),
) -> TelegramConfig:
    # bot_token stored in settings key 'telegram_bot_token' (plaintext in Phase 6 dev)
    # Single SELECT for all 8 keys instead of 8 sequential round-trips.
    values = await _settings_service.get_many(session, _TELEGRAM_KEYS)
    return TelegramConfig(
        bot_token_is_set=bool(values.get("telegram_bot_token")),
        chat_id=str(values.get("telegram_chat_id") or ""),
        alert_on_infected=_as_bool(values.get("telegram_alert_on_infected"), True),
        alert_on_rate_limit_spike=_as_bool(values.get("telegram_alert_on_rate_limit_spike"), True),
        alert_on_admin_login_fail_spike=_as_bool(values.get("telegram_alert_on_admin_login_fail_spike"), True),
        alert_on_storage_high=_as_bool(values.get("telegram_alert_on_storage_high"), True),
        alert_on_defender_event=_as_bool(values.get("telegram_alert_on_defender_event"), True),
        rate_limit_spike_threshold=_as_int(values.get("telegram_rate_limit_spike_threshold"), 20),
    )


@router.patch("/telegram", response_model=TelegramConfig)
async def admin_update_telegram(
    payload: TelegramConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> TelegramConfig:
    import base64 as _base64
    import json as _json  # noqa: F401 — kept for audit-details serialisation downstream

    from app.services.auth import wrap_telegram_token

    def _wrap_for_storage(token: str) -> dict[str, str] | str:
        """Empty = disabled (store as empty string). Non-empty = AES-KW wrap
        + base64, stored as `{"wrapped": "<base64>"}` so a DB dump exposes
        only ciphertext."""
        if not token:
            return ""
        wrapped = wrap_telegram_token(get_master_key(), token)
        return {"wrapped": _base64.b64encode(wrapped).decode("ascii")}

    changes: dict = {}
    fields = {
        "telegram_bot_token": (
            _wrap_for_storage(payload.bot_token) if payload.bot_token is not None else None
        ),
        "telegram_chat_id": payload.chat_id,
        "telegram_alert_on_infected": payload.alert_on_infected,
        "telegram_alert_on_rate_limit_spike": payload.alert_on_rate_limit_spike,
        "telegram_alert_on_admin_login_fail_spike": payload.alert_on_admin_login_fail_spike,
        "telegram_alert_on_storage_high": payload.alert_on_storage_high,
        "telegram_alert_on_defender_event": payload.alert_on_defender_event,
        "telegram_rate_limit_spike_threshold": payload.rate_limit_spike_threshold,
    }
    for key, value in fields.items():
        if value is None:
            continue
        row = await session.get(Setting, key)
        old = row.value if row else None
        if old == value:
            continue
        if row is None:
            session.add(Setting(key=key, value=value, updated_by=ctx.admin.id))
        else:
            row.value = value
            row.updated_by = ctx.admin.id
        # Don't record the literal token in audit — just flag "was changed".
        if key == "telegram_bot_token":
            changes[key] = {"old": "***" if old else None, "new": "***" if value else ""}
        else:
            changes[key] = {"old": old, "new": value}

    if changes:
        await admin_actions.record(
            session,
            admin_id=ctx.admin.id,
            action="update_telegram_config",
            target_type="settings",
            ip=_client_ip(request),
            details=changes,
        )
    await session.commit()

    return await admin_get_telegram(session=session, ctx=ctx)


# ---------------------------------------------------------------------------
# Crypto rotation — admin-triggered rewrap (zero-downtime chunk 4c)
# ---------------------------------------------------------------------------

_REWRAP_CHUNK = 1000


@router.post("/crypto/rewrap")
async def admin_crypto_rewrap(
    request: Request,
    session: AsyncSession = Depends(_session),
    ctx: _AdminCtx = Depends(require_admin_role),
) -> dict[str, Any]:
    """Rewrap all `transfers.wrapped_key` and `admins.totp_secret` rows from
    the previous master key to the current master key.

    Preconditions (enforced by 409):
      - A rotation window is active (`MASTER_KEY_PREVIOUS_PATH` set, so
        `get_previous_master_key()` returns non-None).
      - Current and previous keys differ.

    The operation is idempotent: re-running after a partial crash (or just
    because) is safe — AES-KW RFC 3394 is deterministic, so rewrapping a
    blob already under the current key returns the identical bytes. Rows
    commit in chunks of _REWRAP_CHUNK so a crash mid-run leaves the DB in
    a partially-migrated state that the next run completes.
    """
    from app.crypto import unwrap_key, wrap_key
    from app.services.auth import (
        is_wrapped_totp,
        unwrap_totp_secret,
        wrap_totp_secret,
    )

    current = get_master_key()
    previous = get_previous_master_key()
    if previous is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "no_rotation_in_progress",
                "hint": (
                    "Set MASTER_KEY_PREVIOUS_PATH alongside MASTER_KEY_PATH "
                    "and restart api+worker to begin a rotation window."
                ),
            },
        )
    if current == previous:
        raise HTTPException(
            status_code=409,
            detail={"error": "keys_identical"},
        )

    # Transfers: chunked, keyset-paged by id.
    transfers_rewrapped = 0
    last_id: UUID | None = None
    while True:
        stmt = (
            select(Transfer)
            .where(Transfer.wrapped_key.is_not(None))
            .order_by(Transfer.id)
            .limit(_REWRAP_CHUNK)
        )
        if last_id is not None:
            stmt = stmt.where(Transfer.id > last_id)
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            break
        for t in rows:
            if t.wrapped_key is None:
                # Matches WHERE filter but narrows for mypy. Defensive.
                continue
            file_key = unwrap_key(current, t.wrapped_key, previous_master_key=previous)
            t.wrapped_key = wrap_key(current, file_key)
            transfers_rewrapped += 1
            last_id = t.id
        await session.commit()

    # Admin TOTP secrets: small set, no chunking needed.
    admins_rewrapped = 0
    admin_rows = (
        await session.execute(select(Admin).where(Admin.totp_secret.is_not(None)))
    ).scalars().all()
    for a in admin_rows:
        secret = a.totp_secret
        if secret is None or not is_wrapped_totp(secret):
            # Legacy plaintext or null — wrap_totp_secrets.py should have
            # handled plaintext migration before rotation.
            continue
        plain = unwrap_totp_secret(current, secret, previous_master_key=previous)
        a.totp_secret = wrap_totp_secret(current, plain)
        admins_rewrapped += 1
    if admins_rewrapped:
        await session.commit()

    await admin_actions.record(
        session,
        admin_id=ctx.admin.id,
        action="crypto_rewrap",
        target_type="system",
        target_id="master_key",
        ip=_client_ip(request),
        details={
            "transfers_rewrapped": transfers_rewrapped,
            "admins_rewrapped": admins_rewrapped,
        },
    )
    await session.commit()

    log.info(
        "admin_crypto_rewrap: done transfers=%d admins=%d",
        transfers_rewrapped,
        admins_rewrapped,
    )
    return {
        "ok": True,
        "transfers_rewrapped": transfers_rewrapped,
        "admins_rewrapped": admins_rewrapped,
    }
