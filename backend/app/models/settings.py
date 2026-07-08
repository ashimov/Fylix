from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        # onupdate fires on every SQL UPDATE (ORM-driven). PATCH /settings
        # and PATCH /telegram rely on DB clock here instead of Python
        # datetime.now() — avoids drift if app servers have skewed clocks
        # and prevents stale timestamps when code forgets to set it.
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"))
