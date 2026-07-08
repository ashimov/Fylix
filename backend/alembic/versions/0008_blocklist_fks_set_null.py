"""blocklist_* FKs gain ON DELETE SET NULL

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-17

The three blocklist tables (blocklist_ips, blocklist_email_domains,
blocklist_emails) each have an `added_by` column referencing admins(id)
with no ON DELETE behaviour. Deleting an admin who had added entries
fails with a FK violation, leaving admin deletion partial and the DB in
an inconsistent state (admin row gone or disabled, but audit trail still
attached).

Switch the FKs to `ON DELETE SET NULL` so admin deletion always
succeeds. The blocklist entry itself is preserved — only the
"who added this" attribution is lost, which is acceptable given the
admin_actions log still records the original add operation.

The original 0002 migration created these FKs **unnamed**, so Postgres
assigned default names following the convention `<table>_<col>_fkey`.
The drop_constraint calls below use that exact default so no rename is
needed on pre-existing installations.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES: tuple[str, ...] = (
    "blocklist_ips",
    "blocklist_email_domains",
    "blocklist_emails",
)


def upgrade() -> None:
    for table in _TABLES:
        fkey = f"{table}_added_by_fkey"
        op.drop_constraint(fkey, table, type_="foreignkey")
        op.create_foreign_key(
            fkey,
            table,
            "admins",
            ["added_by"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in _TABLES:
        fkey = f"{table}_added_by_fkey"
        op.drop_constraint(fkey, table, type_="foreignkey")
        op.create_foreign_key(
            fkey,
            table,
            "admins",
            ["added_by"],
            ["id"],
        )
