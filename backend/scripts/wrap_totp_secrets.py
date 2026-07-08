"""One-shot utility: wrap any legacy plaintext TOTP secrets in the admins table.

Idempotent — rows that already look wrapped (40 bytes AES-KW output) are skipped.

Usage:
    docker compose exec api python scripts/wrap_totp_secrets.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make imports work when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.crypto import load_master_key  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Admin  # noqa: E402
from app.services.auth import is_wrapped_totp, wrap_totp_secret  # noqa: E402


async def _main() -> int:
    master = load_master_key(settings.master_key_path, enforce_perms=False)

    wrapped_count = 0
    skipped_count = 0

    async with SessionLocal() as session:
        rows = (await session.execute(select(Admin))).scalars().all()
        for admin in rows:
            if admin.totp_secret is None:
                skipped_count += 1
                continue
            if is_wrapped_totp(admin.totp_secret):
                skipped_count += 1
                continue
            plain = admin.totp_secret.decode("utf-8")
            admin.totp_secret = wrap_totp_secret(master, plain)
            wrapped_count += 1
        await session.commit()

    print(f"Wrapped: {wrapped_count}, Skipped: {skipped_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
