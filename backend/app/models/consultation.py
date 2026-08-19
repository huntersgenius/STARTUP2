from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import GUID, JSONBType


class ConsultationStatus(str, enum.Enum):
    draft = "draft"
    analyzing = "analyzing"
    awaiting_decision = "awaiting_decision"
    completed = "completed"
    cancelled = "cancelled"


class Consultation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "consultations"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(2), default="uz", nullable=False)
    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    structured_symptoms: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    vitals: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    status: Mapped[ConsultationStatus] = mapped_column(
        Enum(ConsultationStatus, native_enum=False, length=24),
        default=ConsultationStatus.draft,
        nullable=False,
    )
    #: Client-generated id, unique per clinic, that makes offline sync idempotent.
    client_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: True when the consultation was created on a device with no connectivity.
    created_offline: Mapped[bool] = mapped_column(default=False, nullable=False)

    patient = relationship("Patient", back_populates="consultations")
    suggestions = relationship(
        "AiSuggestion", back_populates="consultation", cascade="all, delete-orphan"
    )
