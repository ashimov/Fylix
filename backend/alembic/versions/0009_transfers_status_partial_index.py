"""transfers partial index on status for the KPI aggregate

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-17

AnalyticsService._kpi aggregates four quantities off the transfers
table on every cache miss (cache TTL: 60s):
  - COUNT(*) WHERE status='ready'
  - COUNT(*) WHERE status='infected'
  - SUM(total_size) WHERE created_at >= today_start
  - SUM(total_size) WHERE created_at >= week_start

The two status counts currently trigger a sequential scan because no
index includes `status`. On a 10M-row table that's multi-second and
happens every minute under a cold cache. A partial index on the two
"hot" status values trims that to an index-only scan.

The CREATE INDEX is non-CONCURRENTLY (simple table lock) because
alembic is typically run in a maintenance window on Fylix. If that
assumption ever breaks for a deployment, switch to
`op.create_index(..., postgresql_concurrently=True)` and run outside
a transaction (requires removing transactional_ddl for this migration).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_transfers_status_active",
        "transfers",
        ["status"],
        postgresql_where="status IN ('ready', 'infected')",
    )


def downgrade() -> None:
    op.drop_index("idx_transfers_status_active", table_name="transfers")
