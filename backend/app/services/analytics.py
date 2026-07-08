"""Analytics aggregation service with Redis 60s cache."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import cast, func, select, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Download, Transfer, TransferFile


class AnalyticsService:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, session: AsyncSession, *, days: int = 30) -> dict[str, Any]:
        cache_key = f"analytics:{days}"
        cached = await self._redis.get(cache_key)
        if cached is not None:
            return json.loads(cached)

        result = await self._compute(session, days=days)
        await self._redis.setex(cache_key, 60, json.dumps(result, default=str))
        return result

    async def _compute(self, session: AsyncSession, *, days: int) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        kpi = await self._kpi(session, today_start=today_start, week_start=week_start)
        daily = await self._daily_transfers(session, since=since)
        countries = await self._top_countries(session, since=since)
        mime = await self._top_mime(session, since=since)
        ips = await self._top_ips(session, since=since)
        domains = await self._top_sender_domains(session, since=since)
        infected = await self._infected_timeline(session, since=since)

        return {
            "kpi": kpi,
            "daily_transfers": daily,
            "top_countries": countries,
            "top_mime": mime,
            "top_ips": ips,
            "top_sender_domains": domains,
            "infected_timeline": infected,
        }

    async def _kpi(
        self, session: AsyncSession, *, today_start: datetime, week_start: datetime
    ) -> dict[str, Any]:
        # One SELECT over `transfers` with 4 conditional aggregations instead
        # of 4 separate round-trips. Postgres FILTER(WHERE ...) is spec'd for
        # this exact use case — planner can fulfil the status counts via the
        # partial index `idx_transfers_status_active` (migration 0009) and
        # fold the traffic sums into the same pass.
        active_pred = Transfer.status == "ready"
        infected_pred = Transfer.status == "infected"
        today_pred = Transfer.created_at >= today_start
        week_pred = Transfer.created_at >= week_start

        row = (
            await session.execute(
                select(
                    func.count().filter(active_pred).label("active"),
                    func.count().filter(infected_pred).label("infected"),
                    func.coalesce(
                        func.sum(Transfer.total_size).filter(today_pred), 0
                    ).label("traffic_today"),
                    func.coalesce(
                        func.sum(Transfer.total_size).filter(week_pred), 0
                    ).label("traffic_week"),
                )
            )
        ).one()

        # audit_log lives on a different table and uses different indexes —
        # keep as its own query.
        rl_blocks = (
            await session.execute(
                select(func.count())
                .where(AuditLog.event_type == "rate_limit_blocked")
                .where(AuditLog.ts >= today_start)
            )
        ).scalar_one()

        return {
            "active_transfers": row.active,
            "traffic_today_gb": round(int(row.traffic_today) / (1024 ** 3), 4),
            "traffic_week_gb": round(int(row.traffic_week) / (1024 ** 3), 4),
            "infected_count": row.infected,
            "rate_limit_blocks_today": rl_blocks,
        }

    async def _daily_transfers(
        self, session: AsyncSession, *, since: datetime
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(
                func.date_trunc("day", Transfer.created_at).label("day"),
                func.count().label("count"),
            )
            .where(Transfer.created_at >= since)
            .group_by(text("day"))
            .order_by(text("day"))
        )).all()
        return [{"date": str(r.day.date()), "count": r.count} for r in rows]

    async def _top_countries(
        self, session: AsyncSession, *, since: datetime
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(Transfer.sender_country, func.count().label("count"))
            .where(Transfer.created_at >= since)
            .group_by(Transfer.sender_country)
            .order_by(func.count().desc())
            .limit(10)
        )).all()
        return [{"country": r.sender_country, "count": r.count} for r in rows]

    async def _top_mime(
        self, session: AsyncSession, *, since: datetime
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(TransferFile.mime_type, func.count().label("count"))
            .join(Transfer, Transfer.id == TransferFile.transfer_id)
            .where(Transfer.created_at >= since)
            .group_by(TransferFile.mime_type)
            .order_by(func.count().desc())
            .limit(10)
        )).all()
        return [{"mime_type": r.mime_type, "count": r.count} for r in rows]

    async def _top_ips(
        self, session: AsyncSession, *, since: datetime
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(Transfer.sender_ip, func.count().label("count"))
            .where(Transfer.created_at >= since)
            .group_by(Transfer.sender_ip)
            .order_by(func.count().desc())
            .limit(10)
        )).all()
        return [{"ip": str(r.sender_ip), "count": r.count} for r in rows]

    async def _top_sender_domains(
        self, session: AsyncSession, *, since: datetime
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(
                func.split_part(Transfer.sender_email, "@", 2).label("domain"),
                func.count().label("count"),
            )
            .where(Transfer.created_at >= since)
            .group_by(text("domain"))
            .order_by(func.count().desc())
            .limit(10)
        )).all()
        return [{"domain": r.domain, "count": r.count} for r in rows]

    async def _infected_timeline(
        self, session: AsyncSession, *, since: datetime
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(
                func.date_trunc("day", AuditLog.ts).label("day"),
                func.count().label("count"),
            )
            .where(AuditLog.event_type == "infected")
            .where(AuditLog.ts >= since)
            .group_by(text("day"))
            .order_by(text("day"))
        )).all()
        return [{"date": str(r.day.date()), "count": r.count} for r in rows]
