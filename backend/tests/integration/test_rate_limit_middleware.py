"""POST /api/transfers rate-limit at 10/hour (default) — 11th request is 429."""

import os
from uuid import uuid4

import httpx
import pyotp
import pytest

from app.db import SessionLocal
from app.models import Admin
from app.services.auth import AuthService

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _flush_rl_keys() -> None:
    from redis.asyncio import Redis

    from app.config import settings

    r = Redis.from_url(settings.redis_url, decode_responses=False)
    # Clear any existing rl:* keys
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="rl:*", count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break
    await r.aclose()


def _minimal_payload() -> dict:
    return {
        "sender_email": "rl@test.co",
        "recipient_emails": ["r@test.co"],
        "ttl_days": 1,
        "files": [{"filename": "x.txt", "size": 1}],
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_11th_upload_returns_429() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        # 10 allowed
        for i in range(10):
            r = await c.post("/api/transfers", json=_minimal_payload())
            assert r.status_code == 201, f"request {i}: {r.status_code} {r.text[:200]}"
        # 11th blocked
        r = await c.post("/api/transfers", json=_minimal_payload())
        assert r.status_code == 429
        assert "retry-after" in {k.lower() for k in r.headers}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limit_does_not_apply_to_healthz() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        for _ in range(50):
            r = await c.get("/healthz")
            assert r.status_code == 200


async def _seed_admin_for_rl() -> tuple[str, str]:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    email = f"rl_admin_{uuid4().hex[:6]}@test.co"
    async with SessionLocal() as s:
        s.add(
            Admin(
                email=email,
                password_hash=auth.hash_password("StrongPw123!"),
                totp_secret=secret.encode("utf-8"),
                totp_enrolled=True,
                role="admin",
                disabled=False,
            )
        )
        await s.commit()
    return email, secret


async def _admin_login(c: httpx.AsyncClient, email: str, secret: str) -> str:
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
async def test_rate_limit_updated_via_admin_settings() -> None:
    """Changing rate_hourly to 3 via admin API should make the 4th upload return 429.

    Requires RATE_LIMIT_CACHE_TTL=0 (set in docker-compose.yml for dev/test)
    so the middleware reads from DB on every request without caching.
    """
    email, secret = await _seed_admin_for_rl()

    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _admin_login(c, email, secret)

        try:
            # Lower the hourly upload limit to 3
            r = await c.patch(
                "/api/admin/settings",
                json={"rate_hourly": 3},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 200, r.text

            # 3 uploads should be allowed
            for i in range(3):
                r = await c.post("/api/transfers", json=_minimal_payload())
                assert r.status_code == 201, f"request {i}: {r.status_code} {r.text[:200]}"

            # 4th should be blocked
            r = await c.post("/api/transfers", json=_minimal_payload())
            assert r.status_code == 429, f"expected 429 but got {r.status_code}"
            assert "retry-after" in {k.lower() for k in r.headers}
        finally:
            # Restore rate_hourly to the default so other tests are not affected.
            await c.patch(
                "/api/admin/settings",
                json={"rate_hourly": 10},
                headers={"X-CSRF-Token": csrf},
            )
