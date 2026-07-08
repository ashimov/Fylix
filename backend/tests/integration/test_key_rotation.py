"""Rotate the master key and verify: existing transfers still decrypt,
existing admins still log in.

This test is SLOW (~10 seconds) because it generates real transfers and
then runs the in-process rotation subprocess.
"""
import asyncio
import io
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text

from app.config import settings as app_settings
from app.crypto import load_master_key
from app.crypto.envelope import unwrap_key
from app.crypto.stream import decrypt_stream
from app.db import SessionLocal
from app.models import Admin, Transfer, TransferFile
from app.services.auth import AuthService, unwrap_totp_secret, wrap_totp_secret
from app.services.storage import StorageService


BASE = os.environ.get("PUBLIC_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
async def _reset() -> None:
    async with SessionLocal() as s:
        await s.execute(text(
            "TRUNCATE TABLE transfers, transfer_recipients, transfer_files, "
            "downloads, audit_log, admin_actions RESTART IDENTITY CASCADE"
        ))
        await s.execute(text("DELETE FROM admins"))
        await s.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_master_key_rotation_preserves_access() -> None:
    """After rotation: existing transfer still decrypts + existing admin still logs in."""

    # --- Part A: seed data BEFORE rotation ---

    # Seed a ready transfer (upload + wait for worker)
    payload = b"rotation-test-payload" * 100  # ~2 KB
    async with httpx.AsyncClient(base_url=BASE, verify=False) as c:
        resp = await c.post("/api/transfers", json={
            "sender_email": "rot@test.co",
            "recipient_emails": ["r@test.co"],
            "ttl_days": 1,
            "files": [{"filename": "rot.bin", "size": len(payload)}],
        })
        assert resp.status_code == 201
        body = resp.json()
        transfer_id = UUID(body["transfer_id"])
        patch = await c.patch(
            urlparse(body["upload_urls"]["rot.bin"]).path,
            content=payload,
            headers={"content-type": "application/offset+octet-stream", "upload-offset": "0"},
        )
        assert patch.status_code == 204

    # Wait for worker to flip status=ready
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 15
    while loop.time() < deadline:
        async with SessionLocal() as s:
            t = await s.get(Transfer, transfer_id)
            if t and t.status == "ready":
                break
        await asyncio.sleep(0.3)
    else:
        pytest.fail("transfer never reached ready")

    # Seed an admin with a wrapped TOTP secret
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)
    secret = auth.generate_totp_secret()
    master_old = load_master_key(app_settings.master_key_path, enforce_perms=False)
    async with SessionLocal() as s:
        s.add(Admin(
            email="pre-rotate@test.co",
            password_hash=auth.hash_password("StrongPw12345!"),
            totp_secret=wrap_totp_secret(master_old, secret),
            totp_enrolled=True,
            role="admin",
            disabled=False,
        ))
        await s.commit()

    # --- Part B: rotate ---

    # Generate a fresh 32-byte key into a temp file (we are inside the api container).
    new_master = os.urandom(32)
    assert new_master != master_old  # astronomically unlikely but guard anyway

    new_key_fd, new_key_path_str = tempfile.mkstemp(prefix="new_master_key_test_")
    try:
        with os.fdopen(new_key_fd, "wb") as fh:
            fh.write(new_master)
        os.chmod(new_key_path_str, 0o400)

        # Run the rotation script as a subprocess (same approach as other integration tests)
        proc = subprocess.run(
            ["/opt/venv/bin/python", "scripts/rotate_master_key.py",
             "--new-key", new_key_path_str],
            capture_output=True, text=True, timeout=60, cwd="/app",
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
        assert "ROTATION COMPLETE" in proc.stdout
        assert "transfers rewrapped" in proc.stdout

    finally:
        Path(new_key_path_str).unlink(missing_ok=True)

    # --- Part C: verify rewrapped data decrypts with NEW key ---

    storage = StorageService(
        endpoint=app_settings.minio_endpoint,
        access_key=app_settings.minio_root_user,
        secret_key=app_settings.minio_root_password,
        bucket=app_settings.minio_bucket,
        secure=app_settings.minio_secure,
    )

    async with SessionLocal() as s:
        t = await s.get(Transfer, transfer_id)
        assert t is not None and t.wrapped_key is not None
        # Unwrap with the NEW key — this proves rewrap succeeded
        file_key = unwrap_key(new_master, t.wrapped_key)

        f = (await s.execute(
            select(TransferFile).where(TransferFile.transfer_id == transfer_id)
        )).scalar_one()

    # Decrypt ciphertext with new-key-derived file_key — should roundtrip
    ct = b"".join(storage.get_stream(f.object_key))
    plain = io.BytesIO()
    decrypt_stream(file_key, f.iv, io.BytesIO(ct), plain)
    assert plain.getvalue() == payload

    # --- Part D: verify admin TOTP still works with NEW key ---

    async with SessionLocal() as s:
        a = (await s.execute(
            select(Admin).where(Admin.email == "pre-rotate@test.co")
        )).scalar_one()
        # TOTP secret should now unwrap with NEW key and yield the ORIGINAL secret
        recovered_secret = unwrap_totp_secret(new_master, a.totp_secret)
        assert recovered_secret == secret

    # NOTE: we do NOT swap the actual master_key Docker secret here — that's
    # an ops step that requires container restart. The rotation script leaves
    # the DB in a state consistent with the NEW key; the caller (shell wrapper
    # or operator) is responsible for swapping secrets/master_key and restarting
    # api + worker. Since we can't restart here without breaking the test
    # session, we just assert the DB state is correct and stop.
    #
    # The test leaves the api/worker containers running with the OLD key, so
    # they can no longer decrypt transfers. Clean up by truncating the test
    # data in the autouse fixture on the next test run.
