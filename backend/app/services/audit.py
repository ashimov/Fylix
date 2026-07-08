"""Helper for writing AuditLog rows.

Keeps call sites terse and ensures severity/event_type enums are consistent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write_event(
    session: AsyncSession,
    *,
    event_type: str,
    severity: str = "info",
    ip: str | None = None,
    country: str | None = None,
    transfer_id: UUID | None = None,
    admin_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Insert an AuditLog row. Caller commits the session."""
    assert severity in ("info", "warn", "error", "critical"), severity
    session.add(
        AuditLog(
            ts=datetime.now(UTC),
            event_type=event_type,
            severity=severity,
            ip=ip,
            country=country,
            transfer_id=transfer_id,
            admin_id=admin_id,
            details=details,
        )
    )
