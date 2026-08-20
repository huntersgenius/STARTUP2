"""Offline sync.

Design rules, in priority order:

1. **Never lose a record.** Every client operation carries an `operation_id`;
   replaying it is a no-op that returns the original server id. A device may
   retry forever without creating duplicates or dropping work.
2. **Conflicts are resolved per field, not per record**, by last-write-wins on
   the client's `updated_at`. Two clinicians editing different fields of the
   same consultation both keep their edit.
3. **Every discarded value is written to `SyncMergeLog`.** Last-write-wins is
   only acceptable if the loser is recoverable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Language, assert_clinic_scope
from app.core import audit
from app.core.i18n import translate
from app.models.ai import AiSuggestion, ClinicianDecision, DecisionAction, SuggestionKind
from app.models.consultation import Consultation, ConsultationStatus
from app.models.patient import Patient
from app.models.sync import SyncMergeLog, SyncReceipt
from app.models.user import PRESCRIBING_ROLES, UserRole
from app.schemas.consultation import ConsultationCreate
from app.schemas.patient import PatientCreate

#: `offline_assessment` carries a rules-only suggestion produced on the device
#: together with the clinician's decision on it. Without it, a consultation
#: conducted with no signal would reach the server with no record that a
#: clinician ever accepted, edited or rejected the output — which breaks both
#: the audit trail and the clinician-in-the-loop guarantee.
EntityType = Literal["patient", "consultation", "offline_assessment"]

#: Fields a device is allowed to overwrite. Anything else (ids, clinic_id,
#: status transitions driven by the server) is server-owned.
CLIENT_OWNED_FIELDS: dict[str, set[str]] = {
    "patient": {"dob", "sex", "chronic_flags", "pii"},
    "consultation": {"chief_complaint", "structured_symptoms", "vitals", "status"},
}


class SyncOperation(BaseModel):
    operation_id: str = Field(min_length=8, max_length=80)
    entity_type: EntityType
    #: `create` for records made offline, `update` for edits to synced records.
    op: Literal["create", "update"]
    client_uuid: str | None = None
    server_id: uuid.UUID | None = None
    #: Client wall-clock time of the edit; drives last-write-wins.
    updated_at: datetime
    data: dict[str, Any]


class SyncRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    operations: list[SyncOperation] = Field(default_factory=list, max_length=500)


class SyncResult(BaseModel):
    operation_id: str
    status: Literal["applied", "duplicate", "conflict_merged", "rejected"]
    entity_type: EntityType
    server_id: uuid.UUID | None = None
    conflicts: list[str] = Field(default_factory=list)
    detail: str | None = None


class SyncResponse(BaseModel):
    results: list[SyncResult]
    server_time: datetime
    accepted: int
    rejected: int


router = APIRouter(prefix="/sync", tags=["sync"])


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _merge_field(
    db,
    *,
    clinic_id: uuid.UUID,
    device_id: str,
    entity_type: str,
    entity_id: uuid.UUID,
    field: str,
    server_value: Any,
    client_value: Any,
    server_updated_at: datetime,
    client_updated_at: datetime,
) -> tuple[bool, bool]:
    """Return (client_wins, was_conflict). Logs whenever a value is discarded."""
    if server_value == client_value:
        return False, False
    client_wins = _as_aware(client_updated_at) >= _as_aware(server_updated_at)
    db.add(
        SyncMergeLog(
            clinic_id=clinic_id,
            device_id=device_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            field=field,
            resolution={
                "winner": "client" if client_wins else "server",
                # PII values are never written here — only the fact that the
                # field changed. See `_summarise`.
                "server_value": _summarise(field, server_value),
                "client_value": _summarise(field, client_value),
                "server_updated_at": _as_aware(server_updated_at).isoformat(),
            },
            client_updated_at=_as_aware(client_updated_at),
        )
    )
    return client_wins, True


def _summarise(field: str, value: Any) -> Any:
    """Keep identifiers out of the merge log while staying useful for support."""
    if field == "pii":
        return "<redacted>"
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…"
    return value


@router.post("", response_model=SyncResponse)
def sync(
    payload: SyncRequest, db: DbSession, user: CurrentUser, language: Language
) -> SyncResponse:
    if user.clinic_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user is not attached to a clinic"
        )
    results: list[SyncResult] = []

    for op in payload.operations:
        existing_receipt = db.execute(
            select(SyncReceipt).where(SyncReceipt.operation_id == op.operation_id)
        ).scalar_one_or_none()
        if existing_receipt is not None:
            results.append(
                SyncResult(
                    operation_id=op.operation_id,
                    status="duplicate",
                    entity_type=op.entity_type,
                    server_id=existing_receipt.server_entity_id,
                )
            )
            continue

        try:
            result = _apply(db, payload.device_id, op, user, language)
        except HTTPException as exc:
            # One bad operation must not discard the rest of the batch.
            results.append(
                SyncResult(
                    operation_id=op.operation_id,
                    status="rejected",
                    entity_type=op.entity_type,
                    detail=str(exc.detail),
                )
            )
            continue

        db.add(
            SyncReceipt(
                clinic_id=user.clinic_id,
                device_id=payload.device_id,
                operation_id=op.operation_id,
                entity_type=op.entity_type,
                server_entity_id=result.server_id,
                user_id=user.id,
            )
        )
        db.flush()
        results.append(result)

    audit.record(
        db,
        action="sync.batch",
        entity_type="sync",
        entity_id=payload.device_id,
        actor_user_id=user.id,
        clinic_id=user.clinic_id,
        metadata={
            "operations": len(payload.operations),
            "applied": sum(1 for r in results if r.status in ("applied", "conflict_merged")),
            "duplicates": sum(1 for r in results if r.status == "duplicate"),
            "rejected": sum(1 for r in results if r.status == "rejected"),
        },
    )
    return SyncResponse(
        results=results,
        server_time=datetime.now(UTC),
        accepted=sum(1 for r in results if r.status != "rejected"),
        rejected=sum(1 for r in results if r.status == "rejected"),
    )


def _apply(db, device_id: str, op: SyncOperation, user, language: str) -> SyncResult:
    if op.entity_type == "patient":
        return _apply_patient(db, device_id, op, user, language)
    if op.entity_type == "offline_assessment":
        return _apply_offline_assessment(db, op, user, language)
    return _apply_consultation(db, device_id, op, user, language)


def _apply_offline_assessment(db, op: SyncOperation, user, language: str) -> SyncResult:
    """Record a suggestion produced on the device and the decision taken on it.

    The suggestion is stored with `degraded=True` and a model name that says
    plainly it came from the device's rule layer, so nobody reading the audit
    trail later mistakes it for a model output.
    """
    data = op.data
    consultation = _resolve_consultation(db, data, user, language)

    # The same gate the online endpoint enforces. Without this, a nurse's
    # tablet could close the clinical gate by syncing, while the same nurse is
    # refused when online — a rule that depends on connectivity is not a rule.
    if user.role not in PRESCRIBING_ROLES and user.role not in (
        UserRole.admin,
        UserRole.superadmin,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=translate("error.forbidden", language)
        )

    decision_data = data.get("decision") or {}
    action = decision_data.get("action")
    if action not in {a.value for a in DecisionAction}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown decision action {action!r}",
        )

    payload = data.get("payload") or {}
    suggestion = AiSuggestion(
        consultation_id=consultation.id,
        kind=SuggestionKind.diagnosis,
        payload=payload,
        confidence=None,
        model="offline-rules",
        prompt_version=str(data.get("prompt_version") or "device-rules"),
        input_hash=str(data.get("input_hash") or ""),
        raw_output=None,
        latency_ms=int(data.get("latency_ms") or 0),
        cost_usd=0.0,
        degraded=True,
        cache_hit=False,
    )
    db.add(suggestion)
    db.flush()

    decided_at = decision_data.get("decided_at")
    db.add(
        ClinicianDecision(
            ai_suggestion_id=suggestion.id,
            user_id=user.id,
            action=DecisionAction(action),
            final_text=decision_data.get("final_text"),
            reason=decision_data.get("reason"),
            decided_at=_as_aware(datetime.fromisoformat(decided_at))
            if decided_at
            else datetime.now(UTC),
        )
    )
    consultation.status = ConsultationStatus.completed
    db.flush()

    audit.record(
        db,
        action="ai.offline_decision",
        entity_type="ai_suggestion",
        entity_id=suggestion.id,
        actor_user_id=user.id,
        clinic_id=consultation.clinic_id,
        metadata={
            "consultation_id": str(consultation.id),
            "action": action,
            "model": "offline-rules",
            "red_flags": [f.get("code") for f in (payload.get("red_flags") or [])],
        },
    )
    return SyncResult(
        operation_id=op.operation_id,
        status="applied",
        entity_type="offline_assessment",
        server_id=suggestion.id,
    )


def _resolve_consultation(db, data: dict[str, Any], user, language: str) -> Consultation:
    """Find the consultation by server id, or by the client id it synced under."""
    consultation: Consultation | None = None
    if data.get("consultation_server_id"):
        consultation = db.get(Consultation, uuid.UUID(str(data["consultation_server_id"])))
    if consultation is None and data.get("consultation_client_uuid"):
        consultation = db.execute(
            select(Consultation).where(
                Consultation.client_uuid == str(data["consultation_client_uuid"])
            )
        ).scalar_one_or_none()
    if consultation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    assert_clinic_scope(user, consultation.clinic_id, language)
    return consultation


def _apply_patient(db, device_id: str, op: SyncOperation, user, language: str) -> SyncResult:
    if op.op == "create":
        model = PatientCreate.model_validate(op.data)
        patient = Patient(
            id=uuid.uuid4(),
            clinic_id=user.clinic_id,
            mrn=model.mrn or f"P-{uuid.uuid4().hex[:8].upper()}",
            dob=model.dob,
            sex=model.sex,
            chronic_flags=model.chronic_flags,
            pii_blob=b"",
        )
        patient.set_pii(model.pii.model_dump())
        db.add(patient)
        db.flush()
        return SyncResult(
            operation_id=op.operation_id,
            status="applied",
            entity_type="patient",
            server_id=patient.id,
        )

    stored: Patient | None = db.get(Patient, op.server_id) if op.server_id else None
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    patient = stored
    assert_clinic_scope(user, patient.clinic_id, language)

    conflicts: list[str] = []
    for field, client_value in op.data.items():
        if field not in CLIENT_OWNED_FIELDS["patient"]:
            continue
        server_value = patient.get_pii() if field == "pii" else getattr(patient, field)
        if field == "sex" and server_value is not None:
            server_value = getattr(server_value, "value", server_value)
        if field == "dob" and isinstance(server_value, date):
            server_value = server_value.isoformat()
        client_wins, conflicted = _merge_field(
            db,
            clinic_id=patient.clinic_id,
            device_id=device_id,
            entity_type="patient",
            entity_id=patient.id,
            field=field,
            server_value=server_value,
            client_value=client_value,
            server_updated_at=patient.updated_at,
            client_updated_at=op.updated_at,
        )
        if conflicted:
            conflicts.append(field)
        if client_wins:
            if field == "pii":
                patient.set_pii(client_value)
            elif field == "dob":
                patient.dob = datetime.fromisoformat(client_value).date() if client_value else None
            else:
                setattr(patient, field, client_value)
    db.flush()
    return SyncResult(
        operation_id=op.operation_id,
        status="conflict_merged" if conflicts else "applied",
        entity_type="patient",
        server_id=patient.id,
        conflicts=conflicts,
    )


def _apply_consultation(db, device_id: str, op: SyncOperation, user, language: str) -> SyncResult:
    if op.op == "create":
        model = ConsultationCreate.model_validate(op.data)
        patient = db.get(Patient, model.patient_id)
        if patient is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("error.not_found", language),
            )
        assert_clinic_scope(user, patient.clinic_id, language)

        if model.client_uuid:
            existing = db.execute(
                select(Consultation).where(
                    Consultation.client_uuid == model.client_uuid,
                    Consultation.clinic_id == patient.clinic_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return SyncResult(
                    operation_id=op.operation_id,
                    status="duplicate",
                    entity_type="consultation",
                    server_id=existing.id,
                )

        consultation = Consultation(
            patient_id=patient.id,
            user_id=user.id,
            clinic_id=patient.clinic_id,
            language=model.language,
            chief_complaint=model.chief_complaint,
            structured_symptoms=model.structured_symptoms,
            vitals=model.vitals.model_dump(exclude_none=True),
            client_uuid=model.client_uuid,
            created_offline=True,
            synced_at=datetime.now(UTC),
        )
        db.add(consultation)
        db.flush()
        return SyncResult(
            operation_id=op.operation_id,
            status="applied",
            entity_type="consultation",
            server_id=consultation.id,
        )

    stored: Consultation | None = db.get(Consultation, op.server_id) if op.server_id else None
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    consultation = stored
    assert_clinic_scope(user, consultation.clinic_id, language)

    conflicts: list[str] = []
    for field, client_value in op.data.items():
        if field not in CLIENT_OWNED_FIELDS["consultation"]:
            continue
        server_value = getattr(consultation, field)
        server_value = getattr(server_value, "value", server_value)
        client_wins, conflicted = _merge_field(
            db,
            clinic_id=consultation.clinic_id,
            device_id=device_id,
            entity_type="consultation",
            entity_id=consultation.id,
            field=field,
            server_value=server_value,
            client_value=client_value,
            server_updated_at=consultation.updated_at,
            client_updated_at=op.updated_at,
        )
        if conflicted:
            conflicts.append(field)
        if client_wins:
            setattr(consultation, field, client_value)
    consultation.synced_at = datetime.now(UTC)
    db.flush()
    return SyncResult(
        operation_id=op.operation_id,
        status="conflict_merged" if conflicts else "applied",
        entity_type="consultation",
        server_id=consultation.id,
        conflicts=conflicts,
    )
