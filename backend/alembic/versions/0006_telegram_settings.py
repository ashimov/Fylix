"""telegram_settings

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-14

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEED: dict[str, object] = {
    "telegram_alert_on_infected": True,
    "telegram_alert_on_rate_limit_spike": True,
    "telegram_alert_on_admin_login_fail_spike": True,
    "telegram_alert_on_storage_high": True,
    "telegram_alert_on_defender_event": True,
    "telegram_rate_limit_spike_threshold": 20,
}


def upgrade() -> None:
    for key, value in SEED.items():
        op.execute(
            sa.text(
                "INSERT INTO settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, v=json.dumps(value))
        )


def downgrade() -> None:
    for key in SEED:
        op.execute(sa.text("DELETE FROM settings WHERE key = :k").bindparams(k=key))
