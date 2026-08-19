from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin
from app.models.types import GUID, JSONBType


class AuditLog(Base, UUIDMixin):
    """Append-only, hash-chained audit trail.

    Each row commits to the previous row's hash, so removing or editing any
    historical row invalidates every hash after it. `seq` is a per-installation
    monotonic counter that makes gaps detectable even if rows are deleted.
    Nothing in this table is ever updated or deleted — enforced by a database
    trigger in the Postgres migration and by the absence of any update path in
    the application.
    """

    __tablename__ = "audit_logs"

    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: Never contains direct identifiers — audit rows are exported to regulators.
    metadata_json: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
