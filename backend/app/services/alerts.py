"""Alert dispatcher — routes (event, severity, details) to Telegram + audit_log."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit import write_event
from app.services.telegram import TelegramClient

log = logging.getLogger(__name__)

_TG_SEVERITIES = frozenset({"error", "critical"})


class AlertDispatcher:
    """Dispatches an event to both audit_log and (for high-severity) Telegram."""

    def __init__(self, telegram: TelegramClient) -> None:
        self.telegram = telegram

    async def alert(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        severity: str,
        message: str,
        ip: str | None = None,
        transfer_id: UUID | None = None,
        details: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> None:
        await write_event(
            session,
            event_type=event_type,
            severity=severity,
            ip=ip,
            transfer_id=transfer_id,
            details=details,
        )
        if commit:
            await session.commit()

        if severity in _TG_SEVERITIES and self.telegram.enabled:
            tg_text = self._format(event_type, severity, message, details)
            try:
                await self.telegram.send(tg_text)
            except Exception:
                log.exception("alerts: telegram send failed (non-fatal)")

    @staticmethod
    def _format(
        event_type: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None,
    ) -> str:
        icon = "\U0001f6a8" if severity == "critical" else "\u26a0\ufe0f"
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"{icon} *{event_type}* — `{severity}`",
            f"_{ts}_",
            "",
            message,
        ]
        if details:
            lines.append("")
            for k, v in details.items():
                lines.append(f"• `{k}`: `{v}`")
        return "\n".join(lines)
