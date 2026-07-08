"""Rotate the master encryption key: unwrap all per-transfer + TOTP wrapped
keys with the OLD master, rewrap with the NEW master, persist.

Prereqs:
    - The NEW master key file is present at the path passed via --new-key.
    - The OLD master key is the one currently loaded by the running api
      (read from MASTER_KEY_PATH env at the time this script was started).

Strategy:
    1. Load both keys into memory.
    2. In chunks of 1000 rows per commit, iterate transfers where wrapped_key
       IS NOT NULL: unwrap with old -> wrap with new -> UPDATE.
    3. Same for admins.totp_secret (handling the 48-byte wrap-totp-secret format).
    4. At completion, print summary; caller is responsible for swapping the
       secret file and restarting containers.

This is idempotent only if aborted cleanly between chunks; a crash mid-chunk
leaves an inconsistent state that's recoverable by a full restore.

Usage (inside api container):
    /opt/venv/bin/python scripts/rotate_master_key.py --new-key /tmp/new_master_key
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.crypto import load_master_key  # noqa: E402
from app.crypto.envelope import unwrap_key, wrap_key  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Admin, Transfer  # noqa: E402
from app.services.auth import (  # noqa: E402
    is_wrapped_totp,
    unwrap_totp_secret,
    wrap_totp_secret,
)

CHUNK = 1000


async def _rotate_transfers(old: bytes, new: bytes) -> int:
    """Rewrap all transfer keys: old → new. Uses the previous-key fallback
    so the script is idempotent even if the online admin rewrap endpoint
    (POST /api/admin/crypto/rewrap) already migrated some rows."""
    rewrapped = 0
    async with SessionLocal() as session:
        last_id = None
        while True:
            stmt = select(Transfer).where(Transfer.wrapped_key.is_not(None)).order_by(Transfer.id).limit(CHUNK)
            if last_id is not None:
                stmt = stmt.where(Transfer.id > last_id)
            rows = (await session.execute(stmt)).scalars().all()
            if not rows:
                break
            for t in rows:
                if t.wrapped_key is None:
                    continue
                # Try new first (some rows may already be migrated), fall
                # back to old on InvalidUnwrap.
                file_key = unwrap_key(new, t.wrapped_key, previous_master_key=old)
                t.wrapped_key = wrap_key(new, file_key)
                rewrapped += 1
                last_id = t.id
            await session.commit()
            print(f"  rewrapped {rewrapped} transfers so far...")
    return rewrapped


async def _rotate_admins(old: bytes, new: bytes) -> int:
    rewrapped = 0
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Admin).where(Admin.totp_secret.is_not(None))
        )).scalars().all()
        for a in rows:
            secret = a.totp_secret
            if secret is None or not is_wrapped_totp(secret):
                # Legacy plaintext or null — leave for wrap_totp_secrets.py.
                continue
            # Try new first, fall back to old — matches the online endpoint.
            plain = unwrap_totp_secret(new, secret, previous_master_key=old)
            a.totp_secret = wrap_totp_secret(new, plain)
            rewrapped += 1
        await session.commit()
    return rewrapped


async def _main(new_key_path: Path) -> int:
    old_key = load_master_key(settings.master_key_path, enforce_perms=False)
    new_key = load_master_key(new_key_path, enforce_perms=False)

    if old_key == new_key:
        print("ERROR: new key is identical to current key — nothing to do.", file=sys.stderr)
        return 2

    print("Rotating per-transfer wrapped_keys...")
    n_t = await _rotate_transfers(old_key, new_key)
    print(f"  done: {n_t} transfers rewrapped.")

    print("Rotating admin TOTP secrets...")
    n_a = await _rotate_admins(old_key, new_key)
    print(f"  done: {n_a} admins rewrapped.")

    print("")
    print("=== ROTATION COMPLETE ===")
    print(f"Transfers rewrapped: {n_t}")
    print(f"Admins rewrapped:    {n_a}")
    print("")
    print("NEXT STEPS:")
    print("  1. Swap the master-key Docker secret file to the new key.")
    print("  2. Restart api and worker containers: docker compose restart api worker")
    print("  3. Smoke-test by downloading an existing transfer and logging in.")
    print("  4. Store the OLD key in a sealed envelope for 30 days (recovery).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Rotate master key")
    p.add_argument("--new-key", type=Path, required=True, help="path to the new 32-byte key")
    args = p.parse_args()
    return asyncio.run(_main(args.new_key))


if __name__ == "__main__":
    raise SystemExit(main())
