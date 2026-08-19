"""De-identification red-team suite.

**This suite may never be skipped.** CI runs it as its own named job. A single
leak here is a reportable breach in production, so the assertions are absolute
rather than statistical.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.deident import (
    PiiLeakError,
    assert_no_pii,
    deidentify,
    deidentify_payload,
    input_hash,
    reidentify,
)

FIXTURES = Path(__file__).parent / "fixtures" / "deident_redteam.json"

pytestmark = pytest.mark.redteam


def _cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


def test_fixture_set_is_large_enough_to_mean_something():
    cases = _cases()
    assert len(cases) >= 100
    assert {c["language"] for c in cases} == {"uz", "ru"}


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["id"])
def test_no_identifier_survives_on_the_production_path(case):
    """Layer 1 — the guarantee.

    This is exactly how `engine.py` calls it: the patient's identifiers come
    from the decrypted PII blob and are passed in. Zero leakage is required,
    on every case, in both languages.
    """
    result = deidentify(case["text"], known_values=case["identifiers"])
    assert_no_pii(result.text, case["identifiers"])


def test_pattern_net_recall_without_known_values():
    """Layer 2 — defence in depth, measured rather than assumed.

    Free text can mention people whose identifiers we do not hold (a relative,
    a contact). Patterns and the name gazetteer catch most of them. This test
    reports the real recall and holds it above a floor; it deliberately does
    not claim perfection, because a pattern layer cannot deliver it.
    """
    cases = _cases()
    total = caught = 0
    misses: list[tuple[str, str]] = []
    for case in cases:
        scrubbed = deidentify(case["text"]).text
        for identifier in case["identifiers"]:
            if len(identifier) <= 2:
                continue
            total += 1
            try:
                assert_no_pii(scrubbed, [identifier])
                caught += 1
            except PiiLeakError:
                misses.append((case["id"], identifier))

    recall = caught / total
    # Recorded so a regression is visible in CI output, not just a red bar.
    print(f"\npattern-net recall without known values: {recall:.1%} ({caught}/{total})")
    if misses:
        print(f"first misses: {misses[:5]}")
    assert recall >= 0.95, f"pattern net regressed to {recall:.1%}; misses: {misses[:10]}"


@pytest.mark.parametrize("case", _cases()[:20], ids=lambda c: c["id"])
def test_clinical_content_survives_deidentification(case):
    """Redaction must not destroy the reason for the consultation."""
    result = deidentify(case["text"], known_values=case["identifiers"])
    # Some clinical signal has to remain, or the suggestion is worthless.
    assert len(result.text.split()) >= 6
    assert result.redaction_count >= 2


def test_assert_no_pii_actually_catches_a_leak():
    # A test that can never fail proves nothing. This proves the detector works.
    with pytest.raises(PiiLeakError):
        assert_no_pii("Bemor Aziza Yusupova keldi", ["Aziza Yusupova"])


def test_leak_error_does_not_repeat_the_identifier():
    try:
        assert_no_pii("patient Aziza Yusupova", ["Aziza Yusupova"])
    except PiiLeakError as exc:
        assert "Aziza" not in str(exc)
    else:  # pragma: no cover
        pytest.fail("expected PiiLeakError")


def test_tokens_are_stable_per_person():
    text = "Bemor Aziza Yusupova keldi. Aziza Yusupova ga paratsetamol berildi."
    result = deidentify(text, known_values=["Aziza Yusupova"])
    # The same person must read as the same token, or the model loses the thread.
    assert result.text.count("[NAME_1]") == 2
    assert "[NAME_2]" not in result.text


def test_reidentification_restores_locally():
    original = "Bemor Aziza Yusupova, tel +998901234567"
    result = deidentify(original, known_values=["Aziza Yusupova", "+998901234567"])
    assert reidentify(result.text, result.mapping) == original


def test_structured_payload_drops_pii_keys_wholesale():
    payload = {
        "patient": {
            "full_name": "Aziza Yusupova",
            "phone": "+998901234567",
            "passport": "AA1234567",
            "address": "Chinoz tumani, Navro'z MFY",
            "dob": "1985-04-12",
            "sex": "female",
        },
        "consultation": {
            "chief_complaint": "Bemor Aziza Yusupova 3 kundan beri yo'talyapti",
            "vitals": {"temperature_c": 38.5},
        },
    }
    scrubbed, mapping = deidentify_payload(
        payload, known_values=["Aziza Yusupova", "+998901234567", "AA1234567"]
    )
    assert_no_pii(scrubbed, ["Aziza Yusupova", "+998901234567", "AA1234567", "Navro'z MFY"])
    # The clinical fields are untouched.
    assert scrubbed["consultation"]["vitals"]["temperature_c"] == 38.5
    assert scrubbed["patient"]["sex"] == "female"
    assert mapping


def test_nested_lists_are_scrubbed():
    payload = {
        "notes": [{"text": "Bemor Bekzod Rahimov, tel 90 555 44 33"}, {"text": "isitma bor"}]
    }
    scrubbed, _ = deidentify_payload(payload, known_values=["Bekzod Rahimov", "90 555 44 33"])
    assert_no_pii(scrubbed, ["Bekzod Rahimov", "90 555 44 33"])


@pytest.mark.parametrize(
    "phone",
    [
        "+998 90 123 45 67",
        "+998901234567",
        "998 91 555 44 33",
        "90 555 44 33",
        "+998-93-777-22-11",
        "8 90 111 22 33",
    ],
)
def test_every_phone_format_is_caught(phone):
    assert_no_pii(deidentify(f"telefon {phone} raqami").text, [phone])


@pytest.mark.parametrize("passport", ["AA1234567", "AB 7654321", "КА1122334"])
def test_passport_formats_are_caught(passport):
    assert_no_pii(deidentify(f"pasport {passport}").text, [passport])


@pytest.mark.parametrize("pinfl", ["31234567890123", "50987654321098"])
def test_pinfl_is_caught(pinfl):
    assert_no_pii(deidentify(f"PINFL {pinfl}").text, [pinfl])


def test_clinical_terms_are_not_mistaken_for_names():
    # Over-redaction that eats the diagnosis is a real failure mode.
    text = "Pnevmoniya va Gastrit shubhasi bor, Diabet anamnezda"
    scrubbed = deidentify(text).text
    for term in ("Pnevmoniya", "Gastrit", "Diabet"):
        assert term in scrubbed, f"{term} was redacted as a name"


def test_russian_clinical_terms_are_not_redacted():
    text = "Пневмония и Гастрит, в анамнезе Диабет"
    scrubbed = deidentify(text).text
    for term in ("Пневмония", "Гастрит", "Диабет"):
        assert term in scrubbed


def test_empty_and_whitespace_input_is_safe():
    assert deidentify("").text == ""
    assert deidentify("   ").text == "   "


def test_input_hash_is_stable_and_order_independent():
    a = input_hash({"b": 2, "a": 1})
    b = input_hash({"a": 1, "b": 2})
    assert a == b
    assert a != input_hash({"a": 1, "b": 3})
    assert len(a) == 64


def test_hash_of_deidentified_text_does_not_reveal_the_original():
    result = deidentify("Bemor Aziza Yusupova")
    digest = input_hash(result.text)
    assert "Aziza" not in digest
