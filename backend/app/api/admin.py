"""Admin and superadmin surfaces: metrics, onboarding, audit export."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Language, assert_clinic_scope, require_roles
from app.core import audit
from app.core.security import hash_password
from app.models.ai import AiSuggestion, ClinicianDecision, DecisionAction
from app.models.audit import AuditLog
from app.models.clinic import Clinic, ClinicType
from app.models.consultation import Consultation
from app.models.sync import SyncMergeLog
from app.models.user import User, UserRole
from app.schemas.auth import UserOut

router = APIRouter(prefix="/admin", tags=["admin"])

AdminOnly = Depends(require_roles(UserRole.admin, UserRole.superadmin))
SuperadminOnly = Depends(require_roles(UserRole.superadmin))


class ClinicCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    region: str = Field(min_length=2, max_length=100)
    type: ClinicType = ClinicType.gov
    tier: int = Field(default=1, ge=1, le=3)
    offline_mode: bool = False
    default_language: str = "uz"


class ClinicOut(BaseModel):
    id: uuid.UUID
    name: str
    region: str
    type: ClinicType
    tier: int
    offline_mode: bool
    default_language: str

    model_config = {"from_attributes": True}


class BulkUser(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole
    license_no: str | None = None
    password: str = Field(min_length=10, max_length=72)
    language: str = "uz"


class BulkUserRequest(BaseModel):
    clinic_id: uuid.UUID
    users: list[BulkUser] = Field(min_length=1, max_length=200)


class ClinicMetrics(BaseModel):
    clinic_id: uuid.UUID
    clinic_name: str
    consultations: int
    consultations_offline: int
    suggestions: int
    decisions: int
    #: The key product metric: how often clinicians accept AI output unedited.
    acceptance_rate: float | None
    edit_rate: float | None
    reject_rate: float | None
    #: Suggestions with no decision yet — the clinician gate is still open.
    undecided: int
    red_flags_fired: int
    total_cost_usd: float
    mean_latency_ms: float | None
    degraded_share: float | None
    sync_conflicts: int


@router.post(
    "/clinics",
    response_model=ClinicOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[SuperadminOnly],
)
def create_clinic(payload: ClinicCreate, db: DbSession, actor: CurrentUser) -> Clinic:
    clinic = Clinic(**payload.model_dump())
    db.add(clinic)
    db.flush()
    audit.record(
        db,
        action="clinic.created",
        entity_type="clinic",
        entity_id=clinic.id,
        actor_user_id=actor.id,
        clinic_id=clinic.id,
        metadata={"region": clinic.region, "tier": clinic.tier},
    )
    return clinic


@router.get("/clinics", response_model=list[ClinicOut], dependencies=[AdminOnly])
def list_clinics(db: DbSession, user: CurrentUser) -> list[Clinic]:
    stmt = select(Clinic)
    if user.role is not UserRole.superadmin:
        stmt = stmt.where(Clinic.id == user.clinic_id)
    return list(db.execute(stmt.order_by(Clinic.name)).scalars())


@router.post(
    "/users/bulk",
    response_model=list[UserOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[AdminOnly],
)
def bulk_create_users(
    payload: BulkUserRequest, db: DbSession, actor: CurrentUser, language: Language
) -> list[User]:
    assert_clinic_scope(actor, payload.clinic_id, language)
    if db.get(Clinic, payload.clinic_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="clinic not found")

    emails = [u.email.lower().strip() for u in payload.users]
    if len(set(emails)) != len(emails):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate emails in batch"
        )
    taken = db.execute(select(User.email).where(User.email.in_(emails))).scalars().all()
    if taken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"already registered: {sorted(taken)}"
        )

    created: list[User] = []
    for item in payload.users:
        if actor.role is UserRole.admin and item.role is UserRole.superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="admins cannot create superadmins"
            )
        user = User(
            email=item.email.lower().strip(),
            full_name=item.full_name,
            hashed_password=hash_password(item.password),
            role=item.role,
            clinic_id=payload.clinic_id,
            license_no=item.license_no,
            language=item.language,
        )
        db.add(user)
        created.append(user)
    db.flush()
    audit.record(
        db,
        action="user.bulk_created",
        entity_type="clinic",
        entity_id=payload.clinic_id,
        actor_user_id=actor.id,
        clinic_id=payload.clinic_id,
        metadata={"count": len(created), "roles": sorted({u.role.value for u in created})},
    )
    return created


@router.get("/metrics", response_model=list[ClinicMetrics], dependencies=[AdminOnly])
def clinic_metrics(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
) -> list[ClinicMetrics]:
    since = datetime.now(UTC) - timedelta(days=days)
    clinics = list(
        db.execute(
            select(Clinic)
            if user.role is UserRole.superadmin
            else select(Clinic).where(Clinic.id == user.clinic_id)
        ).scalars()
    )

    out: list[ClinicMetrics] = []
    for clinic in clinics:
        consult_rows = list(
            db.execute(
                select(Consultation).where(
                    Consultation.clinic_id == clinic.id, Consultation.created_at >= since
                )
            ).scalars()
        )
        consult_ids = [c.id for c in consult_rows]
        suggestions = (
            list(
                db.execute(
                    select(AiSuggestion).where(AiSuggestion.consultation_id.in_(consult_ids))
                ).scalars()
            )
            if consult_ids
            else []
        )
        suggestion_ids = [s.id for s in suggestions]
        decisions = (
            list(
                db.execute(
                    select(ClinicianDecision).where(
                        ClinicianDecision.ai_suggestion_id.in_(suggestion_ids)
                    )
                ).scalars()
            )
            if suggestion_ids
            else []
        )
        decided = len(decisions)
        counts = {action: 0 for action in DecisionAction}
        for d in decisions:
            counts[d.action] += 1

        red_flags = sum(1 for s in suggestions if (s.payload or {}).get("red_flags"))
        conflicts = int(
            db.execute(
                select(func.count())
                .select_from(SyncMergeLog)
                .where(SyncMergeLog.clinic_id == clinic.id, SyncMergeLog.created_at >= since)
            ).scalar_one()
        )
        out.append(
            ClinicMetrics(
                clinic_id=clinic.id,
                clinic_name=clinic.name,
                consultations=len(consult_rows),
                consultations_offline=sum(1 for c in consult_rows if c.created_offline),
                suggestions=len(suggestions),
                decisions=decided,
                acceptance_rate=(counts[DecisionAction.accept] / decided) if decided else None,
                edit_rate=(counts[DecisionAction.edit] / decided) if decided else None,
                reject_rate=(counts[DecisionAction.reject] / decided) if decided else None,
                undecided=len(suggestions) - decided,
                red_flags_fired=red_flags,
                total_cost_usd=round(sum(s.cost_usd for s in suggestions), 6),
                mean_latency_ms=(
                    sum(s.latency_ms for s in suggestions) / len(suggestions)
                    if suggestions
                    else None
                ),
                degraded_share=(
                    sum(1 for s in suggestions if s.degraded) / len(suggestions)
                    if suggestions
                    else None
                ),
                sync_conflicts=conflicts,
            )
        )
    return out


@router.get("/audit/verify", dependencies=[AdminOnly])
def verify_audit(db: DbSession) -> dict:
    ok, problem = audit.verify_chain(db)
    return {"ok": ok, "entries": audit.chain_length(db), "problem": problem}


@router.get("/audit/export", dependencies=[AdminOnly])
def export_audit(
    db: DbSession,
    user: CurrentUser,
    since: datetime | None = None,
    until: datetime | None = None,
) -> StreamingResponse:
    """CSV export for the regulatory sandbox application.

    The export deliberately carries no direct identifiers — audit metadata is
    validated against a denylist at write time (`app/core/audit.py`).
    """
    stmt = select(AuditLog).order_by(AuditLog.seq.asc())
    if user.role is not UserRole.superadmin:
        stmt = stmt.where(AuditLog.clinic_id == user.clinic_id)
    if since:
        stmt = stmt.where(AuditLog.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditLog.occurred_at <= until)
    rows = list(db.execute(stmt).scalars())

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "seq",
            "occurred_at",
            "action",
            "entity_type",
            "entity_id",
            "actor_user_id",
            "clinic_id",
            "metadata",
            "prev_hash",
            "hash",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.seq,
                row.occurred_at.isoformat(),
                row.action,
                row.entity_type,
                row.entity_id or "",
                row.actor_user_id or "",
                row.clinic_id or "",
                row.metadata_json,
                row.prev_hash,
                row.hash,
            ]
        )
    buffer.seek(0)
    audit.record(
        db,
        action="audit.exported",
        entity_type="audit",
        actor_user_id=user.id,
        clinic_id=user.clinic_id,
        metadata={"rows": len(rows)},
    )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sihhatai-audit.csv"'},
    )
