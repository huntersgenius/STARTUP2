from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core import audit
from app.models.audit import AuditLog


def test_chain_links_and_verifies(db):
    for i in range(5):
        audit.record(db, action="test.event", entity_type="thing", metadata={"i": i})
    rows = db.query(AuditLog).order_by(AuditLog.seq).all()
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0].prev_hash == audit.GENESIS_HASH
    for prev, cur in zip(rows, rows[1:], strict=False):
        assert cur.prev_hash == prev.hash
    ok, problem = audit.verify_chain(db)
    assert ok and problem is None


def test_edited_row_breaks_verification(db):
    for i in range(3):
        audit.record(db, action="test.event", entity_type="thing", metadata={"i": i})
    row = db.query(AuditLog).filter(AuditLog.seq == 2).one()
    row.metadata_json = {"i": 999}
    db.flush()
    ok, problem = audit.verify_chain(db)
    assert not ok
    assert "seq 2" in problem


def test_deleted_row_is_detected_as_a_gap(db):
    for i in range(3):
        audit.record(db, action="test.event", entity_type="thing", metadata={"i": i})
    db.query(AuditLog).filter(AuditLog.seq == 2).delete()
    db.flush()
    ok, problem = audit.verify_chain(db)
    assert not ok
    assert "gap" in problem


def test_identifiers_are_refused_in_metadata(db):
    with pytest.raises(ValueError, match="identifiers"):
        audit.record(
            db,
            action="patient.created",
            entity_type="patient",
            metadata={"full_name": "Aziza Yusupova"},
        )
    with pytest.raises(ValueError, match="identifiers"):
        audit.record(db, action="x", entity_type="y", metadata={"Passport": "AA123"})


def test_hash_depends_on_every_field():
    base = {
        "seq": 1,
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
        "action": "a",
        "entity_type": "t",
        "entity_id": "1",
        "actor_user_id": None,
        "clinic_id": None,
        "metadata": {"k": "v"},
        "prev_hash": audit.GENESIS_HASH,
    }
    reference = audit.compute_hash(**base)
    for field, mutated in [
        ("seq", 2),
        ("action", "b"),
        ("entity_type", "u"),
        ("entity_id", "2"),
        ("metadata", {"k": "w"}),
        ("prev_hash", "f" * 64),
    ]:
        assert audit.compute_hash(**{**base, field: mutated}) != reference, field
