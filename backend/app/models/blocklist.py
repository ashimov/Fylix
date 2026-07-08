from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BlocklistIP(Base):
    __tablename__ = "blocklist_ips"

    cidr: Mapped[str] = mapped_column(INET, primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BlocklistEmailDomain(Base):
    __tablename__ = "blocklist_email_domains"

    domain: Mapped[str] = mapped_column(CITEXT, primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BlocklistEmail(Base):
    __tablename__ = "blocklist_emails"

    email: Mapped[str] = mapped_column(CITEXT, primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
