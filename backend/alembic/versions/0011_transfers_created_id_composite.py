"""Composite (created_at DESC, id DESC) index for admin transfer pagination.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-20

`admin_list_transfers` paginates via the composite-cursor pattern:

    WHERE (created_at, id) < (:cursor_ts, :cursor_id)
    ORDER BY created_at DESC, id DESC
    LIMIT :page_size

`transfers.created_at` already has a standalone index (from 0001) and
`transfers.id` is the PK (unique B-tree). The planner can walk the
created_at index but then resort `(created_at, id)` tuples in memory
— fine at 10K rows, quadratic-looking as the table grows.

A dedicated composite index `(created_at DESC, id DESC)` lets the
planner walk the index in order and short-circuit on the composite
WHERE. Enables index-only scans for the list endpoint.

Non-concurrently is acceptable in a maintenance window; switch to
`postgresql_concurrently=True` + out-of-transaction for zero-downtime
deploys on large tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_transfers_created_at_id_desc "
        "ON transfers (created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transfers_created_at_id_desc")
