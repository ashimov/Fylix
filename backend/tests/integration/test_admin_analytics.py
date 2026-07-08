"""Admin analytics endpoint with Redis 60s cache."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pyotp
import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.models import Admin, AuditLog, Download, Transfer, TransferFile
from app.services.auth import AuthService

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admin_actions"))
        await s.execute(text("DELETE FROM downloads"))
        await s.execute(text("DELETE FROM transfer_recipients"))
        await s.execute(text("DELETE FROM transfer_files"))
        await s.execute(text("DELETE FROM transfers"))
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(text("UPDATE settings SET updated_by = NULL"))
        await s.execute(text("DELETE FROM admins"))
        await s.commit()
    # Clear analytics cache
    r = Redis.from_url(settings.redis_url, decode_responses=False)
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="analytics:*", count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break
    await r.aclose()


async def _seed_admin(role: str = "admin") -> tuple[str, str]:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    email = f"{role}_{uuid4().hex[:6]}@test.co"
    async with SessionLocal() as s:
        s.add(
            Admin(
                email=email,
                password_hash=auth.hash_password("StrongPw123!"),
                totp_secret=secret.encode("utf-8"),
                totp_enrolled=True,
                role=role,
                disabled=False,
            )
        )
        await s.commit()
    return email, secret


async def _login(c: httpx.AsyncClient, email: str, secret: str) -> str:
    code = pyotp.TOTP(secret).now()
    r = await c.post(
        "/api/admin/login",
        json={
            "email": email,
            "password": "StrongPw123!",
            "totp_code": code,
        },
    )
    assert r.status_code == 200, r.text
    return c.cookies.get("csrf") or ""


async def _seed_transfer_with_data() -> None:
    async with SessionLocal() as s:
        t = Transfer(
            token=uuid4().hex,
            manage_token=uuid4().hex,
            sender_email="sender@example.com",
            sender_ip="10.0.0.1",
            sender_country="KZ",
            status="ready",
            total_size=2 * 1024 * 1024,  # 2 MB
            file_count=1,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            wrapped_key=b"fakewrappedkey",
        )
        s.add(t)
        await s.flush()
        tid = t.id
        s.add(
            TransferFile(
                transfer_id=tid,
                filename="doc.pdf",
                safe_filename="doc.pdf",
                mime_type="application/pdf",
                size_bytes=2 * 1024 * 1024,
                object_key=f"{tid}/file.enc",
                iv=b"\x00" * 12,
                sha256_cipher=b"\x00" * 32,
            )
        )
        s.add(
            Download(
                transfer_id=tid,
                ip="10.0.0.2",
                started_at=datetime.now(UTC),
                bytes_sent=1024,
                aborted=False,
            )
        )
        s.add(
            AuditLog(
                ts=datetime.now(UTC),
                event_type="test_event",
                severity="info",
            )
        )
        await s.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_unauthenticated() -> None:
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.get("/api/admin/analytics")
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_returns_correct_shape() -> None:
    await _seed_transfer_with_data()
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/analytics")
    assert r.status_code == 200
    body = r.json()

    # Shape assertions
    assert "kpi" in body
    assert "daily_transfers" in body
    assert "top_countries" in body
    assert "top_mime" in body
    assert "top_ips" in body
    assert "top_sender_domains" in body
    assert "infected_timeline" in body

    kpi = body["kpi"]
    assert "active_transfers" in kpi
    assert "traffic_today_gb" in kpi
    assert "traffic_week_gb" in kpi
    assert "infected_count" in kpi
    assert "rate_limit_blocks_today" in kpi


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_kpi_reflects_seeded_data() -> None:
    await _seed_transfer_with_data()
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/analytics")
    assert r.status_code == 200
    kpi = r.json()["kpi"]
    assert kpi["active_transfers"] >= 1
    assert kpi["traffic_today_gb"] > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_top_mime_reflects_seeded_file() -> None:
    await _seed_transfer_with_data()
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/analytics")
    assert r.status_code == 200
    mime_types = [m["mime_type"] for m in r.json()["top_mime"]]
    assert "application/pdf" in mime_types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_cached_second_call_hits_cache() -> None:
    """Two back-to-back calls should return identical data (cache hit on second)."""
    await _seed_transfer_with_data()
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r1 = await c.get("/api/admin/analytics")
        r2 = await c.get("/api/admin/analytics")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both should return the same result (second is from cache)
    assert r1.json() == r2.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_viewer_can_read() -> None:
    email, secret = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/analytics")
    assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_days_parameter() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/analytics", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert "kpi" in body
