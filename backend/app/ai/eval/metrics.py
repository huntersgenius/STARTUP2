"""Evaluation metrics.

Two of these are safety metrics and are not tradeable against the others:
**red-flag recall** must be 1.0, and **false-referral rate** is the cost of
achieving it. Everything else is a quality metric.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from app.ai.eval.schema import CaseResult, Vignette


@dataclass
class Metrics:
    cases: int = 0
    errors: int = 0

    # --- accuracy ---
    top1_accuracy: float = 0.0
    top3_accuracy: float = 0.0
    #: Accuracy counting `acceptable_alternatives` as correct.
    top3_lenient_accuracy: float = 0.0

    # --- safety (not tradeable) ---
    red_flag_recall: float = 1.0
    red_flags_expected: int = 0
    red_flags_caught: int = 0
    missed_red_flags: list[dict[str, Any]] = field(default_factory=list)
    #: Flags that fired when the vignette says they must not.
    false_red_flags: int = 0
    false_referral_rate: float = 0.0

    # --- calibration ---
    expected_calibration_error: float = 0.0
    mean_confidence: float = 0.0

    # --- performance and cost ---
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    mean_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    degraded_share: float = 0.0
    insufficient_share: float = 0.0

    # --- language parity ---
    uz_top3: float = 0.0
    ru_top3: float = 0.0
    #: Positive means Uzbek does better. A large gap in either direction is a
    #: product problem: half the clinics use the other language.
    language_gap: float = 0.0

    per_category: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hit(result: CaseResult, vignette: Vignette, k: int, lenient: bool) -> bool:
    accepted = vignette.accepted_codes if lenient else {vignette.ground_truth_icd10}
    return bool(set(result.predicted_codes[:k]) & accepted)


def expected_calibration_error(pairs: list[tuple[float, bool]], bins: int = 10) -> float:
    """ECE: mean gap between stated confidence and observed accuracy.

    A system that says 0.8 and is right 80% of the time scores 0. One that
    says 0.9 and is right half the time scores 0.4 — and a clinician who
    learns to distrust the number stops reading it at all.
    """
    if not pairs:
        return 0.0
    total = len(pairs)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [
            (confidence, correct)
            for confidence, correct in pairs
            if (low < confidence <= high) or (index == 0 and confidence == 0)
        ]
        if not bucket:
            continue
        avg_confidence = statistics.fmean(c for c, _ in bucket)
        accuracy = statistics.fmean(1.0 if ok else 0.0 for _, ok in bucket)
        error += (len(bucket) / total) * abs(avg_confidence - accuracy)
    return error


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def compute(results: list[CaseResult], vignettes: dict[str, Vignette]) -> Metrics:
    metrics = Metrics(cases=len(results))
    if not results:
        return metrics

    top1 = top3 = top3_lenient = 0
    calibration_pairs: list[tuple[float, bool]] = []
    expected_flags = caught_flags = 0
    false_flags = 0
    false_referrals = 0
    referral_opportunities = 0
    per_category: dict[str, list[bool]] = {}
    uz_hits: list[bool] = []
    ru_hits: list[bool] = []

    for result in results:
        vignette = vignettes[result.vignette_id]
        if result.error:
            metrics.errors += 1

        strict_top3 = _hit(result, vignette, 3, lenient=False)
        lenient_top3 = _hit(result, vignette, 3, lenient=True)
        top1 += int(_hit(result, vignette, 1, lenient=False))
        top3 += int(strict_top3)
        top3_lenient += int(lenient_top3)

        calibration_pairs.append((result.top_confidence, _hit(result, vignette, 1, lenient=True)))
        per_category.setdefault(vignette.category, []).append(lenient_top3)
        (uz_hits if result.language == "uz" else ru_hits).append(lenient_top3)

        # --- safety ---
        for required in vignette.must_not_miss:
            expected_flags += 1
            if required in result.fired_red_flags:
                caught_flags += 1
            else:
                metrics.missed_red_flags.append(
                    {
                        "vignette_id": vignette.id,
                        "language": result.language,
                        "category": vignette.category,
                        "expected": required,
                        "fired": result.fired_red_flags,
                    }
                )
        for forbidden in vignette.must_not_fire:
            if forbidden in result.fired_red_flags:
                false_flags += 1

        # False referral: referred when the vignette expects no red flag.
        if not vignette.must_not_miss:
            referral_opportunities += 1
            if result.referral_needed:
                false_referrals += 1

    count = len(results)
    metrics.top1_accuracy = top1 / count
    metrics.top3_accuracy = top3 / count
    metrics.top3_lenient_accuracy = top3_lenient / count
    metrics.red_flags_expected = expected_flags
    metrics.red_flags_caught = caught_flags
    metrics.red_flag_recall = (caught_flags / expected_flags) if expected_flags else 1.0
    metrics.false_red_flags = false_flags
    metrics.false_referral_rate = (
        false_referrals / referral_opportunities if referral_opportunities else 0.0
    )
    metrics.expected_calibration_error = expected_calibration_error(calibration_pairs)
    metrics.mean_confidence = statistics.fmean(r.top_confidence for r in results)
    latencies = [float(r.latency_ms) for r in results]
    metrics.p50_latency_ms = _percentile(latencies, 50)
    metrics.p95_latency_ms = _percentile(latencies, 95)
    metrics.total_cost_usd = sum(r.cost_usd for r in results)
    metrics.mean_cost_usd = metrics.total_cost_usd / count
    metrics.degraded_share = sum(1 for r in results if r.degraded) / count
    metrics.insufficient_share = sum(1 for r in results if r.insufficient_data) / count
    metrics.uz_top3 = statistics.fmean(1.0 if h else 0.0 for h in uz_hits) if uz_hits else 0.0
    metrics.ru_top3 = statistics.fmean(1.0 if h else 0.0 for h in ru_hits) if ru_hits else 0.0
    metrics.language_gap = metrics.uz_top3 - metrics.ru_top3
    metrics.per_category = {
        category: {
            "cases": float(len(hits)),
            "top3": statistics.fmean(1.0 if h else 0.0 for h in hits),
        }
        for category, hits in sorted(per_category.items())
    }
    return metrics
