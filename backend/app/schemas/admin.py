from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Settings: typed partial-update DTO
# ---------------------------------------------------------------------------

class PatchSettingsRequest(BaseModel):
    """Typed body for PATCH /api/admin/settings.

    All fields are optional (partial update). `extra="forbid"` rejects unknown
    keys at the Pydantic layer, replacing the previous runtime set-difference
    check and ensuring each submitted value is type-checked and range-checked
    before it reaches the DB / rate limiter.
    """

    model_config = ConfigDict(extra="forbid")

    # Upload / transfer limits
    max_transfer_size_gb: int | None = Field(default=None, ge=1, le=100)
    max_ttl_days: int | None = Field(default=None, ge=1, le=90)
    max_recipients: int | None = Field(default=None, ge=1, le=100)
    max_message_length: int | None = Field(default=None, ge=0, le=10_000)

    # Rate limits (per IP)
    rate_hourly: int | None = Field(default=None, ge=1)
    rate_daily: int | None = Field(default=None, ge=1)
    rate_download_hourly: int | None = Field(default=None, ge=1)

    # GeoIP gate
    geoip_enabled: bool | None = None
    geoip_countries: list[str] | None = None

    # Extension blacklist (e.g. ["exe", "bat", "scr"])
    extension_blacklist: list[str] | None = None

    # Audit log retention
    audit_retention_days: int | None = Field(default=None, ge=30, le=3650)

    def to_changes(self) -> dict[str, Any]:
        """Return a dict containing only the fields the client actually sent.

        `model_dump(exclude_unset=True)` preserves partial-update semantics:
        fields the client omitted stay at their current DB value; fields
        explicitly set to None are NOT included (the None sentinel here
        means "field not sent", not "clear the setting").
        """
        return self.model_dump(exclude_unset=True)


# ---------------------------------------------------------------------------
# Admins CRUD schemas
# ---------------------------------------------------------------------------

class AdminRow(BaseModel):
    id: UUID
    email: str
    role: str
    disabled: bool
    totp_enrolled: bool
    last_login_at: datetime | None
    created_at: datetime
    failed_attempts: int
    locked_until: datetime | None


class AdminCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(pattern=r"^(admin|viewer)$")


class AdminCreateResponse(BaseModel):
    admin: AdminRow
    totp_uri: str  # otpauth:// URL for QR code display (shown once)


class AdminUpdateRequest(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|viewer)$")
    disabled: bool | None = None


class ResetTotpResponse(BaseModel):
    totp_uri: str  # new otpauth:// URL (shown once)


# ---------------------------------------------------------------------------
# Telegram config schemas
# ---------------------------------------------------------------------------

class TelegramConfig(BaseModel):
    bot_token_is_set: bool
    chat_id: str
    alert_on_infected: bool
    alert_on_rate_limit_spike: bool
    alert_on_admin_login_fail_spike: bool
    alert_on_storage_high: bool
    alert_on_defender_event: bool
    rate_limit_spike_threshold: int = Field(ge=1, le=1000)


class TelegramConfigUpdate(BaseModel):
    bot_token: str | None = Field(default=None, max_length=256)
    chat_id: str | None = Field(default=None, max_length=64)
    alert_on_infected: bool | None = None
    alert_on_rate_limit_spike: bool | None = None
    alert_on_admin_login_fail_spike: bool | None = None
    alert_on_storage_high: bool | None = None
    alert_on_defender_event: bool | None = None
    rate_limit_spike_threshold: int | None = Field(default=None, ge=1, le=1000)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    totp_code: str = Field(min_length=6, max_length=8)


class AdminPublic(BaseModel):
    id: UUID
    email: str
    role: str
    disabled: bool
    totp_enrolled: bool
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    admin: AdminPublic


# ---------------------------------------------------------------------------
# Transfer schemas
# ---------------------------------------------------------------------------

class TransferRow(BaseModel):
    id: UUID
    sender_email: str
    sender_ip: str
    sender_country: str | None
    total_size: int
    file_count: int
    status: str
    created_at: datetime
    expires_at: datetime


class TransferListResponse(BaseModel):
    items: list[TransferRow]
    next_cursor: str | None  # ISO timestamp of the oldest item + id


class FileDetail(BaseModel):
    id: UUID
    filename: str
    size_bytes: int
    mime_type: str


class RecipientDetail(BaseModel):
    email: str
    email_sent_at: datetime | None
    email_status: str | None


class DownloadDetail(BaseModel):
    ip: str
    country: str | None
    ua: str | None
    started_at: datetime
    completed_at: datetime | None
    bytes_sent: int | None
    aborted: bool


class TransferDetailResponse(BaseModel):
    id: UUID
    sender_email: str
    sender_ip: str
    sender_country: str | None
    sender_city: str | None
    message: str | None
    status: str
    total_size: int
    file_count: int
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    deleted_at: datetime | None
    infected_at: datetime | None
    files: list[FileDetail]
    recipients: list[RecipientDetail]
    downloads: list[DownloadDetail]


# ---------------------------------------------------------------------------
# Blocklist schemas
# ---------------------------------------------------------------------------

class BlocklistEntry(BaseModel):
    value: str
    reason: str | None
    added_at: datetime
    expires_at: datetime | None


class BlocklistAddRequest(BaseModel):
    value: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Audit / admin-actions schemas
# ---------------------------------------------------------------------------

class AuditRow(BaseModel):
    id: int
    ts: datetime
    event_type: str
    severity: str
    ip: str | None
    country: str | None
    transfer_id: UUID | None
    admin_id: UUID | None
    details: dict | None


class AuditListResponse(BaseModel):
    items: list[AuditRow]
    next_cursor: str | None


class AdminActionRow(BaseModel):
    id: int
    ts: datetime
    admin_id: UUID
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    details: dict | None


class AdminActionListResponse(BaseModel):
    items: list[AdminActionRow]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Analytics schemas
# ---------------------------------------------------------------------------

class KPI(BaseModel):
    active_transfers: int
    traffic_today_gb: float
    traffic_week_gb: float
    infected_count: int
    rate_limit_blocks_today: int


class DailyCount(BaseModel):
    date: str
    count: int


class CountryCount(BaseModel):
    country: str | None
    count: int


class MimeCount(BaseModel):
    mime_type: str
    count: int


class IPCount(BaseModel):
    ip: str
    count: int


class DomainCount(BaseModel):
    domain: str
    count: int


class AnalyticsResponse(BaseModel):
    kpi: KPI
    daily_transfers: list[DailyCount]
    top_countries: list[CountryCount]
    top_mime: list[MimeCount]
    top_ips: list[IPCount]
    top_sender_domains: list[DomainCount]
    infected_timeline: list[DailyCount]
