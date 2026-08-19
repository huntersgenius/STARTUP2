"""A user must never read another clinic's patients. This is the test that
matters most in Sprint 1 — every other guarantee assumes it holds.
"""

from __future__ import annotations

import uuid

from app.models.user import UserRole


def test_patient_list_is_scoped_to_own_clinic(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic_a = clinic_factory(name="Chinoz QVP")
    clinic_b = clinic_factory(name="Zangiota QVP")
    user_factory(clinic_a, email="doc-a@sihhat.uz")
    patient_a = patient_factory(clinic_a, name="Aziza Yusupova")
    patient_b = patient_factory(clinic_b, name="Bekzod Rahimov")

    response = client.get("/api/v1/patients", headers=auth_headers("doc-a@sihhat.uz"))
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(patient_a.id) in ids
    assert str(patient_b.id) not in ids


def test_reading_another_clinics_patient_is_404_not_403(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="doc-a2@sihhat.uz")
    patient_b = patient_factory(clinic_b)

    response = client.get(
        f"/api/v1/patients/{patient_b.id}", headers=auth_headers("doc-a2@sihhat.uz")
    )
    # 403 would confirm the record exists. 404 leaks nothing.
    assert response.status_code == 404


def test_updating_another_clinics_patient_is_refused(
    client, clinic_factory, user_factory, patient_factory, auth_headers, db
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="doc-a3@sihhat.uz")
    patient_b = patient_factory(clinic_b, name="Bekzod Rahimov")

    response = client.patch(
        f"/api/v1/patients/{patient_b.id}",
        headers=auth_headers("doc-a3@sihhat.uz"),
        json={"chronic_flags": ["diabetes"]},
    )
    assert response.status_code == 404
    db.refresh(patient_b)
    assert patient_b.chronic_flags == []


def test_consultation_on_another_clinics_patient_is_refused(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="doc-a4@sihhat.uz")
    patient_b = patient_factory(clinic_b)

    response = client.post(
        "/api/v1/consultations",
        headers=auth_headers("doc-a4@sihhat.uz"),
        json={"patient_id": str(patient_b.id), "chief_complaint": "yo'tal va isitma"},
    )
    assert response.status_code == 404


def test_consultation_list_is_scoped(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="doc-a5@sihhat.uz")
    user_factory(clinic_b, email="doc-b5@sihhat.uz")
    patient_b = patient_factory(clinic_b)
    client.post(
        "/api/v1/consultations",
        headers=auth_headers("doc-b5@sihhat.uz"),
        json={"patient_id": str(patient_b.id), "chief_complaint": "bosh og'rig'i"},
    )

    response = client.get("/api/v1/consultations", headers=auth_headers("doc-a5@sihhat.uz"))
    assert response.status_code == 200
    assert response.json() == []


def test_superadmin_may_read_across_clinics(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(None, email="root@sihhat.uz", role=UserRole.superadmin)
    patient_factory(clinic_a)
    patient_factory(clinic_b)

    response = client.get("/api/v1/patients", headers=auth_headers("root@sihhat.uz"))
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_user_without_clinic_sees_nothing_and_cannot_create(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic = clinic_factory()
    patient_factory(clinic)
    user_factory(None, email="orphan@sihhat.uz")
    headers = auth_headers("orphan@sihhat.uz")

    assert client.get("/api/v1/patients", headers=headers).json() == []
    created = client.post(
        "/api/v1/patients",
        headers=headers,
        json={"pii": {"full_name": "Test Patient"}, "sex": "male"},
    )
    assert created.status_code == 400


def test_unknown_patient_id_is_404(client, clinic_factory, user_factory, auth_headers):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-a6@sihhat.uz")
    response = client.get(
        f"/api/v1/patients/{uuid.uuid4()}", headers=auth_headers("doc-a6@sihhat.uz")
    )
    assert response.status_code == 404


def test_patient_list_never_exposes_identifiers(
    client, clinic_factory, user_factory, patient_factory, auth_headers
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-a7@sihhat.uz")
    patient_factory(clinic, name="Aziza Yusupova")
    response = client.get("/api/v1/patients", headers=auth_headers("doc-a7@sihhat.uz"))
    assert "Aziza" not in response.text
    assert "998901234567" not in response.text
