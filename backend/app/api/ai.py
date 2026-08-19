"""AI endpoints.

Two endpoints, and the second is not optional: `/analyze` produces a
suggestion, `/decision` records what the clinician did with it. A suggestion
without a decision is an open gate, and the admin dashboard reports those as
`undecided` precisely so they cannot be ignored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai.engine import DiagnosticEngine
from app.api.consultations import load_scoped_consultation
from app.api.deps import CurrentUser, DbSession, Language, assert_clinic_scope
from app.core import audit, metrics
from app.core.i18n import translate
from app.models.ai import AiSuggestion, ClinicianDecision, DecisionAction, SuggestionKind
from app.models.clinic import Clinic
from app.models.consultation import Consultation, ConsultationStatus
from app.models.patient import Patient
from app.models.user import PRESCRIBING_ROLES

router = APIRouter(tags=["ai"])


class AnalyzeRequest(BaseModel):
    #: The client tells us it is working offline; the engine routes locally.
    offline: bool = False


class AnalyzeResponse(BaseModel):
    suggestion_id: uuid.UUID
    consultation_id: uuid.UUID
    payload: dict
    model: str
    prompt_version: str
    latency_ms: int
    cost_usd: float
    degraded: bool
    cache_hit: bool
    #: Always true. A client that renders a suggestion without the gate is
    #: non-compliant, and this field is how that is made explicit in the API.
    requires_clinician_review: bool = True
    disclaimer: str


class DecisionRequest(BaseModel):
    action: DecisionAction
    #: What the clinician actually settled on, after editing.
    final_text: str | None = Field(default=None, max_length=8000)
    reason: str | None = Field(default=None, max_length=2000)


class DecisionResponse(BaseModel):
    id: uuid.UUID
    ai_suggestion_id: uuid.UUID
    action: DecisionAction
    decided_at: datetime
    consultation_status: ConsultationStatus


@router.post("/consultations/{consultation_id}/analyze", response_model=AnalyzeResponse)
def analyze(
    consultation_id: uuid.UUID,
    payload: AnalyzeRequest,
    db: DbSession,
    user: CurrentUser,
    language: Language,
) -> AnalyzeResponse:
    consultation = load_scoped_consultation(db, user, consultation_id, language)
    patient = db.get(Patient, consultation.patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    clinic = db.get(Clinic, consultation.clinic_id)

    consultation.status = ConsultationStatus.analyzing
    db.flush()

    engine = DiagnosticEngine(db)
    result = engine.analyze(
        consultation,
        patient,
        clinic_tier=clinic.tier if clinic else 1,
        clinic_offline_mode=bool(clinic and clinic.offline_mode),
        offline=payload.offline,
    )

    suggestion = AiSuggestion(
        consultation_id=consultation.id,
        kind=SuggestionKind.diagnosis,
        payload=result.suggestion.model_dump(mode="json"),
        confidence=result.suggestion.top_confidence,
        model=result.model,
        prompt_version=result.prompt_version,
        input_hash=result.input_hash,
        raw_output=result.raw_output,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        degraded=result.degraded,
        cache_hit=result.cache_hit,
    )
    db.add(suggestion)
    consultation.status = ConsultationStatus.awaiting_decision
    db.flush()

    audit.record(
        db,
        action="ai.analyzed",
        entity_type="ai_suggestion",
        entity_id=suggestion.id,
        actor_user_id=user.id,
        clinic_id=consultation.clinic_id,
        metadata={
            "consultation_id": str(consultation.id),
            "model": result.model,
            "prompt_version": result.prompt_version,
            "input_hash": result.input_hash,
            "latency_ms": result.latency_ms,
            "cost_usd": result.cost_usd,
            "degraded": result.degraded,
            "cache_hit": result.cache_hit,
            "red_flags": [f.code for f in result.suggestion.red_flags],
            "differential_count": len(result.suggestion.differentials),
            "trace": result.trace,
        },
    )
    metrics.inc("sihhatai_analyses_total", {"degraded": str(result.degraded).lower()})
    metrics.observe("sihhatai_analysis_cost_usd", result.cost_usd)
    metrics.observe("sihhatai_analysis_latency_seconds", result.latency_ms / 1000)

    return AnalyzeResponse(
        suggestion_id=suggestion.id,
        consultation_id=consultation.id,
        payload=suggestion.payload,
        model=result.model,
        prompt_version=result.prompt_version,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        degraded=result.degraded,
        cache_hit=result.cache_hit,
        disclaimer=translate("disclaimer.long", language),
    )


@router.post("/suggestions/{suggestion_id}/decision", response_model=DecisionResponse)
def record_decision(
    suggestion_id: uuid.UUID,
    payload: DecisionRequest,
    db: DbSession,
    user: CurrentUser,
    language: Language,
) -> DecisionResponse:
    suggestion = db.get(AiSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("error.not_found", language)
        )
    consultation = db.get(Consultation, suggestion.consultation_id)
    assert_clinic_scope(user, consultation.clinic_id if consultation else None, language)

    if user.role not in PRESCRIBING_ROLES and user.role.value not in ("admin", "superadmin"):
        # A nurse may run a consultation but may not close the clinical gate.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=translate("error.forbidden", language)
        )
    if payload.action is DecisionAction.edit and not (payload.final_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="final_text is required when the action is 'edit'",
        )
    if payload.action is DecisionAction.reject and not (payload.reason or "").strip():
        # A rejection without a reason teaches the model nothing.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reason is required when the action is 'reject'",
        )

    existing = db.execute(
        select(ClinicianDecision).where(ClinicianDecision.ai_suggestion_id == suggestion.id)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="a decision has already been recorded"
        )

    decision = ClinicianDecision(
        ai_suggestion_id=suggestion.id,
        user_id=user.id,
        action=payload.action,
        final_text=payload.final_text,
        reason=payload.reason,
        decided_at=datetime.now(UTC),
    )
    db.add(decision)
    if consultation is not None:
        consultation.status = ConsultationStatus.completed
    db.flush()

    audit.record(
        db,
        action="ai.decision",
        entity_type="clinician_decision",
        entity_id=decision.id,
        actor_user_id=user.id,
        clinic_id=consultation.clinic_id if consultation else None,
        metadata={
            "ai_suggestion_id": str(suggestion.id),
            "action": payload.action.value,
            "model": suggestion.model,
            "prompt_version": suggestion.prompt_version,
            "had_red_flags": bool((suggestion.payload or {}).get("red_flags")),
        },
    )
    metrics.inc("sihhatai_decisions_total", {"action": payload.action.value})

    return DecisionResponse(
        id=decision.id,
        ai_suggestion_id=suggestion.id,
        action=decision.action,
        decided_at=decision.decided_at,
        consultation_status=consultation.status if consultation else ConsultationStatus.completed,
    )


@router.get("/consultations/{consultation_id}/suggestions")
def list_suggestions(
    consultation_id: uuid.UUID, db: DbSession, user: CurrentUser, language: Language
) -> list[dict]:
    consultation = load_scoped_consultation(db, user, consultation_id, language)
    rows = db.execute(
        select(AiSuggestion)
        .where(AiSuggestion.consultation_id == consultation.id)
        .order_by(AiSuggestion.created_at.desc())
    ).scalars()
    return [
        {
            "id": str(row.id),
            "kind": row.kind.value,
            "payload": row.payload,
            "confidence": row.confidence,
            "model": row.model,
            "prompt_version": row.prompt_version,
            "latency_ms": row.latency_ms,
            "cost_usd": row.cost_usd,
            "degraded": row.degraded,
            "cache_hit": row.cache_hit,
            "decision": (
                {
                    "action": row.decision.action.value,
                    "decided_at": row.decision.decided_at.isoformat(),
                    "final_text": row.decision.final_text,
                    "reason": row.decision.reason,
                }
                if row.decision
                else None
            ),
            "requires_clinician_review": row.decision is None,
        }
        for row in rows
    ]
