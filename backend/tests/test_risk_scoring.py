"""The risk score is computed, not authored by a model."""

from __future__ import annotations

import pytest
from ml.risk_scoring import RED_FLAG_FLOOR, score_patient


def test_a_well_patient_scores_low():
    assessment = score_patient(concepts=set(), age_years=30)
    assert assessment.band == "low"
    assert assessment.points == 0
    assert assessment.drivers == []


def test_every_point_is_attributable():
    # A score a clinician cannot interrogate is a number they will ignore.
    assessment = score_patient(
        concepts={"chest_pain", "dyspnea"},
        age_years=70,
        vitals={"spo2": 88},
    )
    assert assessment.points > 0
    assert len(assessment.drivers) >= 3
    assert sum(d.points for d in assessment.drivers) == assessment.points
    for driver in assessment.drivers:
        assert driver.detail and "+" in driver.detail


def test_a_red_flag_pins_the_score_high():
    """The rule layer already decided this patient needs referral.

    A risk score that quietly disagreed with a fired red flag would give a
    clinician a reason to discount the banner.
    """
    quiet = score_patient(concepts={"headache"}, age_years=30)
    flagged = score_patient(concepts={"headache"}, age_years=30, red_flag_codes=["meningism"])
    assert quiet.band == "low"
    assert flagged.points >= RED_FLAG_FLOOR
    assert flagged.band == "very_high"
    assert any("meningism" in text for text in flagged.driver_texts)


def test_bands_are_ordered_by_points():
    scores = [
        # low: nothing notable
        score_patient(concepts=set(), age_years=30),
        # moderate: chronic burden, nothing acute
        score_patient(concepts={"anemia", "diabetes_t2"}, age_years=70),
        # high: an acute presentation in an older patient
        score_patient(
            concepts={"chest_pain", "dyspnea"},
            age_years=70,
            vitals={"temperature_c": 38.6},
        ),
        # very high: the same, now hypoxic and shocked
        score_patient(
            concepts={"crushing_chest_pain"}, age_years=70, vitals={"systolic_bp": 85, "spo2": 88}
        ),
    ]
    points = [s.points for s in scores]
    assert points == sorted(points), points
    assert [s.band for s in scores] == ["low", "moderate", "high", "very_high"]


@pytest.mark.parametrize(
    ("age", "rate", "expect_points"),
    [
        # 40 breaths a minute is an emergency in an adult and unremarkable in
        # an infant. A single threshold would be wrong for one of them.
        (40, 40, True),
        (0.5, 40, False),
        (0.5, 62, True),
        (3, 52, True),
        (3, 30, False),
    ],
)
def test_respiratory_rate_thresholds_are_age_aware(age, rate, expect_points):
    assessment = score_patient(concepts=set(), age_years=age, vitals={"respiratory_rate": rate})
    scored = any(d.factor == "respiratory_rate" for d in assessment.drivers)
    assert scored is expect_points


def test_extremes_of_age_add_risk():
    infant = score_patient(concepts=set(), age_years=0.5)
    adult = score_patient(concepts=set(), age_years=35)
    elderly = score_patient(concepts=set(), age_years=82)
    assert infant.points > adult.points
    assert elderly.points > adult.points


def test_shock_and_hypoxia_dominate_chronic_risk():
    chronic = score_patient(
        concepts={"diabetes_t2", "hypertension", "overweight", "tobacco_use"},
        age_years=60,
    )
    acute = score_patient(concepts=set(), age_years=60, vitals={"systolic_bp": 82, "spo2": 87})
    assert acute.points > chronic.points


def test_score_is_bounded_and_not_presented_as_a_probability():
    extreme = score_patient(
        concepts={"crushing_chest_pain", "stroke", "hematemesis", "confusion"},
        age_years=90,
        vitals={"spo2": 80, "systolic_bp": 70, "glucose_mmol": 25},
        red_flag_codes=["acs_suspected", "stroke_fast"],
    )
    assert extreme.score == 1.0
    assert extreme.band == "very_high"


def test_chronic_flags_are_counted():
    plain = score_patient(concepts=set(), age_years=50)
    with_chronic = score_patient(
        concepts=set(), age_years=50, chronic_flags=["diabetes", "heart_failure"]
    )
    assert with_chronic.points > plain.points
    assert any("chronic" in text for text in with_chronic.driver_texts)


def test_unknown_chronic_flags_are_ignored_rather_than_guessed():
    assessment = score_patient(concepts=set(), age_years=50, chronic_flags=["something-odd"])
    assert assessment.points == 0


def test_malformed_vitals_do_not_crash_the_score():
    assessment = score_patient(
        concepts=set(),
        age_years=50,
        vitals={"spo2": "not a number", "systolic_bp": None, "pulse_bpm": ""},
    )
    assert assessment.band == "low"


def test_engine_uses_the_computed_score_not_the_models(db, clinic_factory, user_factory):
    """The model may write any risk number it likes; the engine overwrites it."""
    import json
    from datetime import date

    from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents

    from app.ai.engine import DiagnosticEngine
    from app.ai.providers.llm import ScriptedProvider
    from app.ai.rag.retriever import HybridRetriever
    from app.ai.router import ModelRouter
    from app.models.consultation import Consultation
    from app.models.patient import Patient, Sex

    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    clinic = clinic_factory()
    patient = Patient(
        clinic_id=clinic.id, mrn="P-RISK", dob=date(1950, 1, 1), sex=Sex.male, pii_blob=b""
    )
    patient.set_pii({"full_name": "Risk Test"})
    db.add(patient)
    db.flush()

    consultation = Consultation(
        patient_id=patient.id,
        user_id=user_factory(clinic).id,
        clinic_id=clinic.id,
        language="uz",
        chief_complaint="ko'krak og'rig'i va nafas qisishi",
        vitals={"spo2": 87},
    )
    db.add(consultation)
    db.flush()

    # A model claiming this patient is fine.
    lying = ScriptedProvider(
        default=json.dumps(
            {
                "differentials": [],
                "risk": {"score": 0.01, "band": "low", "drivers": ["nothing to worry about"]},
                "referral": {"needed": False, "urgency": "none"},
            }
        )
    )
    engine = DiagnosticEngine(
        db,
        router=ModelRouter(openai=lying, anthropic=lying, local=lying),
        retriever=HybridRetriever(db),
        cache=None,
    )
    result = engine.analyze(consultation, patient)

    assert result.suggestion.risk.band == "very_high"
    assert result.suggestion.risk.score > 0.5
    assert "nothing to worry about" not in result.suggestion.risk.drivers
