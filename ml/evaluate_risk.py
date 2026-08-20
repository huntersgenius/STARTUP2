"""Sensitivity and specificity of the risk scorer at its stated operating point.

Ground truth here is "the vignette carries a must-not-miss red flag", i.e. a
patient a clinician would want escalated. The scorer predicts positive when it
returns `high` or `very_high`.

Every caveat that applies to the rest of the evaluation applies doubly here:
the labels are synthetic, the vignettes were written by the same process as the
scorer's inputs, and on out-of-vocabulary text the concepts that feed the
scorer are largely not recognised at all — which is why the out-of-vocabulary
row below is the one worth looking at.

Run: `python -m ml.evaluate_risk`
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from knowledge.terminology import get_terminology

from app.ai.eval.runner import VIGNETTE_SETS, load_vignettes
from app.ai.eval.schema import Vignette
from app.ai.red_flags import CaseFacts, evaluate
from ml.risk_scoring import score_patient

POSITIVE_BANDS = {"high", "very_high"}


@dataclass
class Confusion:
    name: str
    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def total(self) -> int:
        return self.true_positive + self.false_positive + self.true_negative + self.false_negative

    @property
    def sensitivity(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else float("nan")

    @property
    def specificity(self) -> float:
        denominator = self.true_negative + self.false_positive
        return self.true_negative / denominator if denominator else float("nan")

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "set": self.name,
            "n": self.total,
            "tp": self.true_positive,
            "fp": self.false_positive,
            "tn": self.true_negative,
            "fn": self.false_negative,
            "sensitivity": self.sensitivity,
            "specificity": self.specificity,
        }


def _band(age: float | None) -> str:
    if age is None:
        return "unknown"
    for limit, name in (
        (1, "infant"),
        (5, "under5"),
        (12, "child"),
        (18, "adolescent"),
        (65, "adult"),
    ):
        if age < limit:
            return name
    return "elderly"


def score_vignette(vignette: Vignette) -> tuple[str, list[str]]:
    """Score one vignette exactly as the engine would, from its Uzbek text."""
    mapping = get_terminology()
    concepts = set(mapping.clinical_concepts(vignette.text_uz))
    facts = CaseFacts(
        concepts=concepts,
        age_years=vignette.age_years,
        age_band=_band(vignette.age_years),
        sex=vignette.sex,
        pregnant=vignette.pregnant,
        temperature_c=_num(vignette.vitals.get("temperature_c")),
        pulse_bpm=_int(vignette.vitals.get("pulse_bpm")),
        systolic_bp=_int(vignette.vitals.get("systolic_bp")),
        diastolic_bp=_int(vignette.vitals.get("diastolic_bp")),
        respiratory_rate=_int(vignette.vitals.get("respiratory_rate")),
        spo2=_int(vignette.vitals.get("spo2")),
        glucose_mmol=_num(vignette.vitals.get("glucose_mmol")),
        duration_days=vignette.duration_days,
    )
    fired = [flag.code for flag in evaluate(facts)]
    assessment = score_patient(
        concepts=concepts,
        age_years=vignette.age_years,
        vitals=vignette.vitals,
        chronic_flags=vignette.chronic_flags,
        red_flag_codes=fired,
        pregnant=vignette.pregnant,
    )
    return assessment.band, fired


def _num(value: object) -> float | None:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def confusion_for(name: str, vignettes: list[Vignette]) -> Confusion:
    confusion = Confusion(name=name)
    for vignette in vignettes:
        band, _ = score_vignette(vignette)
        predicted_high = band in POSITIVE_BANDS
        actually_high = bool(vignette.must_not_miss)
        if predicted_high and actually_high:
            confusion.true_positive += 1
        elif predicted_high and not actually_high:
            confusion.false_positive += 1
        elif not predicted_high and actually_high:
            confusion.false_negative += 1
        else:
            confusion.true_negative += 1
    return confusion


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Risk scorer sensitivity / specificity")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = []
    for name in ("main", "oov", "adversarial"):
        path = VIGNETTE_SETS[name]
        if not path.exists():
            continue
        results.append(confusion_for(name, load_vignettes(path)))

    if args.json:
        print(json.dumps([c.to_dict() for c in results], indent=2))
        return 0

    print()
    print("=" * 74)
    print("  Risk scorer — operating point: predict high/very_high")
    print("=" * 74)
    print("  Ground truth: the vignette carries a must-not-miss red flag.")
    print("  Tuned to avoid missing a high-risk patient, at the cost of")
    print("  flagging low-risk ones. Labels are SYNTHETIC.")
    print()
    print(f"  {'set':<16}{'n':>6}{'sens':>9}{'spec':>9}{'TP':>6}{'FN':>6}{'FP':>6}{'TN':>6}")
    print("  " + "-" * 62)
    for confusion in results:
        print(
            f"  {confusion.name:<16}{confusion.total:>6}"
            f"{confusion.sensitivity * 100:>8.1f}%"
            f"{confusion.specificity * 100:>8.1f}%"
            f"{confusion.true_positive:>6}{confusion.false_negative:>6}"
            f"{confusion.false_positive:>6}{confusion.true_negative:>6}"
        )
    print()
    print("  The out-of-vocabulary row is the one that matters: the scorer reads")
    print("  concepts produced by the terminology map, and on text outside that")
    print("  map most concepts are never recognised, so the score has little to")
    print("  work with. Read it as the floor, not the expectation.")
    print()

    path = Path(__file__).parent / "risk_operating_point.json"
    path.write_text(json.dumps([c.to_dict() for c in results], indent=2), encoding="utf-8")
    print(f"  written to {path}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
