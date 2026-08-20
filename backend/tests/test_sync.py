"""Offline sync. The governing requirement: never lose a patient record."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.consultation import Consultation
from app.models.sync import SyncMergeLog


def _op(entity_type: str, op: str, data: dict, **kw) -> dict:
    return {
        "operation_id": kw.pop("operation_id", uuid.uuid4().hex),
        "entity_type": entity_type,
        "op": op,
        "updated_at": kw.pop("updated_at", datetime.now(UTC)).isoformat(),
        "data": data,
        **kw,
    }


def test_offline_consultation_reaches_the_server(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="feldsher@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("feldsher@sihhat.uz")

    response = client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-01",
            "operations": [
                _op(
                    "consultation",
                    "create",
                    {
                        "patient_id": str(patient.id),
                        "chief_complaint": "3 kundan beri yo'tal va isitma",
                        "language": "uz",
                        "client_uuid": "c-local-1",
                        "vitals": {"temperature_c": 38.4},
                    },
                )
            ],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "applied"

    stored = db.get(Consultation, uuid.UUID(result["server_id"]))
    assert stored.chief_complaint.startswith("3 kundan")
    assert stored.created_offline is True
    assert stored.synced_at is not None


def test_replaying_the_same_operation_creates_nothing_new(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="feldsher2@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("feldsher2@sihhat.uz")
    operation = _op(
        "consultation",
        "create",
        {"patient_id": str(patient.id), "chief_complaint": "bosh og'rig'i", "client_uuid": "c-2"},
    )
    body = {"device_id": "tablet-01", "operations": [operation]}

    first = client.post("/api/v1/sync", headers=headers, json=body).json()["results"][0]
    second = client.post("/api/v1/sync", headers=headers, json=body).json()["results"][0]

    assert first["status"] == "applied"
    assert second["status"] == "duplicate"
    assert second["server_id"] == first["server_id"]
    assert db.query(Consultation).count() == 1


def test_one_bad_operation_does_not_discard_the_batch(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="feldsher3@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("feldsher3@sihhat.uz")

    response = client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-01",
            "operations": [
                _op(
                    "consultation",
                    "create",
                    {"patient_id": str(uuid.uuid4()), "chief_complaint": "orphan"},
                ),
                _op(
                    "consultation",
                    "create",
                    {"patient_id": str(patient.id), "chief_complaint": "valid one"},
                ),
            ],
        },
    )
    assert response.status_code == 200
    statuses = [r["status"] for r in response.json()["results"]]
    assert statuses == ["rejected", "applied"]
    assert db.query(Consultation).count() == 1


def test_field_level_merge_keeps_both_edits(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="feldsher4@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("feldsher4@sihhat.uz")

    created = client.post(
        "/api/v1/consultations",
        headers=headers,
        json={
            "patient_id": str(patient.id),
            "chief_complaint": "server text",
            "vitals": {"pulse_bpm": 80},
        },
    ).json()

    future = datetime.now(UTC) + timedelta(minutes=5)
    response = client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-02",
            "operations": [
                _op(
                    "consultation",
                    "update",
                    {"chief_complaint": "device text"},
                    server_id=created["id"],
                    updated_at=future,
                )
            ],
        },
    )
    result = response.json()["results"][0]
    assert result["status"] == "conflict_merged"
    assert result["conflicts"] == ["chief_complaint"]

    stored = db.get(Consultation, uuid.UUID(created["id"]))
    assert stored.chief_complaint == "device text"
    # The field the device did not touch is untouched.
    assert stored.vitals["pulse_bpm"] == 80


def test_stale_device_edit_loses_but_is_recorded(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="feldsher5@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("feldsher5@sihhat.uz")
    created = client.post(
        "/api/v1/consultations",
        headers=headers,
        json={"patient_id": str(patient.id), "chief_complaint": "server wins"},
    ).json()

    stale = datetime.now(UTC) - timedelta(days=2)
    client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-03",
            "operations": [
                _op(
                    "consultation",
                    "update",
                    {"chief_complaint": "stale device text"},
                    server_id=created["id"],
                    updated_at=stale,
                )
            ],
        },
    )
    stored = db.get(Consultation, uuid.UUID(created["id"]))
    assert stored.chief_complaint == "server wins"

    # Last-write-wins is only acceptable because the loser is recoverable.
    log = db.query(SyncMergeLog).one()
    assert log.field == "chief_complaint"
    assert log.resolution["winner"] == "server"
    assert log.resolution["client_value"] == "stale device text"


def test_merge_log_never_stores_identifiers(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="feldsher6@sihhat.uz")
    patient = patient_factory(clinic, name="Server Name")
    headers = auth_headers("feldsher6@sihhat.uz")

    client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-04",
            "operations": [
                _op(
                    "patient",
                    "update",
                    {"pii": {"full_name": "Device Name", "phone": "+998900000000"}},
                    server_id=str(patient.id),
                    updated_at=datetime.now(UTC) + timedelta(minutes=1),
                )
            ],
        },
    )
    logs = db.query(SyncMergeLog).all()
    assert logs and logs[0].field == "pii"
    serialised = str([log.resolution for log in logs])
    assert "Device Name" not in serialised
    assert "Server Name" not in serialised
    assert "<redacted>" in serialised
    # The edit itself still applied.
    db.refresh(patient)
    assert patient.get_pii()["full_name"] == "Device Name"


def test_device_cannot_sync_into_another_clinic(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="feldsher7@sihhat.uz")
    patient_b = patient_factory(clinic_b)

    response = client.post(
        "/api/v1/sync",
        headers=auth_headers("feldsher7@sihhat.uz"),
        json={
            "device_id": "tablet-05",
            "operations": [
                _op(
                    "consultation",
                    "create",
                    {"patient_id": str(patient_b.id), "chief_complaint": "yo'tal"},
                )
            ],
        },
    )
    assert response.json()["results"][0]["status"] == "rejected"
    assert db.query(Consultation).count() == 0


def test_server_owned_fields_cannot_be_overwritten_by_a_device(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="feldsher8@sihhat.uz")
    patient = patient_factory(clinic_a)
    headers = auth_headers("feldsher8@sihhat.uz")
    created = client.post(
        "/api/v1/consultations",
        headers=headers,
        json={"patient_id": str(patient.id), "chief_complaint": "yo'tal"},
    ).json()

    client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-06",
            "operations": [
                _op(
                    "consultation",
                    "update",
                    {"clinic_id": str(clinic_b.id), "patient_id": str(uuid.uuid4())},
                    server_id=created["id"],
                    updated_at=datetime.now(UTC) + timedelta(hours=1),
                )
            ],
        },
    )
    stored = db.get(Consultation, uuid.UUID(created["id"]))
    assert stored.clinic_id == clinic_a.id
    assert stored.patient_id == patient.id


def test_offline_decision_is_not_lost(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    """A decision taken with no signal must still reach the audit trail.

    Found in review: the app produced a rules-only suggestion offline, the
    clinician accepted or rejected it, and nothing was recorded anywhere —
    the consultation arrived at the server with no evidence a human had ever
    looked at the output.
    """
    from app.models.ai import AiSuggestion, ClinicianDecision
    from app.models.audit import AuditLog

    clinic = clinic_factory()
    user_factory(clinic, email="offline-doc@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("offline-doc@sihhat.uz")

    # The device syncs the consultation and the decision it took on it.
    created = client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-offline",
            "operations": [
                _op(
                    "consultation",
                    "create",
                    {
                        "patient_id": str(patient.id),
                        "chief_complaint": "ko'krak og'rig'i va nafas qisishi",
                        "language": "uz",
                        "client_uuid": "c-offline-1",
                    },
                )
            ],
        },
    ).json()["results"][0]
    assert created["status"] == "applied"

    synced = client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "tablet-offline",
            "operations": [
                _op(
                    "offline_assessment",
                    "create",
                    {
                        "consultation_client_uuid": "c-offline-1",
                        "payload": {
                            "red_flags": [
                                {
                                    "code": "acs_suspected",
                                    "urgency": "immediate",
                                    "message": "Yurak xurujii shubhasi",
                                    "refer_to": "emergency_cardiology",
                                }
                            ],
                            "insufficient_data": True,
                        },
                        "decision": {
                            "action": "accept",
                            "decided_at": datetime.now(UTC).isoformat(),
                        },
                    },
                )
            ],
        },
    ).json()["results"][0]

    assert synced["status"] == "applied"
    suggestion = db.query(AiSuggestion).one()
    # Labelled honestly: a rules-only device output, never passed off as a model.
    assert suggestion.model == "offline-rules"
    assert suggestion.degraded is True

    decision = db.query(ClinicianDecision).one()
    assert decision.action.value == "accept"
    assert decision.ai_suggestion_id == suggestion.id

    actions = [row.action for row in db.query(AuditLog).all()]
    assert "ai.offline_decision" in actions


def test_offline_assessment_for_an_unknown_consultation_is_rejected(
    client, clinic_factory, user_factory, auth_headers, db
):
    from app.models.ai import AiSuggestion

    clinic = clinic_factory()
    user_factory(clinic, email="offline-doc2@sihhat.uz")
    response = client.post(
        "/api/v1/sync",
        headers=auth_headers("offline-doc2@sihhat.uz"),
        json={
            "device_id": "tablet-offline",
            "operations": [
                _op(
                    "offline_assessment",
                    "create",
                    {
                        "consultation_client_uuid": "does-not-exist",
                        "payload": {},
                        "decision": {"action": "accept"},
                    },
                )
            ],
        },
    )
    assert response.json()["results"][0]["status"] == "rejected"
    assert db.query(AiSuggestion).count() == 0


def test_offline_assessment_with_a_bad_action_is_rejected(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    from app.models.ai import AiSuggestion

    clinic = clinic_factory()
    user_factory(clinic, email="offline-doc3@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("offline-doc3@sihhat.uz")
    client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "t",
            "operations": [
                _op(
                    "consultation",
                    "create",
                    {
                        "patient_id": str(patient.id),
                        "chief_complaint": "yo'tal",
                        "client_uuid": "c-offline-2",
                    },
                )
            ],
        },
    )
    response = client.post(
        "/api/v1/sync",
        headers=headers,
        json={
            "device_id": "t",
            "operations": [
                _op(
                    "offline_assessment",
                    "create",
                    {
                        "consultation_client_uuid": "c-offline-2",
                        "payload": {},
                        "decision": {"action": "rubber-stamp"},
                    },
                )
            ],
        },
    )
    assert response.json()["results"][0]["status"] == "rejected"
    assert db.query(AiSuggestion).count() == 0


def test_a_nurse_cannot_close_the_clinical_gate_by_syncing(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    """The gate must not depend on connectivity.

    Found in review: `/suggestions/{id}/decision` refuses a nurse, but the
    sync path did not — so the same nurse could record a decision simply by
    being offline when they made it.
    """
    from app.models.ai import AiSuggestion
    from app.models.user import UserRole

    clinic = clinic_factory()
    user_factory(clinic, email="doc-gate@sihhat.uz")
    user_factory(clinic, email="nurse-gate@sihhat.uz", role=UserRole.nurse)
    patient = patient_factory(clinic)

    client.post(
        "/api/v1/sync",
        headers=auth_headers("doc-gate@sihhat.uz"),
        json={
            "device_id": "t",
            "operations": [
                _op(
                    "consultation",
                    "create",
                    {
                        "patient_id": str(patient.id),
                        "chief_complaint": "yo'tal",
                        "client_uuid": "c-gate-1",
                    },
                )
            ],
        },
    )

    refused = client.post(
        "/api/v1/sync",
        headers=auth_headers("nurse-gate@sihhat.uz"),
        json={
            "device_id": "t",
            "operations": [
                _op(
                    "offline_assessment",
                    "create",
                    {
                        "consultation_client_uuid": "c-gate-1",
                        "payload": {},
                        "decision": {"action": "accept"},
                    },
                )
            ],
        },
    )
    assert refused.json()["results"][0]["status"] == "rejected"
    assert db.query(AiSuggestion).count() == 0
