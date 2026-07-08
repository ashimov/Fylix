"""transfer_files.filename GIN trigram index for admin search

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-17

admin_list_transfers search runs an OR between `sender_email ILIKE` and
a correlated subquery `transfer_id IN (SELECT transfer_id FROM
transfer_files WHERE filename ILIKE ?)`. The sender_email side uses the
existing `idx_transfers_sender_email_trgm` (GIN trigram, migration
0001). The filename side had no trigram index, so every admin search
triggered a sequential scan of transfer_files — quick on toy data,
painful at 1M+ uploaded files.

Add a GIN trigram index on `transfer_files.filename`. The pg_trgm
extension is already installed (0001). Trigram indexes support ILIKE
with leading wildcards once the query has >= 3 characters (default
trigram threshold); the handler now guards short queries to keep
planner behaviour predictable.

Non-concurrently is fine in a maintenance window; switch to
`postgresql_concurrently=True` + out-of-transaction if the deployment
can't afford the brief lock.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_transfer_files_filename_trgm "
        "ON transfer_files USING gin (filename gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transfer_files_filename_trgm")
