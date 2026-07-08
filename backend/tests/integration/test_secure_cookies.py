"""Verify cookie Secure attribute respects DEV_INSECURE_COOKIES setting."""

from __future__ import annotations

import os

import httpx
import pyotp
import pytest
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.models import Admin
from app.services.auth import AuthService


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_cookie_secure_matches_config() -> None:
    """Cookie Secure attribute must be present unless DEV_INSECURE_COOKIES is set.

    In the dev compose stack, DEV_INSECURE_COOKIES=1 is set so that httpx (which
    runs over plain http://localhost:8000 inside the container) can send the cookie
    back on subsequent requests. When DEV_INSECURE_COOKIES is False (production),
    Secure is unconditionally emitted.

    This test asserts that the cookie attribute matches the live config value.
    """
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    async with SessionLocal() as s:
        s.add(
            Admin(
                email="secure-cookie@test.co",
                password_hash=auth.hash_password("StrongPw123!"),
                totp_secret=secret.encode("utf-8"),
                totp_enrolled=True,
                role="admin",
                disabled=False,
            )
        )
        await s.commit()

    code = pyotp.TOTP(secret).now()
    BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post(
            "/api/admin/login",
            json={
                "email": "secure-cookie@test.co",
                "password": "StrongPw123!",
                "totp_code": code,
            },
        )
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "")

    if settings.dev_insecure_cookies:
        # Dev mode: Secure is intentionally absent so httpx can use the cookie
        # over plain HTTP in integration tests.
        assert (
            "secure" not in set_cookie.lower()
        ), f"Expected no Secure attr in dev-insecure mode: {set_cookie}"
    else:
        # Production mode: Secure must always be present.
        assert "secure" in set_cookie.lower(), f"Secure attr missing: {set_cookie}"

    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dev_insecure_cookies_env_flag_disables_secure() -> None:
    """When DEV_INSECURE_COOKIES is set, Secure is omitted (for dev over plain HTTP)."""
    # This test is aspirational — without restarting the container with the env var,
    # we can't toggle it. Mark as skip with a note.
    pytest.skip("requires container restart with DEV_INSECURE_COOKIES=1; manual verification only")
