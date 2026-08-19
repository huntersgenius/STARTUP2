from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.models.patient import Sex


class PatientPII(BaseModel):
    """Direct identifiers. Encrypted at rest, never sent to any model."""

    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    passport: str | None = None
    address: str | None = None


class PatientCreate(BaseModel):
    pii: PatientPII
    dob: date | None = None
    sex: Sex = Sex.unknown
    chronic_flags: list[str] = Field(default_factory=list)
    mrn: str | None = None
    client_uuid: str | None = None


class PatientUpdate(BaseModel):
    pii: PatientPII | None = None
    dob: date | None = None
    sex: Sex | None = None
    chronic_flags: list[str] | None = None


class PatientSummary(BaseModel):
    """List view: no identifiers, so a shoulder-surfer sees nothing useful."""

    id: uuid.UUID
    mrn: str
    sex: Sex
    age_years: int | None
    chronic_flags: list[str]

    model_config = {"from_attributes": True}


class PatientDetail(PatientSummary):
    pii: PatientPII
    dob: date | None
