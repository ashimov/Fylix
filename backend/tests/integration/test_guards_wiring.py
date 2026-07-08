"""Integration tests that each of the 3 guard surfaces works end-to-end
against the running stack."""

import os

import httpx
import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import (
    AuditLog,
    BlocklistEmail,
    BlocklistEmailDomain,
    BlocklistIP,
)

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, "
                "downloads, audit_log, blocklist_ips, blocklist_emails, "
                "blocklist_email_domains RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


def _payload(**overrides) -> dict:
    body = {
        "sender_email": "good@example.com",
        "recipient_emails": ["rcpt@x.co"],
        "ttl_days": 1,
        "files": [{"filename": "doc.pdf", "size": 1024}],
    }
    body.update(overrides)
    return body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocked_ip_returns_403_and_audits() -> None:
    # Block 127.0.0.1 (the test client's IP on host → api container)
    async with SessionLocal() as session:
        session.add(BlocklistIP(cidr="127.0.0.0/8", reason="test"))
        await session.commit()

    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/transfers", json=_payload())
    assert r.status_code == 403
    assert r.json() == {"detail": {"error": "blocked"}}

    async with SessionLocal() as session:
        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.event_type == "blocklist_hit")))
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].severity == "warn"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocked_email_returns_403() -> None:
    async with SessionLocal() as session:
        session.add(BlocklistEmail(email="Evil@x.co", reason="test"))
        await session.commit()

    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/transfers", json=_payload(sender_email="evil@x.co"))
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocked_email_domain_returns_403() -> None:
    async with SessionLocal() as session:
        session.add(BlocklistEmailDomain(domain="spam.ru", reason="test"))
        await session.commit()

    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/transfers", json=_payload(sender_email="user@spam.ru"))
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extension_blacklist_returns_422() -> None:
    # seed already puts .exe in extension_blacklist
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post(
            "/api/transfers",
            json=_payload(
                files=[{"filename": "virus.EXE", "size": 1024}],
            ),
        )
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["error"] == "policy_violation"
    assert ".exe" in body["detail"]["reason"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversized_transfer_returns_413() -> None:
    gb = 1024 * 1024 * 1024
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post(
            "/api/transfers",
            json=_payload(
                files=[{"filename": "huge.bin", "size": 3 * gb}],
            ),
        )
    assert r.status_code == 413


@pytest.mark.integration
@pytest.mark.asyncio
async def test_too_many_recipients_returns_422() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post(
            "/api/transfers",
            json=_payload(
                recipient_emails=[f"u{i}@x.co" for i in range(21)],
            ),
        )
    # Pydantic rejects >20 at the schema layer BEFORE the policy check (recipients field has max_length=20).
    # So we get 422 from Pydantic validation, not from policy.
    assert r.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_happy_path_still_works() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/transfers", json=_payload())
    assert r.status_code == 201
    body = r.json()
    assert "transfer_id" in body
    assert "download_token" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_geoip_disabled_by_default_lets_through() -> None:
    # The seeded value of geoip_enabled is False. Any country should pass.
    # (And in dev we don't have a real mmdb so geoip.enabled is False anyway,
    # which fails open.)
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/transfers", json=_payload())
    assert r.status_code == 201
