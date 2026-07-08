"""admin_tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admins",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("totp_secret", sa.LargeBinary(), nullable=True),
        sa.Column("totp_enrolled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin','viewer')", name="admins_role_check"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "admin_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_admin_actions_admin_time", "admin_actions", ["admin_id", "ts"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("transfer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "severity IN ('info','warn','error','critical')",
            name="audit_severity_check",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_ts", "audit_log", ["ts"])
    op.create_index("idx_audit_event_ts", "audit_log", ["event_type", "ts"])
    op.create_index("idx_audit_ip", "audit_log", ["ip"])

    op.create_table(
        "blocklist_ips",
        sa.Column("cidr", postgresql.INET(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["added_by"], ["admins.id"]),
        sa.PrimaryKeyConstraint("cidr"),
    )

    op.create_table(
        "blocklist_email_domains",
        sa.Column("domain", postgresql.CITEXT(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["added_by"], ["admins.id"]),
        sa.PrimaryKeyConstraint("domain"),
    )

    op.create_table(
        "blocklist_emails",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["added_by"], ["admins.id"]),
        sa.PrimaryKeyConstraint("email"),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["admins.id"]),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("blocklist_emails")
    op.drop_table("blocklist_email_domains")
    op.drop_table("blocklist_ips")
    op.drop_index("idx_audit_ip", table_name="audit_log")
    op.drop_index("idx_audit_event_ts", table_name="audit_log")
    op.drop_index("idx_audit_ts", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("idx_admin_actions_admin_time", table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_table("admins")
