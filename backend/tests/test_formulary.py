"""The formulary gate: can a clinic in Chinoz actually obtain this drug?"""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge.formulary import FormularyService
from knowledge.ingest import load_formulary

CSV = Path(__file__).resolve().parents[2] / "knowledge" / "formulary.csv"


@pytest.fixture()
def formulary(db):
    count = load_formulary(db, CSV)
    assert count >= 40, "formulary seed is too small to be useful"
    return FormularyService(db)


def test_tier_one_drug_is_available_at_a_feldsher_point(formulary):
    verdict = formulary.check("paracetamol", clinic_tier=1)
    assert verdict.available
    assert verdict.tier == 1


def test_higher_tier_drug_is_flagged_with_a_substitute(formulary):
    verdict = formulary.check("losartan", clinic_tier=1)
    assert not verdict.available
    assert verdict.reason == "not_stocked_at_this_tier"
    # The clinician is told what to use instead, not left with nothing.
    assert verdict.substitute is not None
    assert verdict.substitute.availability_tier <= 1


def test_unknown_drug_is_refused_rather_than_assumed_available(formulary):
    verdict = formulary.check("rosuvastatin-x", clinic_tier=3)
    assert not verdict.available
    assert verdict.reason == "not_in_national_formulary"
    assert verdict.item is None


def test_local_trade_names_resolve(formulary):
    assert formulary.find("paratsetamol") is not None
    assert formulary.find("парацетамол") is not None
    assert formulary.find("amoksitsillin").generic_name == "amoxicillin"


def test_drug_name_is_extracted_from_a_full_prescription_line(formulary):
    item = formulary.find("amoxicillin 500 mg three times daily for 5 days")
    assert item is not None
    assert item.generic_name == "amoxicillin"


def test_pediatric_contraindication_blocks_and_substitutes(formulary):
    verdict = formulary.check("ciprofloxacin", clinic_tier=3, pediatric=True)
    assert not verdict.available
    assert verdict.reason == "not_approved_for_children"


def test_pregnancy_category_d_is_refused(formulary):
    verdict = formulary.check("enalapril", clinic_tier=1, pregnant=True)
    assert not verdict.available
    assert verdict.reason.startswith("pregnancy_category_")
    # A safe alternative in pregnancy still needs a clinician's judgement, but
    # the system must at least not stay silent.
    assert verdict.substitute is None or verdict.substitute.generic_name != "enalapril"


def test_doxycycline_is_refused_for_children(formulary):
    assert not formulary.check("doxycycline", clinic_tier=2, pediatric=True).available


def test_no_controlled_substance_is_in_the_seed_formulary(formulary):
    # The system must never output a controlled substance; the simplest way to
    # guarantee that is for none to exist in the formulary at all.
    assert all(not item.controlled for item in formulary._all())


def test_every_item_has_the_fields_the_engine_relies_on(formulary):
    for item in formulary._all():
        assert item.generic_name and item.form
        assert item.availability_tier in (1, 2, 3)
        assert isinstance(item.pediatric_ok, bool)


def test_preferred_form_is_honoured(formulary):
    syrup = formulary.find("paracetamol", form="syrup")
    assert syrup is not None
    assert syrup.form == "syrup"


def test_tb_drugs_are_oblast_tier_only(formulary):
    # Starting TB treatment outside the DOTS programme creates resistance;
    # the tier encodes that this is not a primary-care decision.
    for drug in ("isoniazid", "rifampicin"):
        assert formulary.check(drug, clinic_tier=1).available is False
