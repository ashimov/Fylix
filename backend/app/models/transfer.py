from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

TRANSFER_STATUSES = ("uploading", "ready", "expired", "deleted", "infected", "revoked")
# Canonical SQL literal for the CHECK constraint — MUST match the string
# hard-coded in alembic/versions/0001_core_tables.py byte-for-byte, or
# `alembic --autogenerate` will flag a phantom drift on every run.
TRANSFER_STATUSES_SQL_IN = "(" + ",".join(f"'{s}'" for s in TRANSFER_STATUSES) + ")"


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    manage_token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    sender_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    sender_ip: Mapped[str] = mapped_column(INET, nullable=False)
    sender_country: Mapped[str | None] = mapped_column(String(2))
    sender_city: Mapped[str | None] = mapped_column(Text)
    sender_ua: Mapped[str | None] = mapped_column(Text)

    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary)

    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    infected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    recipients: Mapped[list["TransferRecipient"]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan"
    )
    files: Mapped[list["TransferFile"]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan"
    )
    downloads: Mapped[list["Download"]] = relationship(back_populates="transfer")

    __table_args__ = (
        CheckConstraint(f"status IN {TRANSFER_STATUSES_SQL_IN}", name="transfers_status_check"),
        CheckConstraint("char_length(message) <= 2000", name="transfers_message_len"),
        Index("idx_transfers_expires_ready", "expires_at", postgresql_where="status='ready'"),
        Index("idx_transfers_sender_ip", "sender_ip"),
        Index("idx_transfers_sender_email", "sender_email"),
        # Partial index on 'ready' + 'infected' — feeds the _kpi aggregate.
        Index(
            "idx_transfers_status_active",
            "status",
            postgresql_where="status IN ('ready', 'infected')",
        ),
    )


class TransferRecipient(Base):
    __tablename__ = "transfer_recipients"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    transfer_id: Mapped[UUID] = mapped_column(
        ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(Text)

    transfer: Mapped[Transfer] = relationship(back_populates="recipients")

    __table_args__ = (
        Index("idx_recipients_transfer", "transfer_id"),
        Index("idx_recipients_email", "email"),
    )


class TransferFile(Base):
    __tablename__ = "transfer_files"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    transfer_id: Mapped[UUID] = mapped_column(
        ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    safe_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    transfer: Mapped[Transfer] = relationship(back_populates="files")

    __table_args__ = (
        Index("idx_files_transfer", "transfer_id"),
        # GIN trigram index — feeds admin_list_transfers ILIKE search on
        # filename. Matches the idx_transfers_sender_email_trgm pattern.
        Index(
            "idx_transfer_files_filename_trgm",
            "filename",
            postgresql_using="gin",
            postgresql_ops={"filename": "gin_trgm_ops"},
        ),
    )


class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    transfer_id: Mapped[UUID] = mapped_column(
        ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("transfer_files.id", ondelete="SET NULL")
    )
    ip: Mapped[str] = mapped_column(INET, nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(Text)
    ua: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bytes_sent: Mapped[int | None] = mapped_column(BigInteger)
    aborted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        # server_default matches the 0001 migration literal; if a future
        # raw-SQL INSERT path bypasses the ORM default, Postgres still
        # populates the column correctly.
        server_default=text("false"),
        default=False,
    )

    transfer: Mapped[Transfer] = relationship(back_populates="downloads")

    __table_args__ = (
        Index("idx_downloads_transfer", "transfer_id"),
        Index("idx_downloads_ip_time", "ip", "started_at"),
    )
