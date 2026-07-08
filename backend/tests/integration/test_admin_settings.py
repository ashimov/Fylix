"""Admin settings + extensions endpoints."""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pyotp
import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Admin, AdminAction, Setting
from app.services.auth import AuthService

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admin_actions"))
        # Null out settings.updated_by before deleting admins to avoid FK violation
        await s.execute(text("UPDATE settings SET updated_by = NULL"))
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
async def test_get_settings_returns_all() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/settings")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    # Should have at least some settings seeded
    assert len(body) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_settings_updates_value() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.patch(
            "/api/admin/settings", json={"max_recipients": 25}, headers={"X-CSRF-Token": csrf}
        )
    assert r.status_code == 200
    assert r.json()["max_recipients"] == 25

    async with SessionLocal() as s:
        row = await s.get(Setting, "max_recipients")
        assert row is not None
        assert row.value == 25


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_settings_records_admin_action() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        await c.patch(
            "/api/admin/settings", json={"max_ttl_days": 14}, headers={"X-CSRF-Token": csrf}
        )

    async with SessionLocal() as s:
        from sqlalchemy import select

        actions = (
            (await s.execute(select(AdminAction).where(AdminAction.action == "update_setting")))
            .scalars()
            .all()
        )
        assert len(actions) >= 1
        assert actions[0].target_id == "max_ttl_days"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_settings_unknown_key_returns_400() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.patch(
            "/api/admin/settings", json={"secret_backdoor": "evil"}, headers={"X-CSRF-Token": csrf}
        )
    # PatchSettingsRequest uses pydantic `extra="forbid"` — validation
    # rejects unknown keys with 422, not the old custom 400.
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("secret_backdoor" in (d.get("loc") or []) for d in detail)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_can_get_settings() -> None:
    email, secret = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/settings")
    assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_cannot_patch_settings() -> None:
    email, secret = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.patch(
            "/api/admin/settings", json={"max_recipients": 5}, headers={"X-CSRF-Token": csrf}
        )
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_extensions_returns_list() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/extensions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_extension_adds_to_list() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/extensions", json={"extension": ".exe"}, headers={"X-CSRF-Token": csrf}
        )
    assert r.status_code == 201
    assert ".exe" in r.json()

    async with SessionLocal() as s:
        row = await s.get(Setting, "extension_blacklist")
        assert row is not None
        assert ".exe" in row.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_extension_removes_from_list() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        await c.post(
            "/api/admin/extensions", json={"extension": ".bat"}, headers={"X-CSRF-Token": csrf}
        )
        r = await c.delete("/api/admin/extensions/.bat", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204

    async with SessionLocal() as s:
        row = await s.get(Setting, "extension_blacklist")
        if row is not None:
            assert ".bat" not in (row.value or [])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_extension_invalid_format_returns_400() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(
            "/api/admin/extensions",
            json={"extension": "exe"},  # missing leading dot
            headers={"X-CSRF-Token": csrf},
        )
    assert r.status_code == 400
