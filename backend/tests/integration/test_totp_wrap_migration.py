"""Verify the migration utility wraps plaintext TOTP secrets idempotently."""

from __future__ import annotations

import os
import subprocess

import httpx
import pyotp
import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Admin
from app.services.auth import AuthService, is_wrapped_totp


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_wraps_plaintext_totp() -> None:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    plain = auth.generate_totp_secret()
    async with SessionLocal() as s:
        s.add(
            Admin(
                email="legacy@test.co",
                password_hash=auth.hash_password("whatever"),
                totp_secret=plain.encode("utf-8"),  # legacy plaintext
                totp_enrolled=True,
                role="admin",
                disabled=False,
            )
        )
        await s.commit()

    # Run the migration inside the api container (we are inside the container)
    proc = subprocess.run(
        ["/opt/venv/bin/python", "scripts/wrap_totp_secrets.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Wrapped: 1" in proc.stdout

    async with SessionLocal() as s:
        admin = (await s.execute(select(Admin).where(Admin.email == "legacy@test.co"))).scalar_one()
        assert is_wrapped_totp(admin.totp_secret) is True

    # Second run is no-op
    proc = subprocess.run(
        ["/opt/venv/bin/python", "scripts/wrap_totp_secrets.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert "Wrapped: 0" in proc.stdout


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_works_after_migration_and_with_new_wrapped_admin() -> None:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    async with SessionLocal() as s:
        s.add(
            Admin(
                email="post-wrap@test.co",
                password_hash=auth.hash_password("StrongPw123!"),
                totp_secret=secret.encode("utf-8"),
                totp_enrolled=True,
                role="admin",
                disabled=False,
            )
        )
        await s.commit()

    subprocess.run(
        ["/opt/venv/bin/python", "scripts/wrap_totp_secrets.py"],
        cwd="/app",
        capture_output=True,
        timeout=30,
        check=False,
    )

    code = pyotp.TOTP(secret).now()
    BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post(
            "/api/admin/login",
            json={
                "email": "post-wrap@test.co",
                "password": "StrongPw123!",
                "totp_code": code,
            },
        )
    assert r.status_code == 200, r.text
