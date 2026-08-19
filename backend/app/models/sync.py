from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import GUID, JSONBType


class SyncMergeLog(Base, UUIDMixin, TimestampMixin):
    """Every field-level conflict resolved during offline sync.

    Last-write-wins silently discards data unless you write down what it
    discarded. This table is that record; the admin dashboard surfaces it.
    """

    __tablename__ = "sync_merge_logs"

    clinic_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(80), nullable=False)
    #: What the server held, what the device sent, and which one survived.
    resolution: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    client_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SyncReceipt(Base, UUIDMixin, TimestampMixin):
    """Idempotency record: one row per accepted client operation."""

    __tablename__ = "sync_receipts"

    clinic_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Client-generated operation id. Replaying it must not duplicate work.
    operation_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    server_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
