"""admin_actions_fk_set_null

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-14

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Change ON DELETE behaviour to SET NULL so deleting an admin preserves their action log.
    op.execute("ALTER TABLE admin_actions ALTER COLUMN admin_id DROP NOT NULL")
    op.drop_constraint("admin_actions_admin_id_fkey", "admin_actions", type_="foreignkey")
    op.create_foreign_key(
        "admin_actions_admin_id_fkey",
        "admin_actions",
        "admins",
        ["admin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("admin_actions_admin_id_fkey", "admin_actions", type_="foreignkey")
    op.create_foreign_key(
        "admin_actions_admin_id_fkey",
        "admin_actions",
        "admins",
        ["admin_id"],
        ["id"],
    )
    op.execute("ALTER TABLE admin_actions ALTER COLUMN admin_id SET NOT NULL")
