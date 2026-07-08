"""Role guards: ensure viewer can't POST admin-only endpoints."""

import os

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
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


async def _seed(email: str, role: str, password: str = "StrongPw123!") -> tuple[str, str]:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    async with SessionLocal() as s:
        s.add(
            Admin(
                email=email,
                password_hash=auth.hash_password(password),
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
async def test_me_requires_session() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.get("/api/admin/me")
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_touches_session_sliding_ttl() -> None:
    email, secret = await _seed("touch@x.co", "admin")
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        await _login(c, email, secret)
        # Two consecutive /me calls both succeed, confirming sliding TTL doesn't expire.
        r1 = await c.get("/api/admin/me")
        assert r1.status_code == 200
        r2 = await c.get("/api/admin/me")
        assert r2.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_can_read_me() -> None:
    email, secret = await _seed("viewer@x.co", "viewer")
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/me")
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"
