"""Admins CRUD endpoints (list / create / update / reset-totp / delete)."""

import os

import httpx
import pyotp
import pytest
from sqlalchemy import select, text

from app.config import settings as app_settings
from app.crypto import load_master_key
from app.db import SessionLocal
from app.models import Admin
from app.services.auth import AuthService, is_wrapped_totp

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admin_actions"))
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


async def _seed_and_login(
    c: httpx.AsyncClient,
    *,
    email: str = "root@test.co",
    role: str = "admin",
) -> str:
    """Return the X-CSRF-Token matching the session cookie."""
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    master = load_master_key(app_settings.master_key_path, enforce_perms=False)
    from app.services.auth import wrap_totp_secret

    async with SessionLocal() as s:
        s.add(
            Admin(
                email=email,
                password_hash=auth.hash_password("StrongPw12345!"),
                totp_secret=wrap_totp_secret(master, secret),
                totp_enrolled=True,
                role=role,
                disabled=False,
            )
        )
        await s.commit()
    code = pyotp.TOTP(secret).now()
    r = await c.post(
        "/api/admin/login",
        json={
            "email": email,
            "password": "StrongPw12345!",
            "totp_code": code,
        },
    )
    assert r.status_code == 200, r.text
    return c.cookies.get("csrf") or ""


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_admins() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        await _seed_and_login(c)
        # Seed a second admin directly
        async with SessionLocal() as s:
            auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
            s.add(
                Admin(
                    email="viewer@test.co",
                    password_hash=auth.hash_password("ViewerPw12345!"),
                    role="viewer",
                    disabled=False,
                )
            )
            await s.commit()
        r = await c.get("/api/admin/admins")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    emails = {a["email"] for a in items}
    assert "root@test.co" in emails
    assert "viewer@test.co" in emails


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_admin_returns_totp_uri() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        r = await c.post(
            "/api/admin/admins",
            json={
                "email": "newadmin@test.co",
                "password": "NewAdminPw12345!",
                "role": "admin",
            },
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["admin"]["email"] == "newadmin@test.co"
    assert body["totp_uri"].startswith("otpauth://totp/")

    # New admin's TOTP secret must be wrapped
    async with SessionLocal() as s:
        a = (await s.execute(select(Admin).where(Admin.email == "newadmin@test.co"))).scalar_one()
        assert is_wrapped_totp(a.totp_secret) is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_admin_duplicate_email_409() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        r = await c.post(
            "/api/admin/admins",
            json={"email": "root@test.co", "password": "Dupe12345678!", "role": "admin"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_admin_role() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        async with SessionLocal() as s:
            auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
            a = Admin(
                email="target@test.co",
                password_hash=auth.hash_password("abcdefghij123!"),
                role="admin",
            )
            s.add(a)
            await s.commit()
            await s.refresh(a)
            target_id = a.id

        r = await c.patch(
            f"/api/admin/admins/{target_id}",
            json={"role": "viewer"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_admin_disable() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        async with SessionLocal() as s:
            auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
            a = Admin(
                email="other@test.co",
                password_hash=auth.hash_password("abcdefghij123!"),
                role="admin",
                disabled=False,
            )
            s.add(a)
            await s.commit()
            await s.refresh(a)
            other_id = a.id

        r = await c.patch(
            f"/api/admin/admins/{other_id}",
            json={"disabled": True},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 200
    assert r.json()["disabled"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reset_totp_returns_new_uri() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        async with SessionLocal() as s:
            a = (await s.execute(select(Admin).where(Admin.email == "root@test.co"))).scalar_one()
            original_wrapped = a.totp_secret

        r = await c.post(
            f"/api/admin/admins/{a.id}/reset-totp",
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 200
    assert r.json()["totp_uri"].startswith("otpauth://totp/")

    async with SessionLocal() as s:
        a = (await s.execute(select(Admin).where(Admin.email == "root@test.co"))).scalar_one()
        # Secret changed
        assert a.totp_secret != original_wrapped
        assert is_wrapped_totp(a.totp_secret)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_admin() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        # Need two admins to delete one (min 2 active enforced)
        async with SessionLocal() as s:
            auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
            a = Admin(
                email="victim@test.co",
                password_hash=auth.hash_password("abcdefghij123!"),
                role="admin",
            )
            s.add(a)
            await s.commit()
            await s.refresh(a)
            vid = a.id

        r = await c.delete(
            f"/api/admin/admins/{vid}",
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 204

    async with SessionLocal() as s:
        assert await s.get(Admin, vid) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cannot_delete_last_active_admin() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        async with SessionLocal() as s:
            root = (
                await s.execute(select(Admin).where(Admin.email == "root@test.co"))
            ).scalar_one()
            root_id = root.id
        r = await c.delete(
            f"/api/admin/admins/{root_id}",
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 409
    assert (
        "minimum" in r.json()["detail"]["error"].lower()
        or r.json()["detail"]["error"] == "min_admins"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cannot_disable_last_active_admin() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c)
        async with SessionLocal() as s:
            root = (
                await s.execute(select(Admin).where(Admin.email == "root@test.co"))
            ).scalar_one()
        r = await c.patch(
            f"/api/admin/admins/{root.id}",
            json={"disabled": True},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_role_cannot_mutate() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _seed_and_login(c, email="viewer@test.co", role="viewer")
        r = await c.post(
            "/api/admin/admins",
            json={"email": "x@y.co", "password": "aaabbb12345!", "role": "viewer"},
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 403
