"""audit_log FK constraints with ON DELETE SET NULL

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-17

audit_log.transfer_id and audit_log.admin_id were plain PG_UUID columns
with no FK constraint — orphaned rows could accumulate silently if a
transfer or admin row were ever deleted, making audit history
unverifiable.

Add FKs with ON DELETE SET NULL (matching the existing 0005 pattern for
admin_actions.admin_id). Audit history survives parent deletion; the
surviving audit row keeps its ts + event_type + severity + details, only
losing the broken reference.

Preflight: neither transfers nor admins currently have a hard-delete
code path — transfers are marked status='deleted' (soft) and admins are
disabled rather than removed. So in a healthy installation no orphaned
audit rows exist and the constraint adds cleanly. If validation fails
for an already-contaminated DB, delete the orphans then re-run:

    UPDATE audit_log SET transfer_id = NULL
     WHERE transfer_id IS NOT NULL
       AND transfer_id NOT IN (SELECT id FROM transfers);
    UPDATE audit_log SET admin_id = NULL
     WHERE admin_id IS NOT NULL
       AND admin_id NOT IN (SELECT id FROM admins);
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        "audit_log_transfer_id_fkey",
        "audit_log",
        "transfers",
        ["transfer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "audit_log_admin_id_fkey",
        "audit_log",
        "admins",
        ["admin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("audit_log_admin_id_fkey", "audit_log", type_="foreignkey")
    op.drop_constraint("audit_log_transfer_id_fkey", "audit_log", type_="foreignkey")
