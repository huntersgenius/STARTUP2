"""The diagnostic pipeline, stage by stage and end to end."""

from __future__ import annotations

import json
from datetime import date

import pytest
from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents, load_formulary

from app.ai.cache import InMemoryCacheBackend, SemanticCache
from app.ai.engine import DiagnosticEngine
from app.ai.providers.llm import ScriptedProvider
from app.ai.rag.retriever import HybridRetriever
from app.ai.router import ModelRouter, Tier
from app.models.consultation import Consultation
from app.models.patient import Patient, Sex
from tests.test_retrieval import CORPUS

FORMULARY_CSV = CORPUS.parent / "formulary.csv"


def _valid_response(citation_id: str, confidence: float = 0.72, drug: str = "amoxicillin") -> str:
    return json.dumps(
        {
            "differentials": [
                {
                    "condition": "Community-acquired pneumonia",
                    "icd10": "J18.9",
                    "confidence": confidence,
                    "why": "Fever with productive cough and focal crackles.",
                    "red_flags": [],
                    "citations": [citation_id],
                }
            ],
            "recommended_tests": [{"name": "Chest X-ray", "reason": "confirm consolidation"}],
            "treatment": {
                "items": [{"drug": drug, "dose": "500 mg", "route": "oral", "duration": "5 days"}],
                "non_pharmacological": ["fluids", "rest"],
            },
            "risk": {"score": 0.4, "band": "moderate", "drivers": ["age"]},
            "referral": {"needed": False, "urgency": "none"},
        }
    )


@pytest.fixture()
def knowledge(db):
    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(db, FORMULARY_CSV)
    return db


@pytest.fixture()
def patient(db, clinic_factory):
    clinic = clinic_factory()
    p = Patient(
        clinic_id=clinic.id, mrn="P-ENG0001", dob=date(1979, 3, 8), sex=Sex.female, pii_blob=b""
    )
    p.set_pii({"full_name": "Zulfiya Ismoilova", "phone": "+998901112233"})
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def consultation(db, patient, user_factory):
    user = user_factory(patient.clinic)
    c = Consultation(
        patient_id=patient.id,
        user_id=user.id,
        clinic_id=patient.clinic_id,
        language="uz",
        chief_complaint="3 kundan beri balg'amli yo'tal, isitma 38.5, ko'krak og'rig'i",
        structured_symptoms={},
        vitals={"temperature_c": 38.5, "pulse_bpm": 96, "respiratory_rate": 20},
    )
    db.add(c)
    db.flush()
    return c


def make_engine(db, response: str | None = None, *, strict: bool = False) -> DiagnosticEngine:
    scripted = ScriptedProvider(default=response, strict=strict)
    router = ModelRouter(openai=scripted, anthropic=scripted, local=scripted)
    return DiagnosticEngine(
        db,
        router=router,
        retriever=HybridRetriever(db),
        cache=SemanticCache(backend=InMemoryCacheBackend()),
    )


# --- 1. normalize --------------------------------------------------------


def test_normalize_maps_uzbek_text_to_concepts(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    # "balg'amli yo'tal" is productive cough specifically: longest match wins.
    assert "productive_cough" in case.concepts
    assert "fever" in case.concepts
    assert "chest_pain" in case.concepts
    assert case.age_band == "adult"
    assert case.duration_days == 3.0


def test_normalize_derives_concepts_from_vitals(knowledge, consultation, patient, db):
    consultation.chief_complaint = "holsizlik"
    consultation.vitals = {"systolic_bp": 165, "diastolic_bp": 98, "glucose_mmol": 12.0}
    db.flush()
    case = make_engine(knowledge).normalize(consultation, patient)
    assert "hypertension" in case.concepts
    assert "diabetes_t2" in case.concepts


# --- 2. de-identify ------------------------------------------------------


def test_no_patient_identifier_reaches_the_prompt(knowledge, consultation, patient, db):
    consultation.chief_complaint = "Bemor Zulfiya Ismoilova, tel +998901112233, yo'tal va isitma"
    db.flush()
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, mapping = engine.deidentify(case, patient)
    serialised = json.dumps(scrubbed, ensure_ascii=False)
    assert "Zulfiya" not in serialised
    assert "998901112233" not in serialised
    assert mapping


def test_prompt_built_from_scrubbed_payload_carries_no_identifiers(
    knowledge, consultation, patient, db
):
    consultation.chief_complaint = "Bemor Zulfiya Ismoilova yo'talyapti, isitma 38.5"
    db.flush()
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunks = engine.retrieve(case, scrubbed)
    flags = engine.red_flags(case)
    system, user = engine.build_prompt(case, scrubbed, chunks, flags)
    assert "Zulfiya" not in user and "Zulfiya" not in system
    assert "998901112233" not in user


# --- 3. retrieve ---------------------------------------------------------


def test_retrieval_returns_cited_chunks(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunks = engine.retrieve(case, scrubbed)
    assert chunks
    assert all(c.citation for c in chunks)


# --- 4. route ------------------------------------------------------------


def test_offline_case_routes_local(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient, offline=True)
    assert engine.route(case, []).tier is Tier.local


def test_red_flag_case_requests_a_second_opinion(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    decision = engine.route(case, engine.red_flags(case))
    if engine.red_flags(case):
        assert decision.needs_second_opinion


# --- 5-6. reason and ground ---------------------------------------------


def test_uncited_differentials_are_dropped(knowledge, consultation, patient):
    engine = make_engine(knowledge, _valid_response("not-a-real-chunk-id"))
    result = engine.analyze(consultation, patient)
    # The differential cited a chunk that was never retrieved, so it must not
    # reach the clinician.
    assert result.suggestion.differentials == []
    assert result.trace.get("dropped_uncited")


def test_cited_differential_survives(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunk_id = engine.retrieve(case, scrubbed)[0].id[:8]

    engine = make_engine(knowledge, _valid_response(chunk_id))
    result = engine.analyze(consultation, patient)
    assert [d.condition for d in result.suggestion.differentials] == [
        "Community-acquired pneumonia"
    ]
    assert result.suggestion.differentials[0].citations == [chunk_id]


def test_malformed_response_degrades_to_rules_only(knowledge, consultation, patient):
    engine = make_engine(knowledge, "this is not JSON at all")
    result = engine.analyze(consultation, patient)
    assert result.degraded
    assert result.trace["degradation"] == "rules_only"
    assert result.suggestion.insufficient_data
    assert result.suggestion.follow_up_questions


def test_all_providers_down_still_produces_red_flags(knowledge, db, patient, user_factory):
    consultation = Consultation(
        patient_id=patient.id,
        user_id=user_factory(patient.clinic).id,
        clinic_id=patient.clinic_id,
        language="uz",
        chief_complaint="ko'krak og'rig'i va nafas qisishi",
        vitals={},
    )
    db.add(consultation)
    db.flush()

    engine = make_engine(knowledge, response=None, strict=False)  # no cassette → all fail
    result = engine.analyze(consultation, patient)
    assert result.degraded
    # The safety layer does not depend on any model being reachable.
    assert "acs_suspected" in {f.code for f in result.suggestion.red_flags}
    assert result.suggestion.referral.needed is True
    assert result.suggestion.referral.urgency == "immediate"


# --- 7. constrain --------------------------------------------------------


def test_unavailable_drug_is_flagged_with_a_substitute(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunk_id = engine.retrieve(case, scrubbed)[0].id[:8]

    engine = make_engine(knowledge, _valid_response(chunk_id, drug="losartan"))
    result = engine.analyze(consultation, patient, clinic_tier=1)
    item = result.suggestion.treatment.items[0]
    assert item.local_availability in ("substitute_suggested", "unavailable")
    assert item.notes


def test_drug_not_in_formulary_is_marked_unavailable(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunk_id = engine.retrieve(case, scrubbed)[0].id[:8]

    engine = make_engine(knowledge, _valid_response(chunk_id, drug="some-imported-brand"))
    result = engine.analyze(consultation, patient)
    assert result.suggestion.treatment.items[0].local_availability == "unavailable"


def test_pediatric_dose_without_weight_is_blocked(knowledge, db, user_factory, clinic_factory):
    clinic = clinic_factory()
    child = Patient(
        clinic_id=clinic.id,
        mrn="P-CHILD",
        dob=date.today().replace(year=date.today().year - 4),
        sex=Sex.male,
        pii_blob=b"",
    )
    child.set_pii({"full_name": "Bola Testov"})
    db.add(child)
    db.flush()
    consultation = Consultation(
        patient_id=child.id,
        user_id=user_factory(clinic).id,
        clinic_id=clinic.id,
        language="uz",
        chief_complaint="ich ketishi va isitma",
        vitals={"temperature_c": 38.2},  # no weight recorded
    )
    db.add(consultation)
    db.flush()

    engine = make_engine(knowledge)
    case = engine.normalize(consultation, child)
    scrubbed, _ = engine.deidentify(case, child)
    hits = engine.retrieve(case, scrubbed)
    chunk_id = hits[0].id[:8]

    engine = make_engine(knowledge, _valid_response(chunk_id, drug="paracetamol"))
    result = engine.analyze(consultation, child)
    assert result.suggestion.treatment.blocked_reason == "pediatric_weight_required"
    assert all(item.dose is None for item in result.suggestion.treatment.items)


def test_low_confidence_asks_questions_instead_of_guessing(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunk_id = engine.retrieve(case, scrubbed)[0].id[:8]

    engine = make_engine(knowledge, _valid_response(chunk_id, confidence=0.25))
    result = engine.analyze(consultation, patient)
    assert result.suggestion.differentials == []
    assert result.suggestion.insufficient_data
    assert len(result.suggestion.follow_up_questions) >= 3


# --- audit fields --------------------------------------------------------


def test_result_carries_everything_the_audit_row_needs(knowledge, consultation, patient):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunk_id = engine.retrieve(case, scrubbed)[0].id[:8]

    engine = make_engine(knowledge, _valid_response(chunk_id))
    result = engine.analyze(consultation, patient)
    assert len(result.input_hash) == 64
    assert result.prompt_version.startswith("v1@")
    assert result.model
    assert result.latency_ms >= 0
    assert result.cost_usd >= 0.0


def test_input_hash_is_of_the_deidentified_payload(knowledge, consultation, patient, db):
    consultation.chief_complaint = "Bemor Zulfiya Ismoilova yo'talyapti"
    db.flush()
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    from app.ai.deident import input_hash

    assert engine.analyze(consultation, patient).input_hash == input_hash(scrubbed)


# --- caching -------------------------------------------------------------


def test_second_identical_consultation_hits_the_cache(
    knowledge, consultation, patient, db, user_factory
):
    engine = make_engine(knowledge)
    case = engine.normalize(consultation, patient)
    scrubbed, _ = engine.deidentify(case, patient)
    chunk_id = engine.retrieve(case, scrubbed)[0].id[:8]

    cache = SemanticCache(backend=InMemoryCacheBackend())
    scripted = ScriptedProvider(default=_valid_response(chunk_id))
    router = ModelRouter(openai=scripted, anthropic=scripted, local=scripted)
    engine = DiagnosticEngine(db, router=router, retriever=HybridRetriever(db), cache=cache)

    first = engine.analyze(consultation, patient)
    assert not first.cache_hit

    twin = Consultation(
        patient_id=patient.id,
        user_id=consultation.user_id,
        clinic_id=patient.clinic_id,
        language="uz",
        chief_complaint=consultation.chief_complaint,
        vitals=dict(consultation.vitals),
    )
    db.add(twin)
    db.flush()
    second = engine.analyze(twin, patient)
    assert second.cache_hit
    assert second.cost_usd == 0.0


def test_degraded_responses_are_never_cached(knowledge, consultation, patient, db):
    cache = SemanticCache(backend=InMemoryCacheBackend())
    engine = make_engine(knowledge, "not json")
    engine.cache = cache
    engine.analyze(consultation, patient)
    assert cache.backend.store == {}
