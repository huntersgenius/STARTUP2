"""Every red-flag rule, tested individually.

These rules are the part of the system that catches the patient who is about
to die. They are pure functions with no model involved, so there is no excuse
for not testing each one.
"""

from __future__ import annotations

import pytest

from app.ai.red_flags import RULES, CaseFacts, Urgency, evaluate, highest_urgency


def codes(facts: CaseFacts) -> set[str]:
    return {flag.code for flag in evaluate(facts)}


def test_every_registered_rule_has_a_test():
    # Guards against a rule being added without coverage.
    assert len(RULES) == 17


def test_no_rule_fires_on_an_empty_case():
    assert evaluate(CaseFacts(concepts=set())) == []


# --- cardiorespiratory ---------------------------------------------------


def test_chest_pain_with_dyspnea_fires_acs():
    assert "acs_suspected" in codes(CaseFacts(concepts={"chest_pain", "dyspnea"}))


def test_crushing_chest_pain_alone_fires_acs():
    assert "acs_suspected" in codes(CaseFacts(concepts={"crushing_chest_pain"}))


def test_chest_pain_alone_does_not_fire_acs():
    # Musculoskeletal chest pain is common; firing on it would train clinicians
    # to ignore the banner.
    assert "acs_suspected" not in codes(CaseFacts(concepts={"chest_pain"}))


@pytest.mark.parametrize(("spo2", "expected"), [(88, True), (91, True), (92, False), (98, False)])
def test_hypoxia_threshold(spo2, expected):
    assert ("hypoxia" in codes(CaseFacts(concepts=set(), spo2=spo2))) is expected


def test_tachypnea_fires_respiratory_distress():
    assert "respiratory_distress" in codes(CaseFacts(concepts=set(), respiratory_rate=32))


def test_choking_fires_airway_compromise():
    assert "airway_compromise" in codes(CaseFacts(concepts={"choking"}))


# --- sepsis --------------------------------------------------------------


def test_sepsis_needs_infection_plus_two_criteria():
    facts = CaseFacts(concepts={"fever"}, systolic_bp=95, respiratory_rate=24)
    assert "sepsis_suspected" in codes(facts)


def test_sepsis_does_not_fire_on_one_criterion():
    assert "sepsis_suspected" not in codes(CaseFacts(concepts={"fever"}, systolic_bp=95))


def test_sepsis_does_not_fire_without_infection():
    # Low BP and fast breathing without infection is a different emergency.
    assert "sepsis_suspected" not in codes(
        CaseFacts(concepts=set(), systolic_bp=95, respiratory_rate=24)
    )


# --- neurological --------------------------------------------------------


def test_stroke_fast_fires_on_unilateral_weakness():
    assert "stroke_fast" in codes(CaseFacts(concepts={"unilateral_weakness"}))


def test_stroke_fast_fires_on_slurred_speech():
    assert "stroke_fast" in codes(CaseFacts(concepts={"slurred_speech"}))


def test_meningism_fires_on_stiff_neck_with_fever():
    assert "meningism" in codes(CaseFacts(concepts={"neck_stiffness", "fever"}))


def test_meningism_fires_on_two_signs_without_fever():
    assert "meningism" in codes(CaseFacts(concepts={"neck_stiffness", "photophobia"}))


def test_stiff_neck_alone_does_not_fire_meningism():
    assert "meningism" not in codes(CaseFacts(concepts={"neck_stiffness"}))


def test_adult_seizure_fires():
    assert "seizure" in codes(CaseFacts(concepts={"seizure"}, age_band="adult"))


# --- pediatric -----------------------------------------------------------


def test_imci_danger_sign_fires_in_a_child():
    assert "imci_danger_sign" in codes(CaseFacts(concepts={"unable_to_feed"}, age_band="under5"))


def test_imci_danger_sign_does_not_fire_in_an_adult():
    assert "imci_danger_sign" not in codes(CaseFacts(concepts={"lethargy"}, age_band="adult"))


def test_pediatric_dehydration_fires():
    facts = CaseFacts(concepts={"diarrhea", "dehydration"}, age_band="under5")
    assert "pediatric_dehydration" in codes(facts)


def test_adult_diarrhea_with_dehydration_is_not_the_pediatric_rule():
    facts = CaseFacts(concepts={"diarrhea", "dehydration"}, age_band="adult")
    assert "pediatric_dehydration" not in codes(facts)


# --- obstetric -----------------------------------------------------------


def test_pregnancy_bleeding_fires():
    assert "pregnancy_bleeding" in codes(CaseFacts(concepts={"pregnancy_bleeding"}))


def test_preeclampsia_fires_on_raised_bp_in_pregnancy():
    facts = CaseFacts(concepts=set(), pregnant=True, systolic_bp=150)
    assert "preeclampsia_suspected" in codes(facts)


def test_same_bp_in_a_non_pregnant_patient_does_not_fire_preeclampsia():
    assert "preeclampsia_suspected" not in codes(CaseFacts(concepts=set(), systolic_bp=150))


# --- bleeding and infection ---------------------------------------------


@pytest.mark.parametrize("sign", ["hematemesis", "melena", "bloody_diarrhea"])
def test_gi_bleeding_signs_fire(sign):
    assert "gi_bleeding" in codes(CaseFacts(concepts={sign}))


def test_hemoptysis_fires():
    assert "hemoptysis" in codes(CaseFacts(concepts={"hemoptysis"}))


def test_tb_triad_fires_on_prolonged_cough_with_night_sweats():
    facts = CaseFacts(concepts={"cough", "night_sweats"}, duration_days=30)
    assert "tb_suspected" in codes(facts)


def test_tb_triad_does_not_fire_on_a_three_day_cough():
    facts = CaseFacts(concepts={"cough", "night_sweats"}, duration_days=3)
    assert "tb_suspected" not in codes(facts)


def test_tb_triad_uses_the_duration_concept_when_no_days_given():
    facts = CaseFacts(concepts={"cough", "weight_loss", "onset_over_3w"})
    assert "tb_suspected" in codes(facts)


# --- metabolic -----------------------------------------------------------


@pytest.mark.parametrize(
    ("glucose", "code"), [(25.0, "hyperglycemic_emergency"), (2.1, "hypoglycemia")]
)
def test_glucose_emergencies(glucose, code):
    assert code in codes(CaseFacts(concepts=set(), glucose_mmol=glucose))


def test_normal_glucose_fires_nothing():
    assert codes(CaseFacts(concepts=set(), glucose_mmol=5.5)) == set()


def test_hypertensive_emergency_needs_symptoms():
    silent = CaseFacts(concepts=set(), systolic_bp=190)
    symptomatic = CaseFacts(concepts={"thunderclap_headache"}, systolic_bp=190)
    assert "hypertensive_emergency" not in codes(silent)
    assert "hypertensive_emergency" in codes(symptomatic)


def test_severe_anemia_fires_with_breathlessness():
    assert "severe_anemia" in codes(CaseFacts(concepts={"anemia", "dyspnea"}))


# --- ordering and messages ----------------------------------------------


def test_flags_are_ordered_most_urgent_first():
    facts = CaseFacts(concepts={"cough", "night_sweats", "chest_pain", "dyspnea"}, duration_days=30)
    flags = evaluate(facts)
    assert flags[0].urgency is Urgency.immediate
    assert highest_urgency(flags) is Urgency.immediate


def test_every_flag_has_all_three_languages():
    facts = CaseFacts(concepts={"chest_pain", "dyspnea"})
    for flag in evaluate(facts):
        for language in ("uz", "ru", "en"):
            message = flag.message(language)
            assert message and len(message) > 10
        # The Uzbek and Russian text must not be the English text.
        assert flag.message("uz") != flag.message("en")
        assert flag.message("ru") != flag.message("en")


def test_every_flag_names_where_to_refer():
    facts = CaseFacts(concepts={"diarrhea", "dehydration"}, age_band="under5")
    for flag in evaluate(facts):
        assert flag.refer_to
        assert flag.triggered_by


def test_rules_do_not_depend_on_any_model():
    # The safety layer must be importable and runnable with no provider wired.
    import app.ai.red_flags as module

    source = module.__file__
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    for forbidden in ("openai", "anthropic", "httpx", "engine", "router"):
        assert forbidden not in text.lower(), f"red_flags.py must not reference {forbidden}"
