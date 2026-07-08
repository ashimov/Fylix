"""Integration tests for BlocklistChecker against real PostgreSQL."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import BlocklistEmail, BlocklistEmailDomain, BlocklistIP
from app.services.blocklist import BlocklistChecker


@pytest.fixture(autouse=True)
async def _clean() -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE blocklist_ips, blocklist_email_domains, blocklist_emails RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_ip_matches_exact() -> None:
    async with SessionLocal() as session:
        session.add(BlocklistIP(cidr="1.2.3.4/32", reason="test"))
        await session.commit()

    c = BlocklistChecker()
    async with SessionLocal() as session:
        assert await c.check_ip(session, "1.2.3.4") is True
        assert await c.check_ip(session, "1.2.3.5") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_ip_matches_cidr_block() -> None:
    async with SessionLocal() as session:
        session.add(BlocklistIP(cidr="10.0.0.0/8", reason="internal range"))
        await session.commit()

    c = BlocklistChecker()
    async with SessionLocal() as session:
        assert await c.check_ip(session, "10.1.2.3") is True
        assert await c.check_ip(session, "10.99.99.99") is True
        assert await c.check_ip(session, "11.0.0.1") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_ip_respects_expiry() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    async with SessionLocal() as session:
        session.add(BlocklistIP(cidr="5.5.5.5/32", reason="old", expires_at=past))
        await session.commit()

    c = BlocklistChecker()
    async with SessionLocal() as session:
        # Expired entry should not match.
        assert await c.check_ip(session, "5.5.5.5") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_email_domain_case_insensitive() -> None:
    async with SessionLocal() as session:
        session.add(BlocklistEmailDomain(domain="badcorp.com"))
        await session.commit()

    c = BlocklistChecker()
    async with SessionLocal() as session:
        assert await c.check_email_domain(session, "user@BadCorp.com") is True
        assert await c.check_email_domain(session, "user@other.com") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_email_exact_match() -> None:
    async with SessionLocal() as session:
        session.add(BlocklistEmail(email="Evil@User.net"))
        await session.commit()

    c = BlocklistChecker()
    async with SessionLocal() as session:
        # citext column — case-insensitive exact match.
        assert await c.check_email(session, "evil@user.net") is True
        assert await c.check_email(session, "someone@user.net") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_email_handles_missing_at_sign() -> None:
    c = BlocklistChecker()
    async with SessionLocal() as session:
        # Malformed input shouldn't crash; domain extraction returns empty → no match.
        assert await c.check_email_domain(session, "not-an-email") is False
