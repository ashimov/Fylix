"""Admin blocklist CRUD endpoints."""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pyotp
import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Admin
from app.services.auth import AuthService

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admin_actions"))
        await s.execute(text("DELETE FROM blocklist_emails"))
        await s.execute(text("DELETE FROM blocklist_email_domains"))
        await s.execute(text("DELETE FROM blocklist_ips"))
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_ips_list_empty() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/blocklist/ips")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_add_ip() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/blocklist/ips",
            json={"value": "192.0.2.1", "reason": "test"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 201
    body = r.json()
    # ipaddress.ip_network("192.0.2.1", strict=False) -> "192.0.2.1/32"
    # but Postgres INET may store it as "192.0.2.1" — accept either
    assert "192.0.2.1" in body["value"]
    assert body["reason"] == "test"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_add_invalid_ip_returns_400() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/blocklist/ips", json={"value": "not-an-ip"}, headers={"X-CSRF-Token": csrf}
        )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_add_domain() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/blocklist/domains",
            json={"value": "spam.example.com"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 201
    assert r.json()["value"] == "spam.example.com"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_add_invalid_domain_returns_400() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/blocklist/domains",
            json={"value": "not_a_domain"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_add_email() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/blocklist/emails",
            json={"value": "bad@actor.com"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 201
    assert r.json()["value"] == "bad@actor.com"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_list_after_add() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        await c.post(
            "/api/admin/blocklist/ips", json={"value": "10.0.0.2"}, headers={"X-CSRF-Token": csrf}
        )
        r = await c.get("/api/admin/blocklist/ips")
    assert r.status_code == 200
    values = [e["value"] for e in r.json()]
    # PostgreSQL INET stores host address as-is (no /32 suffix)
    assert any("10.0.0.2" in v for v in values)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_delete_ip() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        await c.post(
            "/api/admin/blocklist/ips", json={"value": "10.0.0.3"}, headers={"X-CSRF-Token": csrf}
        )
        r = await c.delete("/api/admin/blocklist/ips/10.0.0.3", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204

    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r2 = await c.get("/api/admin/blocklist/ips")
    assert all("10.0.0.3" not in e["value"] for e in r2.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_can_read_blocklist() -> None:
    email, secret = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/blocklist/ips")
    assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_cannot_add_blocklist() -> None:
    email, secret = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/blocklist/ips", json={"value": "1.2.3.4"}, headers={"X-CSRF-Token": csrf}
        )
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_blocks_transfer_creation() -> None:
    """Adding an IP to the blocklist blocks POST /api/transfers from that IP."""
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        # Block 127.0.0.1 (the test client IP)
        r = await c.post(
            "/api/admin/blocklist/ips", json={"value": "127.0.0.1"}, headers={"X-CSRF-Token": csrf}
        )
        assert r.status_code == 201

    # Now try to create a transfer from localhost — should be blocked
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.post(
            "/api/transfers",
            json={
                "sender_email": "sender@example.com",
                "recipient_emails": ["r@example.com"],
                "files": [{"filename": "a.txt", "size": 100}],
                "ttl_days": 7,
            },
        )
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocklist_unknown_kind_returns_404() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/blocklist/phones")
    assert r.status_code == 404
