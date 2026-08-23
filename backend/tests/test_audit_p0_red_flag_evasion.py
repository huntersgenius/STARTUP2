"""AUDIT ARTEFACT — THESE TESTS ARE EXPECTED TO FAIL. DO NOT DELETE TO GET GREEN.

Left in the repository deliberately by the post-execution audit (see
`audit/01-findings.md`, findings A-01 and A-02). Each test asserts the behaviour
a clinician is entitled to assume, and each one currently fails. They are the
proof that the reported "red-flag recall 100.0% (158/158)" is recall on text
written in the rules' own vocabulary, not recall on danger.

The correct way to make these pass is to make the concept layer recognise the
clinical picture rather than the exact phrase — not to add these sentences to
`knowledge/terminology.csv`. Adding the sentences would make the tests pass
without making a patient safer, which is the precise failure mode these tests
exist to prevent.

Run:
    cd backend && ../.venv/bin/python -m pytest tests/test_audit_p0_red_flag_evasion.py -v
"""

from __future__ import annotations

import pytest

from app.ai.red_flags import CaseFacts, evaluate
from knowledge.terminology import get_terminology


def fired(text: str, **facts) -> list[str]:
    """Concepts and rules exactly as `DiagnosticEngine.normalize`/`red_flags` derive them."""
    concepts = get_terminology().clinical_concepts(text)
    return [f.code for f in evaluate(CaseFacts(concepts=set(concepts), free_text=text, **facts))]


# --- A-01: danger present, described in ordinary words --------------------


@pytest.mark.parametrize(
    ("text", "why"),
    [
        (
            "Ko'kragim qattiq og'riyapti va nafas qisyapti, ter bosdi",
            "chest pain + dyspnoea + diaphoresis; an intensifier ('qattiq') sits between "
            "the body part and the verb, which is where Uzbek puts it",
        ),
        (
            "Ko'kragimni kimdir bosib turgandek, yelkamga va jag'imga tarqaladi, nafasim bo'g'ilyapti",
            "crushing chest pain radiating to shoulder and jaw with breathlessness",
        ),
        (
            "Грудь сильно болит, дышать нечем, холодный пот прошиб",
            "the same picture in ordinary Russian",
        ),
    ],
)
def test_acs_fires_when_the_patient_does_not_use_the_rule_s_words(text: str, why: str) -> None:
    """A missed ACS is a person who was not referred. Reason: {why}."""
    assert "acs_suspected" in fired(text), f"no ACS red flag for: {text!r} — {why}"


def test_stroke_fires_when_described_as_a_relative_would_describe_it() -> None:
    text = "Yuzi qiyshayib qoldi, gapi tushunarsiz, bir tomoni ishlamayapti"
    assert "stroke_fast" in fired(text, age_years=71, age_band="elderly"), (
        "face droop + slurred speech + one-sided weakness is FAST-positive; "
        "the thrombolysis window is measured in hours"
    )


def test_seizure_fires_when_described_without_the_word_seizure() -> None:
    text = "Butun badani tortishdi, og'zidan ko'pik chiqdi, tilini tishlab olibdi, o'zini bilmadi"
    assert "seizure" in fired(text, age_years=31, age_band="adult"), (
        "generalised tonic-clonic seizure with tongue-biting and post-ictal confusion"
    )


def test_gi_bleeding_fires_on_melena_described_in_plain_language() -> None:
    text = "Qusganimda qora quyqa chiqdi, hojatim ham qop-qora bo'ldi"
    assert "gi_bleeding" in fired(text, age_years=55, age_band="adult"), (
        "coffee-ground vomit and black stool is upper GI bleeding until proven otherwise"
    )


# --- A-02: danger explicitly denied, flag fires anyway --------------------


@pytest.mark.parametrize(
    ("text", "must_not_fire"),
    [
        ("Ko'krak og'rig'i yo'q, nafas qisishi yo'q. Retsept uchun keldim.", "acs_suspected"),
        ("Qon tupurish yo'q, balg'am oq, uch kundan beri yo'tal.", "hemoptysis"),
    ],
)
def test_an_explicitly_denied_symptom_does_not_raise_a_red_flag(
    text: str, must_not_fire: str
) -> None:
    """`X yo'q` means "no X". Referring a patient on a denial costs them a journey
    they cannot afford, and teaches the clinic to ignore the banner."""
    assert must_not_fire not in fired(text), f"{must_not_fire} fired on a denial: {text!r}"


def test_a_past_event_is_not_a_present_emergency() -> None:
    text = (
        "O'tgan yili ko'krak qafasida siquvchi og'riq bo'lgan, stent qo'yishgan. "
        "Hozir shikoyatim yo'q, retsept uchun keldim."
    )
    assert "acs_suspected" not in fired(text, age_years=62, age_band="adult"), (
        "a stent placed last year is history, not an ambulance call"
    )


# --- A-03: a common Russian intensifier is read as tuberculosis -----------


@pytest.mark.parametrize("text", ["Сил нет", "сильная боль", "сильно болит голова"])
def test_russian_intensifier_is_not_read_as_tuberculosis(text: str) -> None:
    """`sil` is Uzbek for tuberculosis. The Cyrillic->Latin pass turns Russian
    `сильно`/`сил` into `siln`/`sil`, and the 5-character suffix allowance lets
    the tuberculosis surface claim it. TB is a live differential in Uzbekistan;
    seeding it from the word "strongly" corrupts both the differential and the
    clinician's trust in the banner."""
    assert "tuberculosis" not in get_terminology().clinical_concepts(text), (
        f"spurious tuberculosis concept from {text!r}"
    )
