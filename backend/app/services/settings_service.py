"""Read/write key-value settings from the `settings` table.

Phase 4 version: no caching — keep simple. Phase 5 admin UI will add Redis
cache with short TTL + pub/sub invalidation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting


class SettingsService:
    async def get(self, session: AsyncSession, key: str, default: Any = None) -> Any:
        row = (
            await session.execute(select(Setting.value).where(Setting.key == key))
        ).scalar_one_or_none()
        return row if row is not None else default

    async def get_many(self, session: AsyncSession, keys: list[str]) -> dict[str, Any]:
        """Return a dict mapping each requested key to its stored value.

        One SQL round-trip regardless of len(keys). Missing keys are simply
        absent from the returned dict — callers apply per-key defaults via
        `result.get(key, default)`.
        """
        if not keys:
            return {}
        rows = (
            await session.execute(select(Setting.key, Setting.value).where(Setting.key.in_(keys)))
        ).all()
        return {row.key: row.value for row in rows}

    async def get_int(self, session: AsyncSession, key: str, default: int) -> int:
        v = await self.get(session, key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    async def get_bool(self, session: AsyncSession, key: str, default: bool) -> bool:
        v = await self.get(session, key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return default

    async def get_list(self, session: AsyncSession, key: str, default: list[Any]) -> list[Any]:
        v = await self.get(session, key, default)
        return v if isinstance(v, list) else default
