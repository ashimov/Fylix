"""Blocklist lookup — IP (CIDR), email-domain, email-exact.

Uses Postgres `<<=` operator for CIDR containment. Domain and email lookups
are against citext columns so they're naturally case-insensitive.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BlocklistEmail, BlocklistEmailDomain, BlocklistIP


def _not_expired(model):
    now = datetime.now(timezone.utc)
    return or_(model.expires_at.is_(None), model.expires_at > now)


class BlocklistChecker:
    async def check_ip(self, session: AsyncSession, ip: str) -> bool:
        """True if `ip` is contained in any non-expired CIDR block."""
        # `inet <<= cidr` = "ip is inside network (or equal)"
        # asyncpg uses $N positional params; we can't use :name::inet syntax.
        # Use cast() + a custom_op to build: CAST(:ip AS inet) <<= cidr
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import INET

        ip_cast = cast(ip, INET)
        result = await session.execute(
            select(BlocklistIP.cidr)
            .where(
                ip_cast.op("<<=")(BlocklistIP.cidr),
                _not_expired(BlocklistIP),
            )
        )
        return result.first() is not None

    async def check_email_domain(self, session: AsyncSession, email: str) -> bool:
        if "@" not in email:
            return False
        domain = email.rsplit("@", 1)[1]
        if not domain:
            return False
        result = await session.execute(
            select(BlocklistEmailDomain.domain).where(
                BlocklistEmailDomain.domain == domain,
                _not_expired(BlocklistEmailDomain),
            )
        )
        return result.first() is not None

    async def check_email(self, session: AsyncSession, email: str) -> bool:
        result = await session.execute(
            select(BlocklistEmail.email).where(
                BlocklistEmail.email == email,
                _not_expired(BlocklistEmail),
            )
        )
        return result.first() is not None
