from __future__ import annotations

from datetime import date

from app.models.patient import Patient


def test_create_patient_encrypts_pii_at_rest(
    client, clinic_factory, user_factory, auth_headers, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-p1@sihhat.uz")
    response = client.post(
        "/api/v1/patients",
        headers=auth_headers("doc-p1@sihhat.uz"),
        json={
            "pii": {
                "full_name": "Aziza Yusupova",
                "phone": "+998901234567",
                "passport": "AA1234567",
            },
            "dob": "1985-04-12",
            "sex": "female",
            "chronic_flags": ["hypertension"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pii"]["full_name"] == "Aziza Yusupova"

    stored = db.get(Patient, __import__("uuid").UUID(body["id"]))
    assert b"Aziza" not in stored.pii_blob
    assert b"AA1234567" not in stored.pii_blob
    assert stored.get_pii()["passport"] == "AA1234567"


def test_age_band_boundaries(db, clinic_factory):
    clinic = clinic_factory()
    today = date.today()

    def band_for(years: int) -> str:
        patient = Patient(clinic_id=clinic.id, mrn="P-X", pii_blob=b"")
        patient.dob = date(today.year - years, today.month, min(today.day, 28))
        return patient.age_band

    assert band_for(0) == "infant"
    assert band_for(3) == "under5"
    assert band_for(8) == "child"
    assert band_for(15) == "adolescent"
    assert band_for(40) == "adult"
    assert band_for(70) == "elderly"
    assert Patient(clinic_id=clinic.id, mrn="P-Y", pii_blob=b"").age_band == "unknown"


def test_mrn_prefix_search(client, clinic_factory, user_factory, auth_headers, patient_factory):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-p2@sihhat.uz")
    patient_factory(clinic, mrn="P-AAAA1111")
    patient_factory(clinic, mrn="P-BBBB2222")
    headers = auth_headers("doc-p2@sihhat.uz")
    rows = client.get("/api/v1/patients?q=P-AAAA", headers=headers).json()
    assert [r["mrn"] for r in rows] == ["P-AAAA1111"]


def test_updating_pii_rewrites_the_blob(
    client, clinic_factory, user_factory, auth_headers, patient_factory, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-p3@sihhat.uz")
    patient = patient_factory(clinic, name="Old Name")
    before = bytes(patient.pii_blob)

    response = client.patch(
        f"/api/v1/patients/{patient.id}",
        headers=auth_headers("doc-p3@sihhat.uz"),
        json={"pii": {"full_name": "New Name", "phone": "+998907654321"}},
    )
    assert response.status_code == 200
    db.refresh(patient)
    assert patient.pii_blob != before
    assert patient.get_pii()["full_name"] == "New Name"


def test_patient_actions_are_audited(client, clinic_factory, user_factory, auth_headers, db):
    from app.models.audit import AuditLog

    clinic = clinic_factory()
    user_factory(clinic, email="doc-p4@sihhat.uz")
    client.post(
        "/api/v1/patients",
        headers=auth_headers("doc-p4@sihhat.uz"),
        json={"pii": {"full_name": "Audited Patient"}, "sex": "male"},
    )
    actions = [row.action for row in db.query(AuditLog).all()]
    assert "patient.created" in actions
    # No identifier may reach the audit trail.
    assert all("Audited Patient" not in str(row.metadata_json) for row in db.query(AuditLog).all())


def test_vitals_out_of_physiological_range_are_rejected(
    client, clinic_factory, user_factory, auth_headers, patient_factory
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-p5@sihhat.uz")
    patient = patient_factory(clinic)
    response = client.post(
        "/api/v1/consultations",
        headers=auth_headers("doc-p5@sihhat.uz"),
        json={
            "patient_id": str(patient.id),
            "chief_complaint": "isitma",
            "vitals": {"temperature_c": 95.0},
        },
    )
    assert response.status_code == 422


def test_completed_consultation_is_immutable(
    client, clinic_factory, user_factory, auth_headers, patient_factory
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-p6@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-p6@sihhat.uz")
    consultation = client.post(
        "/api/v1/consultations",
        headers=headers,
        json={"patient_id": str(patient.id), "chief_complaint": "yo'tal"},
    ).json()
    client.patch(
        f"/api/v1/consultations/{consultation['id']}", headers=headers, json={"status": "completed"}
    )
    late = client.patch(
        f"/api/v1/consultations/{consultation['id']}",
        headers=headers,
        json={"chief_complaint": "changed after the fact"},
    )
    assert late.status_code == 409
