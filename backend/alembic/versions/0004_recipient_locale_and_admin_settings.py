"""recipient_locale_and_admin_settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-14

"""
import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ADMIN_SETTINGS: dict[str, object] = {
    "admin_session_ttl_minutes": 30,
    "admin_max_failed_attempts": 5,
    "admin_lockout_minutes": 15,
    "admin_cidr_allowlist": ["127.0.0.0/8"],
}


def upgrade() -> None:
    # Column for per-recipient locale (ru/kk/en). NULL = default to Phase 4 fallback.
    op.add_column(
        "transfer_recipients",
        sa.Column("locale", sa.Text(), nullable=True),
    )

    # Seed admin-specific settings rows.
    for key, value in ADMIN_SETTINGS.items():
        op.execute(
            sa.text(
                "INSERT INTO settings (key, value) "
                "VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, v=json.dumps(value))
        )


def downgrade() -> None:
    for key in ADMIN_SETTINGS:
        op.execute(
            sa.text("DELETE FROM settings WHERE key = :k").bindparams(k=key)
        )
    op.drop_column("transfer_recipients", "locale")
