from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Language, assert_clinic_scope, scoped_clinic_ids
from app.core import audit
from app.core.i18n import translate
from app.models.consultation import Consultation, ConsultationStatus
from app.models.patient import Patient
from app.schemas.consultation import ConsultationCreate, ConsultationOut, ConsultationUpdate

router = APIRouter(prefix="/consultations", tags=["consultations"])


def load_scoped_consultation(db, user, consultation_id: uuid.UUID, language: str) -> Consultation:
    consultation = db.get(Consultation, consultation_id)
    if consultation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    assert_clinic_scope(user, consultation.clinic_id, language)
    return consultation


@router.post("", response_model=ConsultationOut, status_code=status.HTTP_201_CREATED)
def create_consultation(
    payload: ConsultationCreate, db: DbSession, user: CurrentUser, language: Language
) -> Consultation:
    patient = db.get(Patient, payload.patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    assert_clinic_scope(user, patient.clinic_id, language)

    # Offline clients replay their outbox; the same client_uuid must not
    # create a second consultation.
    if payload.client_uuid:
        existing = db.execute(
            select(Consultation).where(
                Consultation.client_uuid == payload.client_uuid,
                Consultation.clinic_id == patient.clinic_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    consultation = Consultation(
        patient_id=patient.id,
        user_id=user.id,
        clinic_id=patient.clinic_id,
        language=payload.language,
        chief_complaint=payload.chief_complaint,
        structured_symptoms=payload.structured_symptoms,
        vitals=payload.vitals.model_dump(exclude_none=True),
        status=ConsultationStatus.draft,
        client_uuid=payload.client_uuid,
        created_offline=payload.created_offline,
    )
    db.add(consultation)
    db.flush()
    audit.record(
        db,
        action="consultation.created",
        entity_type="consultation",
        entity_id=consultation.id,
        actor_user_id=user.id,
        clinic_id=consultation.clinic_id,
        metadata={"language": consultation.language, "offline": consultation.created_offline},
    )
    return consultation


@router.get("", response_model=list[ConsultationOut])
def list_consultations(
    db: DbSession,
    user: CurrentUser,
    patient_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Consultation]:
    stmt = select(Consultation)
    clinics = scoped_clinic_ids(user)
    if clinics is not None:
        stmt = stmt.where(Consultation.clinic_id.in_(clinics))
    if patient_id:
        stmt = stmt.where(Consultation.patient_id == patient_id)
    stmt = stmt.order_by(Consultation.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


@router.get("/{consultation_id}", response_model=ConsultationOut)
def get_consultation(
    consultation_id: uuid.UUID, db: DbSession, user: CurrentUser, language: Language
) -> Consultation:
    return load_scoped_consultation(db, user, consultation_id, language)


@router.patch("/{consultation_id}", response_model=ConsultationOut)
def update_consultation(
    consultation_id: uuid.UUID,
    payload: ConsultationUpdate,
    db: DbSession,
    user: CurrentUser,
    language: Language,
) -> Consultation:
    consultation = load_scoped_consultation(db, user, consultation_id, language)
    if consultation.status is ConsultationStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="completed consultations are immutable"
        )
    changed: list[str] = []
    if payload.chief_complaint is not None:
        consultation.chief_complaint = payload.chief_complaint
        changed.append("chief_complaint")
    if payload.structured_symptoms is not None:
        consultation.structured_symptoms = payload.structured_symptoms
        changed.append("structured_symptoms")
    if payload.vitals is not None:
        consultation.vitals = payload.vitals.model_dump(exclude_none=True)
        changed.append("vitals")
    if payload.status is not None:
        consultation.status = payload.status
        changed.append("status")
    db.flush()
    audit.record(
        db,
        action="consultation.updated",
        entity_type="consultation",
        entity_id=consultation.id,
        actor_user_id=user.id,
        clinic_id=consultation.clinic_id,
        metadata={"fields": changed},
    )
    return consultation
