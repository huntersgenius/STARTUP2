"""A/B harness: compare two prompt versions or two models on the same set.

Runs both arms over identical vignettes in identical order, so a difference is
attributable to the arm and not to sampling. Reports per-metric deltas and,
critically, flags any case where arm B misses a red flag that arm A caught —
a top-3 improvement that costs a missed red flag is a regression, not a win.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.ai.eval import metrics as metrics_module
from app.ai.eval.runner import RESULTS_DIR, run_suite
from app.ai.eval.schema import CaseResult, Vignette
from app.ai.providers.base import LlmProvider
from app.ai.providers.baseline import RetrievalBaselineProvider


@dataclass
class Arm:
    name: str
    provider: LlmProvider
    prompt_version: str = "v1"


@dataclass
class Comparison:
    arm_a: str
    arm_b: str
    metrics_a: metrics_module.Metrics
    metrics_b: metrics_module.Metrics
    #: Red flags arm A caught and arm B missed. Any entry here blocks a switch.
    safety_regressions: list[dict[str, Any]]
    #: Cases where A was right and B was wrong, and vice versa.
    a_only_correct: list[str]
    b_only_correct: list[str]

    @property
    def is_safe_to_switch(self) -> bool:
        return (
            not self.safety_regressions
            and self.metrics_b.red_flag_recall >= self.metrics_a.red_flag_recall
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_a": self.arm_a,
            "arm_b": self.arm_b,
            "metrics_a": self.metrics_a.to_dict(),
            "metrics_b": self.metrics_b.to_dict(),
            "deltas": {
                "top1_accuracy": self.metrics_b.top1_accuracy - self.metrics_a.top1_accuracy,
                "top3_accuracy": self.metrics_b.top3_lenient_accuracy
                - self.metrics_a.top3_lenient_accuracy,
                "red_flag_recall": self.metrics_b.red_flag_recall - self.metrics_a.red_flag_recall,
                "false_referral_rate": self.metrics_b.false_referral_rate
                - self.metrics_a.false_referral_rate,
                "ece": self.metrics_b.expected_calibration_error
                - self.metrics_a.expected_calibration_error,
                "mean_cost_usd": self.metrics_b.mean_cost_usd - self.metrics_a.mean_cost_usd,
                "p95_latency_ms": self.metrics_b.p95_latency_ms - self.metrics_a.p95_latency_ms,
            },
            "safety_regressions": self.safety_regressions,
            "a_only_correct": self.a_only_correct,
            "b_only_correct": self.b_only_correct,
            "safe_to_switch": self.is_safe_to_switch,
        }


def _correct(result: CaseResult, vignette: Vignette) -> bool:
    return bool(set(result.predicted_codes[:3]) & vignette.accepted_codes)


def compare(
    arm_a: Arm,
    arm_b: Arm,
    *,
    languages: tuple[str, ...] = ("uz", "ru"),
    limit: int | None = None,
) -> Comparison:
    results_a, lookup = run_suite(
        provider=arm_a.provider,
        languages=languages,
        limit=limit,
        prompt_version=arm_a.prompt_version,
    )
    results_b, _ = run_suite(
        provider=arm_b.provider,
        languages=languages,
        limit=limit,
        prompt_version=arm_b.prompt_version,
    )

    by_key_a = {(r.vignette_id, r.language): r for r in results_a}
    by_key_b = {(r.vignette_id, r.language): r for r in results_b}

    safety_regressions: list[dict[str, Any]] = []
    a_only: list[str] = []
    b_only: list[str] = []

    for key, result_a in by_key_a.items():
        result_b = by_key_b.get(key)
        if result_b is None:
            continue
        vignette = lookup[result_a.vignette_id]

        for required in vignette.must_not_miss:
            caught_a = required in result_a.fired_red_flags
            caught_b = required in result_b.fired_red_flags
            if caught_a and not caught_b:
                safety_regressions.append(
                    {
                        "vignette_id": result_a.vignette_id,
                        "language": result_a.language,
                        "red_flag": required,
                    }
                )

        correct_a, correct_b = _correct(result_a, vignette), _correct(result_b, vignette)
        if correct_a and not correct_b:
            a_only.append(f"{result_a.vignette_id}:{result_a.language}")
        elif correct_b and not correct_a:
            b_only.append(f"{result_a.vignette_id}:{result_a.language}")

    return Comparison(
        arm_a=arm_a.name,
        arm_b=arm_b.name,
        metrics_a=metrics_module.compute(results_a, lookup),
        metrics_b=metrics_module.compute(results_b, lookup),
        safety_regressions=safety_regressions,
        a_only_correct=sorted(a_only),
        b_only_correct=sorted(b_only),
    )


def print_comparison(comparison: Comparison) -> None:
    payload = comparison.to_dict()
    print()
    print("=" * 72)
    print(f"  A/B: {comparison.arm_a}  vs  {comparison.arm_b}")
    print("=" * 72)
    for label, key, fmt in [
        ("Top-1 accuracy", "top1_accuracy", "pct"),
        ("Top-3 accuracy", "top3_accuracy", "pct"),
        ("Red-flag recall  [SAFETY]", "red_flag_recall", "pct"),
        ("False-referral rate", "false_referral_rate", "pct"),
        ("Calibration error", "ece", "raw"),
        ("Mean cost", "mean_cost_usd", "usd"),
        ("p95 latency", "p95_latency_ms", "ms"),
    ]:
        delta = payload["deltas"][key]
        if fmt == "pct":
            shown = f"{delta * 100:+.1f} pp"
        elif fmt == "usd":
            shown = f"${delta:+.4f}"
        elif fmt == "ms":
            shown = f"{delta:+.0f} ms"
        else:
            shown = f"{delta:+.3f}"
        print(f"  {label:<34} {shown}")

    print()
    print(f"  Cases only A got right: {len(comparison.a_only_correct)}")
    print(f"  Cases only B got right: {len(comparison.b_only_correct)}")

    if comparison.safety_regressions:
        print()
        print(f"  !! {len(comparison.safety_regressions)} SAFETY REGRESSIONS — do not switch")
        for regression in comparison.safety_regressions[:10]:
            print(
                f"     {regression['vignette_id']} [{regression['language']}]: "
                f"{regression['red_flag']}"
            )
    else:
        print()
        print("  No safety regression: arm B misses no red flag that arm A caught.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two evaluation arms")
    parser.add_argument("--prompt-a", default="v1")
    parser.add_argument("--prompt-b", default="v1")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    comparison = compare(
        Arm(f"prompt {args.prompt_a}", RetrievalBaselineProvider(), args.prompt_a),
        Arm(f"prompt {args.prompt_b}", RetrievalBaselineProvider(), args.prompt_b),
        limit=args.limit,
    )
    print_comparison(comparison)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    path = RESULTS_DIR / f"ab-{stamp}.json"
    path.write_text(
        json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  written to {path}\n")
    return 0 if comparison.is_safe_to_switch else 1


if __name__ == "__main__":
    raise SystemExit(main())
