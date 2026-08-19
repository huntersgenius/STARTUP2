from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import GUID


class UserRole(str, enum.Enum):
    doctor = "doctor"
    feldsher = "feldsher"
    nurse = "nurse"
    admin = "admin"
    superadmin = "superadmin"


#: Roles permitted to accept/edit/reject an AI suggestion. A nurse may run a
#: consultation but may not close the clinician gate on a diagnosis.
PRESCRIBING_ROLES = {UserRole.doctor, UserRole.feldsher}


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    clinic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16), nullable=False
    )
    license_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(2), default="uz", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    clinic = relationship("Clinic", back_populates="users")
