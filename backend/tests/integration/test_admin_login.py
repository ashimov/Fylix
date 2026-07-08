"""Admin login/logout/me via HTTP against running stack."""
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


async def _seed_admin(
    *,
    email: str = "admin@test.co",
    password: str = "StrongPw123!",
    enrolled: bool = True,
    disabled: bool = False,
    role: str = "admin",
) -> tuple[str, str]:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    async with SessionLocal() as s:
        s.add(Admin(
            email=email,
            password_hash=auth.hash_password(password),
            totp_secret=secret.encode("utf-8") if enrolled else None,
            totp_enrolled=enrolled,
            role=role,
            disabled=disabled,
        ))
        await s.commit()
    return email, secret


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_happy_path_sets_session_cookie() -> None:
    email, secret = await _seed_admin()
    code = pyotp.TOTP(secret).now()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": code,
        })
    assert r.status_code == 200
    body = r.json()
    assert body["admin"]["email"] == email
    assert "session_id" in r.cookies


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_wrong_password_returns_401() -> None:
    email, secret = await _seed_admin()
    code = pyotp.TOTP(secret).now()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/admin/login", json={
            "email": email, "password": "wrong", "totp_code": code,
        })
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_wrong_totp_returns_401() -> None:
    email, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": "000000",
        })
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_unknown_user_returns_401() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/admin/login", json={
            "email": "nobody@nowhere.co",
            "password": "whatever",
            "totp_code": "123456",
        })
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_disabled_admin_returns_403() -> None:
    email, secret = await _seed_admin(disabled=True)
    code = pyotp.TOTP(secret).now()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": code,
        })
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_not_enrolled_returns_400() -> None:
    email, _ = await _seed_admin(enrolled=False)
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": "123456",
        })
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_requires_session() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        r = await c.get("/api/admin/me")
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_returns_admin_after_login() -> None:
    email, secret = await _seed_admin()
    code = pyotp.TOTP(secret).now()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        login = await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": code,
        })
        assert login.status_code == 200
        me = await c.get("/api/admin/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_destroys_session() -> None:
    email, secret = await _seed_admin()
    code = pyotp.TOTP(secret).now()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": code,
        })
        # Logout is a mutating admin request but exempt from CSRF since user
        # just logged in and the CSRF cookie was already minted by the login
        # response. The SPA reads it from document.cookie. In this test we
        # copy it into the header explicitly.
        csrf = c.cookies.get("csrf")
        r = await c.post("/api/admin/logout", headers={"X-CSRF-Token": csrf or ""})
        assert r.status_code == 204

        me = await c.get("/api/admin/me")
        assert me.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lockout_after_5_failed_attempts() -> None:
    email, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        for i in range(5):
            await c.post("/api/admin/login", json={
                "email": email, "password": "wrong", "totp_code": "000000",
            })
        # 6th attempt is locked even with correct creds
        from pyotp import TOTP
        # Need secret — look it up
        async with SessionLocal() as s:
            from sqlalchemy import select
            admin = (await s.execute(
                select(Admin).where(Admin.email == email)
            )).scalar_one()
            secret = admin.totp_secret.decode("utf-8")
        code = TOTP(secret).now()
        r = await c.post("/api/admin/login", json={
            "email": email, "password": "StrongPw123!", "totp_code": code,
        })
        assert r.status_code == 423
