"""Admin audit log list, CSV export, and admin-actions list endpoints."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pyotp
import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import Admin, AuditLog
from app.services.auth import AuthService

BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admin_actions"))
        await s.execute(text("DELETE FROM audit_log"))
        await s.execute(text("UPDATE settings SET updated_by = NULL"))
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


async def _seed_admin(role: str = "admin") -> tuple[str, str]:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    email = f"{role}_{uuid4().hex[:6]}@test.co"
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
    return email, secret


async def _login(c: httpx.AsyncClient, email: str, secret: str) -> str:
    code = pyotp.TOTP(secret).now()
    r = await c.post("/api/admin/login", json={
        "email": email, "password": "StrongPw123!", "totp_code": code,
    })
    assert r.status_code == 200, r.text
    return c.cookies.get("csrf") or ""


async def _seed_audit_rows(n: int = 3) -> None:
    async with SessionLocal() as s:
        for i in range(n):
            s.add(AuditLog(
                ts=datetime.now(timezone.utc),
                event_type="test_event",
                severity="info",
                ip="127.0.0.1",
                details={"index": i},
            ))
        await s.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_list_unauthenticated() -> None:
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.get("/api/admin/audit")
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_list_returns_items() -> None:
    await _seed_audit_rows(3)
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/audit")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert len(body["items"]) >= 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_list_filter_by_event_type() -> None:
    await _seed_audit_rows(2)
    async with SessionLocal() as s:
        s.add(AuditLog(
            ts=datetime.now(timezone.utc),
            event_type="blocklist_hit",
            severity="warn",
        ))
        await s.commit()
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/audit", params={"event_type": "blocklist_hit"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["event_type"] == "blocklist_hit" for i in items)
    assert len(items) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_list_viewer_can_read() -> None:
    email, secret = await _seed_admin(role="viewer")
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/audit")
    assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_csv_content_type() -> None:
    await _seed_audit_rows(3)
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/audit.csv?since=2020-01-01T00:00:00%2B00:00&until=2020-03-31T00:00:00%2B00:00")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "audit.csv" in r.headers.get("content-disposition", "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_csv_first_bytes_valid() -> None:
    await _seed_audit_rows(2)
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/audit.csv?since=2020-01-01T00:00:00%2B00:00&until=2020-03-31T00:00:00%2B00:00")
    assert r.status_code == 200
    first_100 = r.text[:100]
    assert first_100.startswith("id,ts,event_type")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_csv_export_records_admin_action() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        await _login(c, email, secret)
        r = await c.get("/api/admin/audit.csv?since=2020-01-01T00:00:00%2B00:00&until=2020-03-31T00:00:00%2B00:00")
    assert r.status_code == 200

    async with SessionLocal() as s:
        from sqlalchemy import select
        from app.models import AdminAction
        actions = (await s.execute(
            select(AdminAction).where(AdminAction.action == "export_audit_csv")
        )).scalars().all()
        assert len(actions) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_actions_list_unauthenticated() -> None:
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.get("/api/admin/admin-actions")
    assert r.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_actions_list_returns_own_actions() -> None:
    email, secret = await _seed_admin()
    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        # Do a settings patch to create an admin action
        await c.patch("/api/admin/settings",
                      json={"max_recipients": 10},
                      headers={"X-CSRF-Token": csrf})
        r = await c.get("/api/admin/admin-actions")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    actions = body["items"]
    assert any(a["action"] == "update_setting" for a in actions)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_actions_list_filter_by_admin_id() -> None:
    email, secret = await _seed_admin()
    async with SessionLocal() as s:
        from sqlalchemy import select
        admin = (await s.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Admin).where(Admin.email == email)
        )).scalar_one()
        admin_id = str(admin.id)

    async with httpx.AsyncClient(base_url=BASE) as c:
        csrf = await _login(c, email, secret)
        await c.patch("/api/admin/settings",
                      json={"max_ttl_days": 14},
                      headers={"X-CSRF-Token": csrf})
        r = await c.get("/api/admin/admin-actions", params={"admin_id": admin_id})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["admin_id"] == admin_id for i in items)
