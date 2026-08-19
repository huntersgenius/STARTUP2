"""End-to-end: symptom in → suggestion out → clinician decision recorded."""

from __future__ import annotations

import json

import pytest
from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents, load_formulary

from app.ai.providers.llm import ScriptedProvider
from app.ai.router import ModelRouter
from app.models.ai import AiSuggestion, ClinicianDecision
from app.models.audit import AuditLog
from app.models.consultation import ConsultationStatus
from app.models.user import UserRole
from tests.test_retrieval import CORPUS

FORMULARY_CSV = CORPUS.parent / "formulary.csv"


@pytest.fixture()
def seeded(db):
    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(db, FORMULARY_CSV)
    return db


@pytest.fixture()
def scripted_engine(monkeypatch, db):
    """Point the API's engine at a scripted provider — no network in tests."""
    from app.ai import engine as engine_module

    original_init = engine_module.DiagnosticEngine.__init__

    def patched(self, session, **kwargs):
        original_init(self, session, **kwargs)
        # The response cites the first chunk this engine actually retrieves,
        # so grounding is exercised rather than bypassed.
        chunk_ids = [c.id[:8] for c in self.retriever.retrieve("yo'tal isitma", limit=1)]
        response = json.dumps(
            {
                "differentials": [
                    {
                        "condition": "O'tkir bronxit",
                        "icd10": "J40",
                        "confidence": 0.68,
                        "why": "Isitma va balg'amli yo'tal, o'pkada mahalliy xirillashsiz.",
                        "citations": chunk_ids,
                    }
                ],
                "recommended_tests": [{"name": "Umumiy qon tahlili", "reason": "infeksiya"}],
                "treatment": {
                    "items": [{"drug": "paracetamol", "dose": "500 mg", "duration": "3 kun"}],
                    "non_pharmacological": ["ko'p suyuqlik"],
                },
                "risk": {"score": 0.2, "band": "low", "drivers": []},
                "referral": {"needed": False, "urgency": "none"},
            },
            ensure_ascii=False,
        )
        scripted = ScriptedProvider(default=response)
        self.router = ModelRouter(openai=scripted, anthropic=scripted, local=scripted)

    monkeypatch.setattr(engine_module.DiagnosticEngine, "__init__", patched)


def _make_consultation(client, headers, patient_id, complaint="3 kundan beri yo'tal va isitma"):
    return client.post(
        "/api/v1/consultations",
        headers=headers,
        json={
            "patient_id": str(patient_id),
            "chief_complaint": complaint,
            "language": "uz",
            "vitals": {"temperature_c": 38.2, "pulse_bpm": 92},
        },
    ).json()


def test_full_consultation_flow(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-ai@sihhat.uz")

    consultation = _make_consultation(client, headers, patient.id)

    analysis = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={}
    )
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()

    # The gate is explicit in the response, not implied.
    assert body["requires_clinician_review"] is True
    assert body["disclaimer"]
    assert body["payload"]["differentials"]
    assert body["prompt_version"].startswith("v1@")

    # The consultation is waiting on a human, not finished.
    stored = db.query(AiSuggestion).one()
    assert stored.input_hash and stored.model
    consultation_row = client.get(
        f"/api/v1/consultations/{consultation['id']}", headers=headers
    ).json()
    assert consultation_row["status"] == ConsultationStatus.awaiting_decision.value

    decision = client.post(
        f"/api/v1/suggestions/{body['suggestion_id']}/decision",
        headers=headers,
        json={"action": "accept"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["consultation_status"] == ConsultationStatus.completed.value
    assert db.query(ClinicianDecision).count() == 1


def test_suggestion_payload_never_contains_patient_identifiers(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai2@sihhat.uz")
    patient = patient_factory(clinic, name="Aziza Yusupova")
    headers = auth_headers("doc-ai2@sihhat.uz")

    consultation = _make_consultation(
        client, headers, patient.id, complaint="Bemor Aziza Yusupova, tel +998901234567, yo'tal bor"
    )
    analysis = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={}
    ).json()

    # The stored raw model output is part of the audit trail; it must be clean.
    assert "Aziza" not in json.dumps(analysis["payload"], ensure_ascii=False)


def test_decision_is_required_before_a_consultation_completes(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai3@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-ai3@sihhat.uz")
    consultation = _make_consultation(client, headers, patient.id)
    client.post(f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={})

    listed = client.get(
        f"/api/v1/consultations/{consultation['id']}/suggestions", headers=headers
    ).json()
    assert listed[0]["requires_clinician_review"] is True
    assert listed[0]["decision"] is None


def test_edit_requires_final_text_and_reject_requires_a_reason(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai4@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-ai4@sihhat.uz")
    consultation = _make_consultation(client, headers, patient.id)
    suggestion_id = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={}
    ).json()["suggestion_id"]

    assert (
        client.post(
            f"/api/v1/suggestions/{suggestion_id}/decision",
            headers=headers,
            json={"action": "edit"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/v1/suggestions/{suggestion_id}/decision",
            headers=headers,
            json={"action": "reject"},
        ).status_code
        == 400
    )
    ok = client.post(
        f"/api/v1/suggestions/{suggestion_id}/decision",
        headers=headers,
        json={"action": "reject", "reason": "Klinik manzara mos kelmaydi"},
    )
    assert ok.status_code == 200


def test_a_decision_cannot_be_recorded_twice(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai5@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-ai5@sihhat.uz")
    consultation = _make_consultation(client, headers, patient.id)
    suggestion_id = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={}
    ).json()["suggestion_id"]

    first = client.post(
        f"/api/v1/suggestions/{suggestion_id}/decision", headers=headers, json={"action": "accept"}
    )
    second = client.post(
        f"/api/v1/suggestions/{suggestion_id}/decision", headers=headers, json={"action": "accept"}
    )
    assert first.status_code == 200
    assert second.status_code == 409


def test_a_nurse_cannot_close_the_clinical_gate(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai6@sihhat.uz")
    user_factory(clinic, email="nurse-ai@sihhat.uz", role=UserRole.nurse)
    patient = patient_factory(clinic)
    doctor_headers = auth_headers("doc-ai6@sihhat.uz")

    consultation = _make_consultation(client, doctor_headers, patient.id)
    suggestion_id = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=doctor_headers, json={}
    ).json()["suggestion_id"]

    refused = client.post(
        f"/api/v1/suggestions/{suggestion_id}/decision",
        headers=auth_headers("nurse-ai@sihhat.uz"),
        json={"action": "accept"},
    )
    assert refused.status_code == 403


def test_another_clinic_cannot_analyze_or_decide(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="doc-a-ai@sihhat.uz")
    user_factory(clinic_b, email="doc-b-ai@sihhat.uz")
    patient_b = patient_factory(clinic_b)

    consultation = _make_consultation(client, auth_headers("doc-b-ai@sihhat.uz"), patient_b.id)
    refused = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze",
        headers=auth_headers("doc-a-ai@sihhat.uz"),
        json={},
    )
    assert refused.status_code == 404


def test_analysis_and_decision_are_both_audited(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine, db
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai7@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-ai7@sihhat.uz")
    consultation = _make_consultation(client, headers, patient.id)
    suggestion_id = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={}
    ).json()["suggestion_id"]
    client.post(
        f"/api/v1/suggestions/{suggestion_id}/decision", headers=headers, json={"action": "accept"}
    )

    actions = [row.action for row in db.query(AuditLog).all()]
    assert "ai.analyzed" in actions
    assert "ai.decision" in actions

    from app.core import audit

    ok, problem = audit.verify_chain(db)
    assert ok, problem


def test_red_flag_case_forces_referral_end_to_end(
    client, seeded, clinic_factory, user_factory, patient_factory, auth_headers, scripted_engine
):
    clinic = clinic_factory()
    user_factory(clinic, email="doc-ai8@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("doc-ai8@sihhat.uz")

    consultation = _make_consultation(
        client,
        headers,
        patient.id,
        complaint="ko'krak og'rig'i va nafas qisishi, to'satdan boshlandi",
    )
    payload = client.post(
        f"/api/v1/consultations/{consultation['id']}/analyze", headers=headers, json={}
    ).json()["payload"]

    assert payload["red_flags"], "a chest pain + dyspnea case must fire a red flag"
    assert payload["referral"]["needed"] is True
    assert payload["referral"]["urgency"] == "immediate"
    # The banner text is in the clinician's language.
    assert payload["red_flags"][0]["message"]
