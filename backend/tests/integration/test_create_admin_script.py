"""End-to-end script-driven admin creation."""

import subprocess

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Admin


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_script_creates_admin_row() -> None:
    # This test runs INSIDE the api container (via docker compose exec).
    # The script is at /app/scripts/create_admin.py — relative path below works.
    proc = subprocess.run(
        [
            "/opt/venv/bin/python",
            "scripts/create_admin.py",
            "--email",
            "script@test.co",
            "--password",
            "ScriptTest123!",
        ],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    # Stdout should contain the otpauth:// URI
    assert "otpauth://totp/" in proc.stdout
    assert "Fylix" in proc.stdout

    async with SessionLocal() as session:
        row = (
            await session.execute(select(Admin).where(Admin.email == "script@test.co"))
        ).scalar_one()
        assert row.role == "admin"
        assert row.totp_enrolled is True
        assert row.totp_secret is not None
        # TOTP secret should NOT be the email or password (sanity check
        # against obvious plaintext leakage of sensitive fields).
        assert b"ScriptTest123" not in row.totp_secret


@pytest.mark.integration
@pytest.mark.asyncio
async def test_script_refuses_duplicate_email() -> None:
    for expected_code in (0, 2):
        proc = subprocess.run(
            [
                "/opt/venv/bin/python",
                "scripts/create_admin.py",
                "--email",
                "dupe@test.co",
                "--password",
                "DupeTest123!",
            ],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if expected_code == 0:
            assert proc.returncode == 0
        else:
            assert proc.returncode == 2
            assert "already exists" in proc.stderr
