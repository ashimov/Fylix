"""Helper for immutable admin-action logging."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAction


async def record(
    session: AsyncSession,
    *,
    admin_id: UUID,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Insert an AdminAction row. Caller commits the session."""
    session.add(AdminAction(
        ts=datetime.now(timezone.utc),
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        details=details,
    ))
