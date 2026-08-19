from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, Enum, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import decrypt_blob, encrypt_blob
from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import GUID, JSONBType


class Sex(str, enum.Enum):
    male = "male"
    female = "female"
    unknown = "unknown"


class Patient(Base, UUIDMixin, TimestampMixin):
    """A patient record.

    Direct identifiers (name, passport, phone, address) live only inside
    ``pii_blob`` — AES-256-GCM encrypted, authenticated with the patient's own
    id as additional data so a blob cannot be moved between rows. Everything
    outside the blob is safe to aggregate and, once the region is dropped, to
    export for evaluation.
    """

    __tablename__ = "patients"

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pii_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Stable lookup handle shown to clinicians instead of a name in lists.
    mrn: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, native_enum=False, length=8), default=Sex.unknown, nullable=False
    )
    chronic_flags: Mapped[list[str]] = mapped_column(JSONBType, default=list, nullable=False)

    clinic = relationship("Clinic", back_populates="patients")
    consultations = relationship(
        "Consultation", back_populates="patient", cascade="all, delete-orphan"
    )

    # --- PII access is deliberately explicit -----------------------------
    def set_pii(self, data: dict[str, Any]) -> None:
        # The ciphertext is bound to the row id, so the id must exist before
        # encryption. Column defaults are applied at INSERT, which is too late
        # if a caller sets PII on a freshly constructed object — the blob would
        # then be bound to "None" and fail to decrypt after the flush.
        if self.id is None:
            self.id = uuid.uuid4()
        self.pii_blob = encrypt_blob(data, aad=str(self.id).encode())

    def get_pii(self) -> dict[str, Any]:
        return decrypt_blob(self.pii_blob, aad=str(self.id).encode())

    @property
    def age_years(self) -> int | None:
        if self.dob is None:
            return None
        today = date.today()
        return (
            today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))
        )

    @property
    def age_band(self) -> str:
        """Age band used to filter retrieval; protocols differ sharply by band."""
        age = self.age_years
        if age is None:
            return "unknown"
        if age < 1:
            return "infant"
        if age < 5:
            return "under5"
        if age < 12:
            return "child"
        if age < 18:
            return "adolescent"
        if age < 65:
            return "adult"
        return "elderly"
