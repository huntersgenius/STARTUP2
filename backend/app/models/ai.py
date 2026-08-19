from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import GUID, JSONBType


class SuggestionKind(str, enum.Enum):
    diagnosis = "diagnosis"
    treatment = "treatment"
    referral = "referral"
    risk = "risk"


class DecisionAction(str, enum.Enum):
    accept = "accept"
    edit = "edit"
    reject = "reject"


class AiSuggestion(Base, UUIDMixin, TimestampMixin):
    """One AI output, plus everything the regulator will ask about it."""

    __tablename__ = "ai_suggestions"

    consultation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[SuggestionKind] = mapped_column(
        Enum(SuggestionKind, native_enum=False, length=16), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    #: SHA-256 of the de-identified input actually sent to the model.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: True when the primary model was unavailable and we fell back locally.
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    consultation = relationship("Consultation", back_populates="suggestions")
    decision = relationship(
        "ClinicianDecision",
        back_populates="suggestion",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ClinicianDecision(Base, UUIDMixin, TimestampMixin):
    """The clinician-in-the-loop gate. No suggestion is 'used' without one."""

    __tablename__ = "clinician_decisions"

    ai_suggestion_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("ai_suggestions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[DecisionAction] = mapped_column(
        Enum(DecisionAction, native_enum=False, length=8), nullable=False
    )
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    suggestion = relationship("AiSuggestion", back_populates="decision")
