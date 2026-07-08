"""Admin transfer list/detail/delete/revoke endpoints."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pyotp
import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Admin, AdminAction, Transfer, TransferFile, TransferRecipient
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
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


async def _seed_admin(role: str = "admin") -> tuple[str, str, str]:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    email = f"{role}@test.co"
    async with SessionLocal() as s:
        s.add(Admin(
            email=email,
            password_hash=auth.hash_password("StrongPw123!"),
            totp_secret=secret.encode("utf-8"),
            totp_enrolled=True,
            role=role,
            disabled=False,
        ))
        await s.commit()
    return email, secret, "StrongPw123!"


async def _login(c: httpx.AsyncClient, email: str, secret: str) -> str:
    code = pyotp.TOTP(secret).now()
    r = await c.post("/api/admin/login", json={
        "email": email, "password": "StrongPw123!", "totp_code": code,
    })
    assert r.status_code == 200, r.text
    return c.cookies.get("csrf") or ""


async def _seed_transfer(status: str = "ready") -> UUID:
    async with SessionLocal() as s:
        t = Transfer(
            token=uuid4().hex,
            manage_token=uuid4().hex,
            sender_email="sender@example.com",
            sender_ip="10.0.0.1",
            sender_country="KZ",
            status=status,
            total_size=1024,
            file_count=1,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            wrapped_key=b"fakewrappedkey",
        )
        s.add(t)
        await s.flush()
        tid = t.id
        s.add(TransferFile(
            transfer_id=tid,
            filename="test.txt",
            safe_filename="test.txt",
            mime_type="text/plain",
            size_bytes=1024,
            object_key=f"{tid}/file1.enc",
            iv=b"\x00" * 12,
            sha256_cipher=b"\x00" * 32,
        ))
        s.add(TransferRecipient(
            transfer_id=tid,
            email="recipient@example.com",
        ))
        await s.commit()
    return tid


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_transfers_unauthenticated() -> None:
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.get("/api/admin/transfers")
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_transfers_returns_items() -> None:
    await _seed_transfer()
    email, secret, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/transfers")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert len(body["items"]) >= 1
    item = body["items"][0]
    assert "id" in item
    assert item["sender_email"] == "sender@example.com"
    assert item["status"] == "ready"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_transfers_filter_by_status() -> None:
    await _seed_transfer(status="ready")
    await _seed_transfer(status="revoked")
    email, secret, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/transfers", params={"status": "revoked"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["status"] == "revoked" for i in items)
    assert len(items) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_transfer_detail() -> None:
    tid = await _seed_transfer()
    email, secret, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get(f"/api/admin/transfers/{tid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(tid)
    assert len(body["files"]) == 1
    assert body["files"][0]["filename"] == "test.txt"
    assert len(body["recipients"]) == 1
    assert body["recipients"][0]["email"] == "recipient@example.com"
    assert isinstance(body["downloads"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_transfer_detail_not_found() -> None:
    email, secret, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get(f"/api/admin/transfers/{uuid4()}")
    assert r.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_delete_transfer() -> None:
    tid = await _seed_transfer()
    email, secret, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.delete(f"/api/admin/transfers/{tid}", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204

    async with SessionLocal() as s:
        t = await s.get(Transfer, tid)
        assert t.status == "deleted"
        assert t.wrapped_key is None
        # Check admin_action was recorded
        actions = (await s.execute(
            select(AdminAction).where(AdminAction.action == "delete_transfer")
        )).scalars().all()
        assert len(actions) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_revoke_transfer() -> None:
    tid = await _seed_transfer()
    email, secret, _ = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(f"/api/admin/transfers/{tid}/revoke", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204

    async with SessionLocal() as s:
        t = await s.get(Transfer, tid)
        assert t.status == "revoked"
        # wrapped_key kept on revoke
        assert t.wrapped_key is not None
        actions = (await s.execute(
            select(AdminAction).where(AdminAction.action == "revoke_transfer")
        )).scalars().all()
        assert len(actions) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_cannot_delete_transfer() -> None:
    tid = await _seed_transfer()
    email, secret, _ = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.delete(f"/api/admin/transfers/{tid}", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_cannot_revoke_transfer() -> None:
    tid = await _seed_transfer()
    email, secret, _ = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        r = await c.post(f"/api/admin/transfers/{tid}/revoke", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
