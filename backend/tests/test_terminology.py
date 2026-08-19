from __future__ import annotations

import pytest
from knowledge.terminology import get_terminology, normalize


@pytest.fixture(scope="module")
def terms():
    return get_terminology()


def test_map_covers_at_least_300_primary_care_surfaces(terms):
    # The spec asks for 300+ terms including the informal words patients use.
    assert terms.surface_count >= 300
    assert len(terms) >= 100


def test_apostrophe_variants_all_resolve(terms):
    # A phone, a laptop and OCR each produce a different apostrophe.
    for variant in ["yo'tal", "yo’tal", "yoʻtal", "yotal", "YO'TAL"]:
        assert terms.lookup(variant) is not None, variant
        assert terms.lookup(variant).concept == "cough"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3 kundan beri yo'tal va isitma", {"cough", "fever"}),
        ("boshim og'riyapti", {"headache"}),
        ("qornim ogriyapti va kongim aynyapti", {"abdominal_pain", "nausea"}),
        ("ichim ketyapti", {"diarrhea"}),
        ("nafas qisishi va ko'krak og'rig'i", {"dyspnea", "chest_pain"}),
        ("shamollab qoldim", {"common_cold"}),
        ("bosim ko'tarilgan", {"hypertension"}),
        ("qand kasali bor", {"diabetes_t2"}),
        ("kechasi terlayman va ozib ketdim", {"night_sweats", "weight_loss"}),
        ("bo'yin qattiq, yorug'lik ko'zni og'ritadi", {"neck_stiffness", "photophobia"}),
    ],
)
def test_uzbek_colloquial_extraction(terms, text, expected):
    assert expected.issubset(set(terms.concepts_in(text)))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("кашель и температура три дня", {"cough", "fever"}),
        ("боль в груди и одышка", {"chest_pain", "dyspnea"}),
        ("головная боль и тошнота", {"headache", "nausea"}),
        ("диарея у ребёнка", {"diarrhea"}),
        ("повышенное давление", {"hypertension"}),
        ("сахарный диабет", {"diabetes_t2"}),
        ("кровь в мокроте", {"hemoptysis"}),
        ("боль в пояснице", {"low_back_pain"}),
        ("ночная потливость и потеря веса", {"night_sweats", "weight_loss"}),
        ("судороги", {"seizure"}),
    ],
)
def test_russian_extraction(terms, text, expected):
    assert expected.issubset(set(terms.concepts_in(text)))


def test_uzbek_cyrillic_is_understood(terms):
    # Older clinicians still write Uzbek in Cyrillic.
    assert "cough" in terms.concepts_in("йўтал ва иситма")


def test_longest_match_wins(terms):
    concepts = terms.concepts_in("quruq yo'tal bor")
    assert "dry_cough" in concepts
    # "yo'tal" inside "quruq yo'tal" must not be reported separately.
    assert "cough" not in concepts


def test_partial_words_do_not_match(terms):
    # "isitma" must not fire inside an unrelated longer token.
    assert "fever" not in terms.concepts_in("isitmasizlikxyz")


def test_red_flag_terms_are_flagged(terms):
    flags = {t.concept for t in terms.red_flag_terms("ko'krak og'rig'i va nafas qisishi bor")}
    assert "chest_pain" in flags


def test_icd10_candidates_are_surfaced(terms):
    codes = terms.icd10_candidates("qandli diabet va bosim ko'tarilishi")
    assert "E11.9" in codes
    assert "I10" in codes


def test_terms_round_trip_across_languages(terms):
    assert terms.translate("yo'tal", "ru") == "кашель"
    assert terms.translate("кашель", "en") == "cough"
    assert terms.translate("кашель", "uz") == "yo'tal"


def test_every_red_flag_term_has_an_icd10_code(terms):
    # A red flag with no code cannot be filtered on in retrieval.
    missing = [t.concept for t in terms.terms if t.is_red_flag and not t.icd10]
    assert missing == []


def test_no_duplicate_concepts():
    from knowledge.terminology import load_terms

    concepts = [t.concept for t in load_terms()]
    duplicates = {c for c in concepts if concepts.count(c) > 1}
    assert duplicates == set()


def test_normalize_is_idempotent():
    text = "  Yo’TAL   va\tISITMA "
    assert normalize(normalize(text)) == normalize(text)
    assert normalize(text) == "yo'tal va isitma"
