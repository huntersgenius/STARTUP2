"""`make eval` entry point.

Prints a table, writes `eval/results/<date>.json`, and fails the build when
top-3 accuracy or red-flag recall drops below the configured floor.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from app.ai import prompts
from app.ai.eval import metrics as metrics_module
from app.ai.eval.report import write_report
from app.ai.eval.runner import load_vignettes, provenance_note, run_suite, write_results
from app.ai.providers.base import LlmProvider
from app.ai.providers.baseline import RetrievalBaselineProvider


def _provider(name: str) -> tuple[LlmProvider, str]:
    if name == "baseline":
        return RetrievalBaselineProvider(), "rules-baseline-v1"
    if name == "openai":
        from app.ai.providers.llm import OpenAIProvider

        openai_provider = OpenAIProvider()
        return openai_provider, openai_provider.model
    if name == "anthropic":
        from app.ai.providers.llm import AnthropicProvider

        anthropic_provider = AnthropicProvider()
        return anthropic_provider, anthropic_provider.model
    if name == "local":
        from app.ai.providers.llm import LocalLlamaProvider

        local_provider = LocalLlamaProvider()
        return local_provider, local_provider.model
    raise SystemExit(f"unknown provider {name!r}")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def print_table(name: str, m: metrics_module.Metrics) -> None:
    print()
    print("=" * 72)
    print(f"  SihhatAI evaluation — {name}")
    print("=" * 72)
    rows = [
        ("Cases run", str(m.cases)),
        ("Errors", str(m.errors)),
        ("", ""),
        ("Top-1 accuracy (strict)", _pct(m.top1_accuracy)),
        ("Top-3 accuracy (strict)", _pct(m.top3_accuracy)),
        ("Top-3 accuracy (with acceptable alternatives)", _pct(m.top3_lenient_accuracy)),
        ("", ""),
        (
            "Red-flag recall  [SAFETY]",
            f"{_pct(m.red_flag_recall)}  ({m.red_flags_caught}/{m.red_flags_expected})",
        ),
        ("Red flags that fired wrongly", str(m.false_red_flags)),
        ("False-referral rate", _pct(m.false_referral_rate)),
        ("", ""),
        ("Calibration error (ECE, lower is better)", f"{m.expected_calibration_error:.3f}"),
        ("Mean top confidence", f"{m.mean_confidence:.3f}"),
        ("", ""),
        ("p50 latency", f"{m.p50_latency_ms:.0f} ms"),
        ("p95 latency", f"{m.p95_latency_ms:.0f} ms"),
        ("Mean cost per case", f"${m.mean_cost_usd:.4f}"),
        ("Total cost", f"${m.total_cost_usd:.2f}"),
        ("Degraded responses", _pct(m.degraded_share)),
        ("Insufficient-data responses", _pct(m.insufficient_share)),
        ("", ""),
        ("Uzbek top-3", _pct(m.uz_top3)),
        ("Russian top-3", _pct(m.ru_top3)),
        ("Language gap (uz − ru)", f"{m.language_gap * 100:+.1f} pp"),
    ]
    for label, value in rows:
        if not label:
            print()
            continue
        print(f"  {label:<46} {value}")

    print()
    print("  By presentation")
    print("  " + "-" * 52)
    for category, stats in m.per_category.items():
        print(f"    {category:<28} {_pct(stats['top3']):>7}   n={int(stats['cases'])}")

    if m.missed_red_flags:
        print()
        print(f"  !! {len(m.missed_red_flags)} MISSED RED FLAGS")
        for miss in m.missed_red_flags[:10]:
            print(f"     {miss['vignette_id']} [{miss['language']}] expected {miss['expected']}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SihhatAI evaluation suite")
    parser.add_argument(
        "--provider",
        default="baseline",
        choices=["baseline", "openai", "anthropic", "local"],
        help="which model to evaluate (default: the offline rules baseline)",
    )
    parser.add_argument("--offline", action="store_true", help="alias for --provider baseline")
    parser.add_argument("--languages", default="uz,ru")
    parser.add_argument(
        "--limit", type=int, default=None, help="evaluate only the first N vignettes"
    )
    parser.add_argument("--prompt-version", default=prompts.DEFAULT_VERSION)
    parser.add_argument("--fail-under-top3", type=float, default=None)
    parser.add_argument("--fail-under-redflag", type=float, default=None)
    parser.add_argument("--html", action="store_true", help="also write eval/report.html")
    parser.add_argument("--label", default=None, help="name this run in the report")
    args = parser.parse_args(argv)

    provider_name = "baseline" if args.offline else args.provider
    provider, model_name = _provider(provider_name)
    languages = tuple(lang.strip() for lang in args.languages.split(",") if lang.strip())

    results, lookup = run_suite(
        provider=provider,
        languages=languages,
        limit=args.limit,
        prompt_version=args.prompt_version,
    )
    m = metrics_module.compute(results, lookup)

    label = args.label or f"{provider_name} ({model_name})"
    print_table(label, m)

    vignettes = load_vignettes()
    reviewed = sum(1 for v in vignettes if v.reviewed_by == "advisor_reviewed")
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "label": label,
        "provider": provider_name,
        "model": model_name,
        "prompt_version": prompts.prompt_version(args.prompt_version),
        "languages": list(languages),
        "vignettes": {
            "total": len(vignettes),
            "advisor_reviewed": reviewed,
            "synthetic": len(vignettes) - reviewed,
            "provenance_note": provenance_note(),
        },
        "metrics": m.to_dict(),
        "cases": [
            {
                "vignette_id": r.vignette_id,
                "language": r.language,
                "category": r.category,
                "predicted": r.predicted_codes,
                "confidences": r.confidences,
                "red_flags": r.fired_red_flags,
                "referral": r.referral_needed,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd,
                "degraded": r.degraded,
                "error": r.error,
            }
            for r in results
        ],
    }
    path = write_results(payload)
    print(f"  results written to {path}")

    if args.html:
        report = write_report(payload, lookup)
        print(f"  report written to {report}")

    # --- gates -----------------------------------------------------------
    failures: list[str] = []
    if args.fail_under_top3 is not None and m.top3_lenient_accuracy < args.fail_under_top3:
        failures.append(
            f"top-3 accuracy {_pct(m.top3_lenient_accuracy)} is below the floor "
            f"{_pct(args.fail_under_top3)}"
        )
    if args.fail_under_redflag is not None and m.red_flag_recall < args.fail_under_redflag:
        failures.append(
            f"red-flag recall {_pct(m.red_flag_recall)} is below the floor "
            f"{_pct(args.fail_under_redflag)} — this is a safety regression"
        )

    if failures:
        print("  EVALUATION GATE FAILED")
        for failure in failures:
            print(f"    - {failure}")
        print()
        return 1

    if reviewed == 0:
        # Never let a green run be mistaken for clinical validation.
        print("  NOTE: every vignette is synthetic and unreviewed by a clinician.")
        print("        These numbers describe engineering behaviour, not clinical accuracy.")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
