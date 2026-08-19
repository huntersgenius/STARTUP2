from __future__ import annotations

import json

import pytest

from app.core.i18n import LOCALES_DIR, catalog, resolve_language, translate


def test_all_catalogs_have_identical_keys():
    catalogs = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in LOCALES_DIR.glob("*.json")
    }
    assert set(catalogs) == {"uz", "ru", "en"}
    reference = set(catalogs["uz"])
    for lang, entries in catalogs.items():
        assert set(entries) == reference, f"{lang} catalog keys diverge"


def test_no_catalog_entry_is_empty():
    for path in LOCALES_DIR.glob("*.json"):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            assert value.strip(), f"{path.stem}:{key} is empty"


def test_clinical_strings_are_actually_translated():
    # A catalog that silently copies English is worse than a missing one:
    # it looks translated in review and is unusable in a clinic.
    for key in ("disclaimer.short", "action.accept", "red_flag.banner"):
        assert catalog("uz")[key] != catalog("en")[key], key
        assert catalog("ru")[key] != catalog("en")[key], key


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "uz"),
        ("", "uz"),
        ("ru", "ru"),
        ("ru-RU,ru;q=0.9", "ru"),
        ("uz-Cyrl-UZ", "uz"),
        ("kaa", "uz"),
        ("en-US,en;q=0.8", "en"),
        ("fr-FR", "uz"),
        ("de;q=0.9,ru;q=0.95", "ru"),
        ("*", "uz"),
    ],
)
def test_accept_language_resolution(header, expected):
    assert resolve_language(header) == expected


def test_translate_falls_back_to_default_then_key():
    assert translate("action.accept", "ru") == "Принять"
    assert translate("no.such.key", "ru") == "no.such.key"


def test_translate_interpolates():
    assert "7" in translate("sync.pending", "uz", count=7)


def test_malformed_quality_value_does_not_raise():
    assert resolve_language("ru;q=abc,en") == "en"


def test_response_carries_content_language_and_disclaimer(client):
    response = client.get("/health/live", headers={"Accept-Language": "ru"})
    assert response.headers["Content-Language"] == "ru"
    assert response.headers["X-Clinical-Disclaimer"] == "not-a-diagnosis; clinician-review-required"
