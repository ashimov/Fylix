"""Public-API DTOs for transfer creation and response."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator


class FileDescriptor(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)


class CreateTransferRequest(BaseModel):
    sender_email: EmailStr
    recipient_emails: list[EmailStr] = Field(min_length=1, max_length=20)
    message: str | None = Field(default=None, max_length=2000)
    ttl_days: int = Field(ge=1, le=7)  # admin may raise the cap later
    files: list[FileDescriptor] = Field(min_length=1, max_length=50)
    captcha_token: str | None = Field(default=None, max_length=2000)

    @field_validator("recipient_emails")
    @classmethod
    def _dedup_recipients(cls, v: list[EmailStr]) -> list[EmailStr]:
        # Preserve order and first-seen casing, drop duplicates by lowercase key.
        seen: set[str] = set()
        result: list[EmailStr] = []
        for e in v:
            key = str(e).lower()
            if key not in seen:
                seen.add(key)
                result.append(e)
        return result

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_count(self) -> int:
        return len(self.files)


class CreateTransferResponse(BaseModel):
    transfer_id: UUID
    download_token: str
    manage_token: str
    upload_urls: dict[str, str]  # {filename: tus-upload-url}
    expires_at: datetime


class FileInfo(BaseModel):
    filename: str
    size_bytes: int
    mime_type: str


class DownloadInfo(BaseModel):
    ip: str
    country: str | None = None
    ua: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    bytes_sent: int | None = None
    aborted: bool


class SenderPanelResponse(BaseModel):
    transfer_id: UUID
    status: str
    sender_email: str
    recipient_emails: list[str]
    message: str | None = None
    created_at: datetime
    expires_at: datetime
    download_token: str | None = None
    files: list[FileInfo]
    downloads: list[DownloadInfo]
