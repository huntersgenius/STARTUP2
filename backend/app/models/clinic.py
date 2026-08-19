from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ClinicType(str, enum.Enum):
    gov = "gov"
    private = "private"


class Clinic(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "clinics"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[ClinicType] = mapped_column(
        Enum(ClinicType, native_enum=False, length=16), nullable=False
    )
    #: Service tier (1 = rural feldsher point, 3 = district polyclinic).
    tier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: True when the clinic runs an edge server and expects long offline windows.
    offline_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_language: Mapped[str] = mapped_column(String(2), default="uz", nullable=False)

    users = relationship("User", back_populates="clinic", cascade="all, delete-orphan")
    patients = relationship("Patient", back_populates="clinic", cascade="all, delete-orphan")
