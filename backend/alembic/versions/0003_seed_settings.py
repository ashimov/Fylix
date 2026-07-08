"""seed_settings

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-13

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED: dict[str, object] = {
    "max_transfer_size_gb": 2,
    "max_ttl_days": 7,
    "rate_hourly": 10,
    "rate_daily": 100,
    "rate_download_hourly": 30,
    "geoip_enabled": False,
    "geoip_countries": ["KZ", "UZ", "KG"],
    "extension_blacklist": [
        ".exe",
        ".bat",
        ".scr",
        ".vbs",
        ".js",
        ".msi",
        ".ps1",
        ".hta",
        ".lnk",
        ".iso",
    ],
    "max_recipients": 20,
    "max_message_length": 2000,
    "audit_retention_days": 730,
}


def upgrade() -> None:
    for key, value in SEED.items():
        op.execute(
            sa.text("INSERT INTO settings (key, value) VALUES (:k, CAST(:v AS jsonb))").bindparams(
                k=key, v=json.dumps(value)
            )
        )


def downgrade() -> None:
    for key in SEED:
        op.execute(sa.text("DELETE FROM settings WHERE key = :k").bindparams(k=key))
