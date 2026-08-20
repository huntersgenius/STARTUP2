"""Run every vignette set and report them side by side.

The single most misleading thing this repository could publish is one accuracy
number. `make eval-all` exists so that the in-vocabulary score and the
out-of-vocabulary score are produced by the same command, in the same table,
and are impossible to quote apart.

Run: `python -m app.ai.eval.summary [--html] [--provider baseline]`
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from app.ai import prompts
from app.ai.eval import metrics as metrics_module
from app.ai.eval.overlap import build_report as build_overlap
from app.ai.eval.report import write_combined_report
from app.ai.eval.run import CODE_PATHS, _provider
from app.ai.eval.runner import (
    VIGNETTE_SETS,
    load_vignettes,
    provenance_note,
    run_suite,
    write_results,
)

#: Order matters: the honest number comes second so it is read.
SET_ORDER = ("main", "oov", "adversarial", "injection")

SET_LABELS = {
    "main": "in-vocabulary (main)",
    "oov": "out-of-vocabulary",
    "adversarial": "adversarial red flags",
    "injection": "prompt injection",
}


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def run_all(provider_name: str = "baseline", prompt_version: str = "v1") -> dict[str, Any]:
    provider, model_name = _provider(provider_name)
    per_set: dict[str, Any] = {}

    for name in SET_ORDER:
        path = VIGNETTE_SETS[name]
        if not path.exists():
            continue
        results, lookup = run_suite(
            provider=provider,
            languages=("uz", "ru"),
            prompt_version=prompt_version,
            vignettes_path=path,
        )
        m = metrics_module.compute(results, lookup)
        vignettes = load_vignettes(path)
        per_set[name] = {
            "label": SET_LABELS[name],
            "vignettes": len(vignettes),
            "cases": m.cases,
            "advisor_reviewed": sum(1 for v in vignettes if v.reviewed_by == "advisor_reviewed"),
            "provenance_note": provenance_note(path),
            "metrics": m.to_dict(),
        }

    overlap = build_overlap()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": provider_name,
        "model": model_name,
        "code_path": CODE_PATHS[provider_name],
        "prompt_version": prompts.prompt_version(prompt_version),
        "sets": per_set,
        "overlap": overlap.to_dict(),
    }


def print_summary(payload: dict[str, Any]) -> None:
    print()
    print("=" * 88)
    print("  SihhatAI — all evaluation sets")
    print("=" * 88)
    print(f"  provider   {payload['provider']}  ({payload['model']})")
    print(f"  code path  {payload['code_path']}")
    print(f"  prompt     {payload['prompt_version']}")
    print("  corpus     every vignette is SYNTHETIC and unreviewed by a clinician")
    print("=" * 88)
    print()

    header = f"  {'set':<24}{'cases':>7}{'top-3':>9}{'top-1':>9}{'red-flag':>11}{'declined':>10}"
    print(header)
    print("  " + "-" * 68)
    for name in SET_ORDER:
        entry = payload["sets"].get(name)
        if not entry:
            continue
        m = entry["metrics"]
        declined = _pct(m["decline_recall"]) if m["should_have_declined"] else "—"
        print(
            f"  {entry['label']:<24}{m['cases']:>7}"
            f"{_pct(m['top3_lenient_accuracy']):>9}"
            f"{_pct(m['top1_accuracy']):>9}"
            f"{_pct(m['red_flag_recall']):>11}"
            f"{declined:>10}"
        )

    main = payload["sets"].get("main", {}).get("metrics")
    oov = payload["sets"].get("oov", {}).get("metrics")
    if main and oov:
        gap = main["top3_lenient_accuracy"] - oov["top3_lenient_accuracy"]
        flag_gap = main["red_flag_recall"] - oov["red_flag_recall"]
        print()
        print("  The gap is the measurement")
        print("  " + "-" * 68)
        print(
            f"    top-3 falls {gap * 100:.1f} points when the wording leaves the map"
            f"  ({_pct(main['top3_lenient_accuracy'])} -> {_pct(oov['top3_lenient_accuracy'])})"
        )
        print(
            f"    red-flag recall falls {flag_gap * 100:.1f} points"
            f"  ({_pct(main['red_flag_recall'])} -> {_pct(oov['red_flag_recall'])})"
        )

    adversarial = payload["sets"].get("adversarial", {}).get("metrics")
    if adversarial:
        print()
        print(
            f"    danger caught when paraphrased: "
            f"{_pct(adversarial['adversarial_danger_recall'])}"
            f"  ({adversarial['adversarial_danger_caught']}"
            f"/{adversarial['adversarial_danger_cases']})"
        )
        print(
            f"    decoys wrongly fired:           "
            f"{_pct(adversarial['adversarial_decoy_false_positive_rate'])}"
            f"  ({adversarial['adversarial_decoy_fired']}"
            f"/{adversarial['adversarial_decoy_cases']})"
        )

    overlap = payload["overlap"]
    main_overlap = next((s for s in overlap["sets"] if s["name"] == "main"), None)
    if main_overlap:
        print()
        print("  Why the in-vocabulary number is high")
        print("  " + "-" * 68)
        print(
            f"    {main_overlap['mean_surface_word_coverage'] * 100:.1f}% of each main-set "
            f"vignette's words are already terminology surfaces"
        )
        print(
            f"    {main_overlap['vignettes']} vignettes are "
            f"{main_overlap['distinct_templates']} distinct templates "
            f"({main_overlap['exact_duplicates']} exact duplicates)"
        )
        print(
            f"    {overlap['unused_surfaces']} of {overlap['total_surfaces']} terminology "
            f"surfaces are never exercised by any vignette"
        )
        if overlap["trivially_separable_categories"]:
            print(
                f"    {len(overlap['trivially_separable_categories'])} presentation classes are "
                f"identifiable by one shared phrase"
            )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run every evaluation set")
    parser.add_argument("--provider", default="baseline")
    parser.add_argument("--prompt-version", default=prompts.DEFAULT_VERSION)
    parser.add_argument("--html", action="store_true")
    args = parser.parse_args(argv)

    payload = run_all(args.provider, args.prompt_version)
    print_summary(payload)

    stamp = f"{datetime.now(UTC):%Y-%m-%d}-{args.provider}-all"
    path = write_results(payload, stamp=stamp)
    print(f"  written to {path}")
    if args.html:
        report = write_combined_report(payload)
        print(f"  report written to {report}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
