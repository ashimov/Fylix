"""core_tables

Revision ID: 0001
Revises:
Create Date: 2026-04-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "transfers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("manage_token", sa.Text(), nullable=False),
        sa.Column("sender_email", postgresql.CITEXT(), nullable=False),
        sa.Column("sender_ip", postgresql.INET(), nullable=False),
        sa.Column("sender_country", sa.String(length=2), nullable=True),
        sa.Column("sender_city", sa.Text(), nullable=True),
        sa.Column("sender_ua", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=True),
        sa.Column("total_size", sa.BigInteger(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("infected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('uploading','ready','expired','deleted','infected','revoked')",
            name="transfers_status_check",
        ),
        sa.CheckConstraint("char_length(message) <= 2000", name="transfers_message_len"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
        sa.UniqueConstraint("manage_token"),
    )
    op.create_index(
        "idx_transfers_expires_ready",
        "transfers",
        ["expires_at"],
        postgresql_where=sa.text("status = 'ready'"),
    )
    op.create_index("idx_transfers_sender_ip", "transfers", ["sender_ip"])
    op.create_index("idx_transfers_sender_email", "transfers", ["sender_email"])
    op.execute(
        "CREATE INDEX idx_transfers_sender_email_trgm "
        "ON transfers USING gin (sender_email gin_trgm_ops)"
    )

    op.create_table(
        "transfer_recipients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("transfer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["transfer_id"], ["transfers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_recipients_transfer", "transfer_recipients", ["transfer_id"])
    op.create_index("idx_recipients_email", "transfer_recipients", ["email"])

    op.create_table(
        "transfer_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("transfer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("safe_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("extension", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("iv", sa.LargeBinary(), nullable=False),
        sa.Column("sha256_cipher", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["transfer_id"], ["transfers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_files_transfer", "transfer_files", ["transfer_id"])

    op.create_table(
        "downloads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("transfer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("ua", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bytes_sent", sa.BigInteger(), nullable=True),
        sa.Column("aborted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["transfer_id"], ["transfers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["transfer_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_downloads_transfer", "downloads", ["transfer_id"])
    op.create_index("idx_downloads_ip_time", "downloads", ["ip", "started_at"])


def downgrade() -> None:
    op.drop_index("idx_downloads_ip_time", table_name="downloads")
    op.drop_index("idx_downloads_transfer", table_name="downloads")
    op.drop_table("downloads")

    op.drop_index("idx_files_transfer", table_name="transfer_files")
    op.drop_table("transfer_files")

    op.drop_index("idx_recipients_email", table_name="transfer_recipients")
    op.drop_index("idx_recipients_transfer", table_name="transfer_recipients")
    op.drop_table("transfer_recipients")

    op.execute("DROP INDEX IF EXISTS idx_transfers_sender_email_trgm")
    op.drop_index("idx_transfers_sender_email", table_name="transfers")
    op.drop_index("idx_transfers_sender_ip", table_name="transfers")
    op.drop_index("idx_transfers_expires_ready", table_name="transfers")
    op.drop_table("transfers")

    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS citext")
