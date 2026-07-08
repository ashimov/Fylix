import os

import httpx
import pyotp
import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Admin, Setting
from app.services.auth import AuthService, wrap_totp_secret
from app.crypto import load_master_key
from app.config import settings as app_settings


BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admins"))
        # Delete all telegram_* settings so they fall back to in-code defaults.
        await s.execute(text("DELETE FROM settings WHERE key LIKE 'telegram_%'"))
        await s.commit()


async def _login_admin(c: httpx.AsyncClient) -> str:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    master = load_master_key(app_settings.master_key_path, enforce_perms=False)
    async with SessionLocal() as s:
        s.add(Admin(
            email="tg@test.co",
            password_hash=auth.hash_password("StrongPw12345!"),
            totp_secret=wrap_totp_secret(master, secret),
            totp_enrolled=True,
            role="admin",
        ))
        await s.commit()
    code = pyotp.TOTP(secret).now()
    r = await c.post("/api/admin/login", json={
        "email": "tg@test.co", "password": "StrongPw12345!", "totp_code": code,
    })
    assert r.status_code == 200
    return c.cookies.get("csrf") or ""


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_telegram_reveals_no_token() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        await _login_admin(c)
        r = await c.get("/api/admin/telegram")
    assert r.status_code == 200
    body = r.json()
    assert "bot_token" not in body
    assert body["bot_token_is_set"] is False
    assert body["alert_on_infected"] is True
    assert body["rate_limit_spike_threshold"] == 20


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_telegram_persists_changes() -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        csrf = await _login_admin(c)
        r = await c.patch("/api/admin/telegram", json={
            "bot_token": "1234:TOKEN",
            "chat_id": "-100999",
            "alert_on_storage_high": False,
            "rate_limit_spike_threshold": 50,
        }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    body = r.json()
    assert body["bot_token_is_set"] is True
    assert body["chat_id"] == "-100999"
    assert body["alert_on_storage_high"] is False
    assert body["rate_limit_spike_threshold"] == 50

    # Verify in DB — token is AES-KW wrapped before storage (commit a7177ee),
    # so row.value is {"wrapped": "<base64>"} rather than the plaintext token.
    async with SessionLocal() as s:
        row = await s.get(Setting, "telegram_bot_token")
        assert row is not None
        assert isinstance(row.value, dict)
        assert "wrapped" in row.value
        assert row.value["wrapped"]  # non-empty ciphertext


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_cannot_patch_telegram() -> None:
    # Seed viewer
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    master = load_master_key(app_settings.master_key_path, enforce_perms=False)
    async with SessionLocal() as s:
        s.add(Admin(
            email="v@test.co",
            password_hash=auth.hash_password("StrongPw12345!"),
            totp_secret=wrap_totp_secret(master, secret),
            totp_enrolled=True,
            role="viewer",
        ))
        await s.commit()

    code = pyotp.TOTP(secret).now()
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        login = await c.post("/api/admin/login", json={
            "email": "v@test.co", "password": "StrongPw12345!", "totp_code": code,
        })
        assert login.status_code == 200
        csrf = c.cookies.get("csrf") or ""
        r = await c.patch("/api/admin/telegram", json={"bot_token": "x"},
                          headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
