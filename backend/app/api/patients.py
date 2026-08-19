from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Language, assert_clinic_scope, scoped_clinic_ids
from app.core import audit
from app.core.i18n import translate
from app.models.patient import Patient
from app.schemas.patient import (
    PatientCreate,
    PatientDetail,
    PatientPII,
    PatientSummary,
    PatientUpdate,
)

router = APIRouter(prefix="/patients", tags=["patients"])


def _generate_mrn() -> str:
    return f"P-{secrets.token_hex(4).upper()}"


def _detail(patient: Patient) -> PatientDetail:
    return PatientDetail(
        id=patient.id,
        mrn=patient.mrn,
        sex=patient.sex,
        age_years=patient.age_years,
        chronic_flags=list(patient.chronic_flags or []),
        dob=patient.dob,
        pii=PatientPII(**patient.get_pii()),
    )


def _load_scoped(db, user, patient_id: uuid.UUID, language: str) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    assert_clinic_scope(user, patient.clinic_id, language)
    return patient


@router.post("", response_model=PatientDetail, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate, db: DbSession, user: CurrentUser, language: Language
) -> PatientDetail:
    if user.clinic_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user is not attached to a clinic"
        )
    patient = Patient(
        id=uuid.uuid4(),
        clinic_id=user.clinic_id,
        mrn=payload.mrn or _generate_mrn(),
        dob=payload.dob,
        sex=payload.sex,
        chronic_flags=payload.chronic_flags,
        pii_blob=b"",
    )
    # set_pii binds the ciphertext to the patient id, so id must exist first.
    patient.set_pii(payload.pii.model_dump())
    db.add(patient)
    db.flush()
    audit.record(
        db,
        action="patient.created",
        entity_type="patient",
        entity_id=patient.id,
        actor_user_id=user.id,
        clinic_id=user.clinic_id,
        metadata={"mrn": patient.mrn, "sex": patient.sex.value},
    )
    return _detail(patient)


@router.get("", response_model=list[PatientSummary])
def list_patients(
    db: DbSession,
    user: CurrentUser,
    q: str | None = Query(default=None, description="MRN prefix search"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PatientSummary]:
    stmt = select(Patient)
    clinics = scoped_clinic_ids(user)
    if clinics is not None:
        stmt = stmt.where(Patient.clinic_id.in_(clinics))
    if q:
        stmt = stmt.where(Patient.mrn.ilike(f"{q}%"))
    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return [
        PatientSummary(
            id=p.id,
            mrn=p.mrn,
            sex=p.sex,
            age_years=p.age_years,
            chronic_flags=list(p.chronic_flags or []),
        )
        for p in db.execute(stmt).scalars()
    ]


@router.get("/{patient_id}", response_model=PatientDetail)
def get_patient(
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser, language: Language
) -> PatientDetail:
    patient = _load_scoped(db, user, patient_id, language)
    audit.record(
        db,
        action="patient.viewed",
        entity_type="patient",
        entity_id=patient.id,
        actor_user_id=user.id,
        clinic_id=patient.clinic_id,
        metadata={},
    )
    return _detail(patient)


@router.patch("/{patient_id}", response_model=PatientDetail)
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    db: DbSession,
    user: CurrentUser,
    language: Language,
) -> PatientDetail:
    patient = _load_scoped(db, user, patient_id, language)
    changed: list[str] = []
    if payload.pii is not None:
        patient.set_pii(payload.pii.model_dump())
        changed.append("pii")
    if payload.dob is not None:
        patient.dob = payload.dob
        changed.append("dob")
    if payload.sex is not None:
        patient.sex = payload.sex
        changed.append("sex")
    if payload.chronic_flags is not None:
        patient.chronic_flags = payload.chronic_flags
        changed.append("chronic_flags")
    db.flush()
    audit.record(
        db,
        action="patient.updated",
        entity_type="patient",
        entity_id=patient.id,
        actor_user_id=user.id,
        clinic_id=patient.clinic_id,
        metadata={"fields": changed},
    )
    return _detail(patient)
