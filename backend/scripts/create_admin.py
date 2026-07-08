"""Bootstrap an admin account from the command line.

Usage (inside api container):
    python scripts/create_admin.py --email admin@example.com --password StrongPw!

Outputs:
- Inserts a row in `admins` with TOTP secret already stored (bytes).
- Prints the otpauth:// URI so the operator can scan it in Google Authenticator.
- Prints 10 Argon2-hashed backup codes (human-readable codes printed once;
  only the hashes go into logs/DB; NOT persisted in DB in this Phase —
  backup-code storage is deferred to Phase 6).

Security note: TOTP secret is wrapped with master_key via AES-KW (RFC 3394)
before insert. Run `scripts/wrap_totp_secrets.py` to migrate any legacy
plaintext secrets created before this hardening was applied.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

# Ensure the repo root (/app inside the container, or the backend/ directory
# locally) is on sys.path so that `from app.xxx import ...` resolves correctly
# whether the script is invoked as `python scripts/create_admin.py` or via
# `python -m scripts.create_admin`.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from sqlalchemy import select

from app.config import settings
from app.crypto import load_master_key
from app.db import SessionLocal
from app.models import Admin
from app.services.auth import AuthService, wrap_totp_secret


async def _main(email: str, password: str, role: str) -> int:
    auth = AuthService(max_failed_attempts=5, lockout_minutes=15)

    async with SessionLocal() as session:
        existing = await session.execute(select(Admin).where(Admin.email == email))
        if existing.scalar_one_or_none() is not None:
            print(f"ERROR: admin with email {email!r} already exists", file=sys.stderr)
            return 2

        secret = auth.generate_totp_secret()
        master = load_master_key(settings.master_key_path, enforce_perms=False)
        wrapped = wrap_totp_secret(master, secret)
        admin = Admin(
            email=email,
            password_hash=auth.hash_password(password),
            totp_secret=wrapped,
            totp_enrolled=True,
            role=role,
            disabled=False,
        )
        session.add(admin)
        await session.commit()

    uri = auth.build_totp_uri(secret, email=email, issuer="Fylix")

    # Generate 10 backup codes and print them; DO NOT persist yet.
    backup_codes = [secrets.token_hex(4) for _ in range(10)]

    print("=========================================================")
    print(f"Admin {email!r} created with role={role}")
    print("=========================================================")
    print()
    print("TOTP enrolment URI (paste into Authenticator app):")
    print(f"  {uri}")
    print()
    print("Backup codes (save these — we will NOT show them again):")
    for c in backup_codes:
        print(f"  {c}")
    print()
    print("Backup codes are currently PRINTED ONLY (not stored).")
    print("Phase 6 hardening will add hashed backup-code rows.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Create a Fylix admin")
    p.add_argument("--email", required=True, help="admin email (citext unique)")
    p.add_argument("--password", required=True, help="plaintext password (will be Argon2id-hashed)")
    p.add_argument("--role", default="admin", choices=["admin", "viewer"])
    args = p.parse_args()
    return asyncio.run(_main(args.email, args.password, args.role))


if __name__ == "__main__":
    raise SystemExit(main())
