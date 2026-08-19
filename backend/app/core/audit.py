"""Hash-chained append-only audit log.

Chain rule: ``hash = sha256(seq | occurred_at | action | entity | actor | metadata | prev_hash)``.
The first row of an installation chains from GENESIS_HASH. Verification walks
the chain in `seq` order and recomputes every hash.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

GENESIS_HASH = "0" * 64

#: Keys that must never appear in an audit metadata payload. Audit logs are
#: exported to the regulator as CSV; identifiers cannot ride along.
FORBIDDEN_METADATA_KEYS = {
    "name",
    "full_name",
    "first_name",
    "last_name",
    "patient_name",
    "passport",
    "passport_no",
    "phone",
    "phone_number",
    "address",
    "email",
    "pii",
    "pii_blob",
}


class AuditIntegrityError(RuntimeError):
    """Raised when the audit chain does not verify."""


def compute_hash(
    *,
    seq: int,
    occurred_at: datetime,
    action: str,
    entity_type: str,
    entity_id: str | None,
    actor_user_id: str | None,
    clinic_id: str | None,
    metadata: dict[str, Any],
    prev_hash: str,
) -> str:
    payload = json.dumps(
        {
            "seq": seq,
            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_user_id": actor_user_id,
            "clinic_id": clinic_id,
            "metadata": metadata,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_metadata_clean(metadata: dict[str, Any]) -> None:
    offending = {k for k in metadata if k.lower() in FORBIDDEN_METADATA_KEYS}
    if offending:
        raise ValueError(f"audit metadata may not contain identifiers: {sorted(offending)}")


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    actor_user_id: str | uuid.UUID | None = None,
    clinic_id: str | uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditLog:
    """Append one row to the chain. Never updates, never deletes."""
    metadata = metadata or {}
    _assert_metadata_clean(metadata)

    last = db.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.hash if last else GENESIS_HASH
    occurred_at = occurred_at or datetime.now(UTC)

    entity_id_s = str(entity_id) if entity_id is not None else None
    actor_s = str(actor_user_id) if actor_user_id is not None else None
    clinic_s = str(clinic_id) if clinic_id is not None else None

    row = AuditLog(
        seq=seq,
        occurred_at=occurred_at,
        actor_user_id=uuid.UUID(actor_s) if actor_s else None,
        clinic_id=uuid.UUID(clinic_s) if clinic_s else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id_s,
        metadata_json=metadata,
        prev_hash=prev_hash,
        hash=compute_hash(
            seq=seq,
            occurred_at=occurred_at,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id_s,
            actor_user_id=actor_s,
            clinic_id=clinic_s,
            metadata=metadata,
            prev_hash=prev_hash,
        ),
    )
    db.add(row)
    db.flush()
    return row


def verify_chain(db: Session, *, limit: int | None = None) -> tuple[bool, str | None]:
    """Recompute the whole chain. Returns (ok, first_bad_description)."""
    stmt = select(AuditLog).order_by(AuditLog.seq.asc())
    if limit:
        stmt = stmt.limit(limit)
    prev_hash = GENESIS_HASH
    expected_seq = 1
    for row in db.execute(stmt).scalars():
        if row.seq != expected_seq:
            return False, f"sequence gap: expected {expected_seq}, found {row.seq}"
        if row.prev_hash != prev_hash:
            return False, f"broken link at seq {row.seq}"
        recomputed = compute_hash(
            seq=row.seq,
            occurred_at=row.occurred_at,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            actor_user_id=str(row.actor_user_id) if row.actor_user_id else None,
            clinic_id=str(row.clinic_id) if row.clinic_id else None,
            metadata=row.metadata_json,
            prev_hash=row.prev_hash,
        )
        if recomputed != row.hash:
            return False, f"hash mismatch at seq {row.seq}"
        prev_hash = row.hash
        expected_seq += 1
    return True, None


def chain_length(db: Session) -> int:
    return int(db.execute(select(func.count()).select_from(AuditLog)).scalar_one())
