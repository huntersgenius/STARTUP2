from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.consultation import ConsultationStatus


class Vitals(BaseModel):
    """Vitals as a feldsher records them. All optional; none are invented."""

    temperature_c: float | None = Field(default=None, ge=25, le=45)
    pulse_bpm: int | None = Field(default=None, ge=20, le=250)
    systolic_bp: int | None = Field(default=None, ge=50, le=300)
    diastolic_bp: int | None = Field(default=None, ge=20, le=200)
    respiratory_rate: int | None = Field(default=None, ge=4, le=90)
    spo2: int | None = Field(default=None, ge=40, le=100)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    glucose_mmol: float | None = Field(default=None, ge=0.5, le=60)


class ConsultationCreate(BaseModel):
    patient_id: uuid.UUID
    language: str = "uz"
    chief_complaint: str = Field(min_length=2, max_length=4000)
    structured_symptoms: dict = Field(default_factory=dict)
    vitals: Vitals = Field(default_factory=Vitals)
    client_uuid: str | None = None
    created_offline: bool = False

    @field_validator("language")
    @classmethod
    def _supported(cls, v: str) -> str:
        if v not in ("uz", "ru", "en"):
            raise ValueError("language must be one of uz, ru, en")
        return v


class ConsultationUpdate(BaseModel):
    chief_complaint: str | None = None
    structured_symptoms: dict | None = None
    vitals: Vitals | None = None
    status: ConsultationStatus | None = None


class ConsultationOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    user_id: uuid.UUID
    clinic_id: uuid.UUID
    language: str
    chief_complaint: str
    structured_symptoms: dict
    vitals: dict
    status: ConsultationStatus
    created_at: datetime
    synced_at: datetime | None
    created_offline: bool

    model_config = {"from_attributes": True}
