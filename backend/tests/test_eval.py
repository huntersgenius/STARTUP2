"""Tests for the evaluation harness itself.

An eval suite that is wrong is worse than none: it certifies a system nobody
checked. These tests assert the metrics actually measure what they claim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.eval import metrics as metrics_module
from app.ai.eval.report import write_report
from app.ai.eval.runner import VIGNETTES_PATH, load_vignettes
from app.ai.eval.schema import CaseResult, Vignette
from app.ai.providers.baseline import RetrievalBaselineProvider

pytestmark = pytest.mark.eval


def _vignette(**kw) -> Vignette:
    base = {
        "id": "v1",
        "category": "test",
        "text_uz": "yo'tal",
        "text_ru": "кашель",
        "age_years": 40,
        "sex": "male",
        "vitals": {},
        "ground_truth_icd10": "J18.9",
        "ground_truth_label": "Pneumonia",
    }
    base.update(kw)
    return Vignette(**base)


def _result(**kw) -> CaseResult:
    base = {
        "vignette_id": "v1",
        "language": "uz",
        "category": "test",
        "predicted_codes": ["J18.9"],
        "predicted_labels": ["Pneumonia"],
        "confidences": [0.8],
        "fired_red_flags": [],
        "referral_needed": False,
        "latency_ms": 100,
        "cost_usd": 0.001,
        "degraded": False,
        "insufficient_data": False,
    }
    base.update(kw)
    return CaseResult(**base)


# --- the vignette set ----------------------------------------------------


def test_vignette_set_is_large_and_covers_the_target_conditions():
    vignettes = load_vignettes()
    assert len(vignettes) >= 200
    categories = {v.category for v in vignettes}
    # The 10 presentations named in BUSINESS_PLAN.md.
    for required in (
        "respiratory_infection",
        "hypertension",
        "type2_diabetes",
        "anemia",
        "gastritis_hpylori",
        "tb_suspicion",
        "iodine_deficiency",
        "pediatric_diarrhea",
        "musculoskeletal_pain",
        "cardiovascular_risk",
    ):
        assert required in categories, required


def test_every_vignette_is_bilingual_and_complete():
    for vignette in load_vignettes():
        assert len(vignette.text_uz) > 15, vignette.id
        assert len(vignette.text_ru) > 15, vignette.id
        assert vignette.text_uz != vignette.text_ru, vignette.id
        assert vignette.ground_truth_icd10
        assert vignette.ground_truth_label
        assert vignette.sex in ("male", "female", "unknown")
        assert 0 < vignette.age_years < 110


def test_provenance_is_explicit_on_every_vignette():
    # A number from an unreviewed set must never be mistaken for a clinical
    # result. Provenance is per-vignette so a partially reviewed set is honest.
    for vignette in load_vignettes():
        assert vignette.reviewed_by in ("synthetic", "advisor_reviewed")
    payload = json.loads(Path(VIGNETTES_PATH).read_text(encoding="utf-8"))
    assert "SYNTHETIC" in payload["provenance_note"]


def test_a_meaningful_share_of_vignettes_test_safety():
    vignettes = load_vignettes()
    with_flags = [v for v in vignettes if v.must_not_miss]
    # Red-flag recall is the metric that matters most; it needs real coverage.
    assert len(with_flags) >= 40
    assert len({code for v in with_flags for code in v.must_not_miss}) >= 8


def test_over_triage_is_measured_too():
    # Without must_not_fire, a system that refers everyone scores perfectly.
    vignettes = load_vignettes()
    assert sum(1 for v in vignettes if v.must_not_fire) >= 40


# --- metrics -------------------------------------------------------------


def test_top1_and_top3_distinguish_position():
    vignettes = {"v1": _vignette()}
    exact = metrics_module.compute([_result(predicted_codes=["J18.9"])], vignettes)
    assert exact.top1_accuracy == 1.0
    assert exact.top3_accuracy == 1.0

    third = metrics_module.compute([_result(predicted_codes=["J40", "J00", "J18.9"])], vignettes)
    assert third.top1_accuracy == 0.0
    assert third.top3_accuracy == 1.0


def test_acceptable_alternatives_count_as_correct_only_in_lenient():
    vignettes = {"v1": _vignette(acceptable_alternatives=["J15.9"])}
    m = metrics_module.compute([_result(predicted_codes=["J15.9"])], vignettes)
    assert m.top3_accuracy == 0.0
    assert m.top3_lenient_accuracy == 1.0


def test_red_flag_recall_counts_a_miss():
    vignettes = {"v1": _vignette(must_not_miss=["acs_suspected"])}
    caught = metrics_module.compute([_result(fired_red_flags=["acs_suspected"])], vignettes)
    assert caught.red_flag_recall == 1.0

    missed = metrics_module.compute([_result(fired_red_flags=[])], vignettes)
    assert missed.red_flag_recall == 0.0
    assert missed.missed_red_flags[0]["expected"] == "acs_suspected"


def test_false_red_flags_are_counted():
    vignettes = {"v1": _vignette(must_not_fire=["acs_suspected"])}
    m = metrics_module.compute([_result(fired_red_flags=["acs_suspected"])], vignettes)
    assert m.false_red_flags == 1


def test_false_referral_rate_penalises_over_triage():
    vignettes = {"v1": _vignette()}  # no red flag expected
    m = metrics_module.compute([_result(referral_needed=True)], vignettes)
    assert m.false_referral_rate == 1.0


def test_calibration_error_rewards_honest_confidence():
    # Perfectly calibrated: says 1.0 and is always right.
    perfect = metrics_module.expected_calibration_error([(1.0, True)] * 10)
    # Badly calibrated: says 0.95 and is right half the time.
    bad = metrics_module.expected_calibration_error([(0.95, True)] * 5 + [(0.95, False)] * 5)
    assert perfect < 0.01
    assert bad > 0.4


def test_language_gap_is_signed_and_reported():
    vignettes = {"v1": _vignette(), "v2": _vignette(id="v2")}
    results = [
        _result(vignette_id="v1", language="uz", predicted_codes=["J18.9"]),
        _result(vignette_id="v1", language="ru", predicted_codes=["WRONG"]),
        _result(vignette_id="v2", language="uz", predicted_codes=["J18.9"]),
        _result(vignette_id="v2", language="ru", predicted_codes=["WRONG"]),
    ]
    m = metrics_module.compute(results, vignettes)
    assert m.uz_top3 == 1.0
    assert m.ru_top3 == 0.0
    assert m.language_gap == pytest.approx(1.0)


def test_percentiles_are_sane():
    vignettes = {"v1": _vignette()}
    results = [_result(latency_ms=ms) for ms in range(1, 101)]
    m = metrics_module.compute(results, vignettes)
    assert 45 <= m.p50_latency_ms <= 55
    assert 90 <= m.p95_latency_ms <= 100


def test_empty_run_does_not_crash():
    assert metrics_module.compute([], {}).cases == 0


# --- the baseline provider ----------------------------------------------


def test_baseline_parses_the_current_prompt_template():
    """The baseline reads our own prompt format; a template change must fail here."""
    from app.ai import prompts

    template = prompts.load("diagnose")
    for marker in (
        "Recognised clinical concepts:",
        "Age band:",
        "## Deterministic red flags already fired",
        "{protocol_excerpts}",
    ):
        assert marker in template, f"baseline provider depends on {marker!r}"


def test_baseline_returns_schema_valid_json():
    from app.ai.schema import parse_response

    user = (
        "Age band: adult\n"
        "Recognised clinical concepts: productive_cough, fever\n"
        "## Deterministic red flags already fired\n\nNone.\n\n"
        "[abc12345] (WHO · protocol)\ntext"
    )
    response = RetrievalBaselineProvider().complete(system="s", user=user)
    suggestion = parse_response(response.text)
    assert suggestion.differentials
    assert suggestion.differentials[0].citations == ["abc12345"]


def test_baseline_cites_nothing_when_nothing_was_retrieved():
    from app.ai.schema import parse_response

    user = (
        "Age band: adult\n"
        "Recognised clinical concepts: productive_cough, fever\n"
        "## Deterministic red flags already fired\n\nNone.\n"
    )
    suggestion = parse_response(RetrievalBaselineProvider().complete(system="s", user=user).text)
    # No excerpts means no citation is possible, so no differential may be made.
    assert suggestion.differentials == []


def test_baseline_is_free_and_deterministic():
    user = "Age band: adult\nRecognised clinical concepts: fever\n[abc12345] x"
    provider = RetrievalBaselineProvider()
    first = provider.complete(system="s", user=user)
    second = provider.complete(system="s", user=user)
    assert first.text == second.text
    assert first.cost_usd == 0.0


# --- the report ----------------------------------------------------------


def test_report_states_provenance_prominently(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ai.eval.report.RESULTS_DIR", tmp_path)
    payload = {
        "label": "test run",
        "prompt_version": "v1@abc",
        "generated_at": "2026-08-19T10:00:00+00:00",
        "vignettes": {
            "total": 200,
            "advisor_reviewed": 0,
            "synthetic": 200,
            "provenance_note": "Every vignette is SYNTHETIC.",
        },
        "metrics": metrics_module.Metrics().to_dict(),
    }
    path = write_report(payload, {})
    html = path.read_text(encoding="utf-8")
    assert "SYNTHETIC" in html
    assert "not clinical validation" in html
    # The banner must appear before the headline numbers.
    assert html.index("Provenance") < html.index("Top-3 accuracy")
