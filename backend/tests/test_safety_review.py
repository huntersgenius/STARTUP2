"""Defects found by the hostile-review pass, locked in so they cannot return.

Each test here corresponds to a specific finding. The comment says what the
defect was, because a test whose purpose is forgotten gets deleted in the next
refactor.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents, load_formulary

from app.ai.engine import DiagnosticEngine
from app.ai.providers.baseline import RetrievalBaselineProvider
from app.ai.rag.retriever import HybridRetriever
from app.ai.router import ModelRouter
from app.models.consultation import Consultation
from app.models.patient import Patient, Sex
from tests.test_retrieval import CORPUS

FORMULARY_CSV = CORPUS.parent / "formulary.csv"


@pytest.fixture()
def knowledge(db):
    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(db, FORMULARY_CSV)
    return db


@pytest.fixture()
def engine(knowledge):
    model = RetrievalBaselineProvider()
    return DiagnosticEngine(
        knowledge,
        router=ModelRouter(openai=model, anthropic=model, local=model),
        retriever=HybridRetriever(knowledge),
        cache=None,
    )


def _patient_with_pii(db, clinic, **pii) -> Patient:
    patient = Patient(
        clinic_id=clinic.id,
        mrn="P-REVIEW1",
        dob=date(1980, 5, 5),
        sex=Sex.female,
        chronic_flags=[],
        pii_blob=b"",
    )
    patient.set_pii({"full_name": "Aziza Yusupova", "phone": "+998901234567", **pii})
    db.add(patient)
    db.flush()
    return patient


def test_chronic_flags_are_scrubbed_before_reaching_the_prompt(
    engine, knowledge, clinic_factory, user_factory
):
    """Finding 1.

    `build_prompt` interpolated `case.chronic_flags` — straight from the
    patient row — while every other field came from the scrubbed payload.
    Chronic flags are free text a clinician typed, so a name written there
    would have been sent to a third-party model.
    """
    clinic = clinic_factory()
    patient = _patient_with_pii(knowledge, clinic)
    # A clinician recording context the way they actually do.
    patient.chronic_flags = ["diabet (onasi Zulfiya Ismoilova ham kasal)"]
    knowledge.flush()

    consultation = Consultation(
        patient_id=patient.id,
        user_id=user_factory(clinic).id,
        clinic_id=clinic.id,
        language="uz",
        chief_complaint="yo'tal va isitma",
        vitals={"temperature_c": 38.2},
    )
    knowledge.add(consultation)
    knowledge.flush()

    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunks = engine.retrieve(case, scrubbed)
    system, user = engine.build_prompt(case, scrubbed, chunks, engine.red_flags(case))

    assert "Zulfiya" not in user
    assert "Ismoilova" not in user
    assert "Zulfiya" not in system


def test_raw_model_output_is_not_copied_into_the_audit_metadata(
    engine, knowledge, clinic_factory, user_factory
):
    """Finding 2.

    The engine trace carried the full raw model response, and the API writes
    that trace into `AuditLog.metadata_json` — which is exported to the
    regulator as CSV. The output is already persisted on
    `AiSuggestion.raw_output`; duplicating it bloated every audit row with
    model prose.
    """
    clinic = clinic_factory()
    patient = _patient_with_pii(knowledge, clinic)
    consultation = Consultation(
        patient_id=patient.id,
        user_id=user_factory(clinic).id,
        clinic_id=clinic.id,
        language="uz",
        chief_complaint="balg'amli yo'tal, isitma 38.5",
        vitals={"temperature_c": 38.5},
    )
    knowledge.add(consultation)
    knowledge.flush()

    result = engine.analyze(consultation, patient)
    serialised = json.dumps(result.trace, ensure_ascii=False)

    assert "raw_output" not in serialised
    assert "response_chars" in serialised
    # The output itself is still recorded, just in the right column.
    assert result.raw_output


def test_audit_metadata_stays_small_enough_to_export(
    client, seeded_engine_patient, auth_headers, db
):
    """A regulator's CSV export must remain readable.

    Not a hard limit, but a tripwire: if a trace starts carrying kilobytes
    again, this fails before the export does.
    """
    from app.models.audit import AuditLog

    headers, consultation_id = seeded_engine_patient
    client.post(f"/api/v1/consultations/{consultation_id}/analyze", headers=headers, json={})

    rows = db.query(AuditLog).filter(AuditLog.action == "ai.analyzed").all()
    assert rows
    for row in rows:
        assert len(json.dumps(row.metadata_json, ensure_ascii=False)) < 4000


@pytest.fixture()
def seeded_engine_patient(client, db, clinic_factory, user_factory, patient_factory, auth_headers):
    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(db, FORMULARY_CSV)
    clinic = clinic_factory()
    user_factory(clinic, email="review-doc@sihhat.uz")
    patient = patient_factory(clinic)
    headers = auth_headers("review-doc@sihhat.uz")
    consultation = client.post(
        "/api/v1/consultations",
        headers=headers,
        json={
            "patient_id": str(patient.id),
            "chief_complaint": "3 kundan beri yo'tal va isitma",
            "language": "uz",
            "vitals": {"temperature_c": 38.2},
        },
    ).json()
    return headers, consultation["id"]
