"""`make eval` entry point.

Prints a table, writes `eval/results/<date>.json`, and fails the build when
top-3 accuracy or red-flag recall drops below the configured floor.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from app.ai import prompts
from app.ai.eval import metrics as metrics_module
from app.ai.eval.report import write_report
from app.ai.eval.runner import (
    VIGNETTE_SETS,
    load_vignettes,
    provenance_note,
    resolve_set,
    run_suite,
    stratified_subset,
    write_results,
)
from app.ai.providers.base import LlmProvider
from app.ai.providers.baseline import RetrievalBaselineProvider

#: What each provider name actually exercises. Printed above every result so a
#: baseline number cannot be read as an engine number.
CODE_PATHS: dict[str, str] = {
    "baseline": "deterministic rules baseline (no model called)",
    "openai": "full eight-stage engine, GPT-4o",
    "anthropic": "full eight-stage engine, Claude",
    "local": "full eight-stage engine, self-hosted Llama",
}


class ProviderUnavailable(SystemExit):
    """A model-path run was requested with no way to call the model.

    This exits rather than degrading, because the alternative is what this
    tool did on its first attempt: fall through to the rules layer and print a
    full results table that reads as a model evaluation. A gate that reports
    numbers when it measured nothing is worse than a gate that fails.
    """


def _provider(name: str) -> tuple[LlmProvider, str]:
    if name == "baseline":
        return RetrievalBaselineProvider(), "rules-baseline-v1"
    if name == "openai":
        from app.ai.providers.llm import OpenAIProvider

        openai_provider = OpenAIProvider()
        _require_available(openai_provider, name, "OPENAI_API_KEY")
        return openai_provider, openai_provider.model
    if name == "anthropic":
        from app.ai.providers.llm import AnthropicProvider

        anthropic_provider = AnthropicProvider()
        _require_available(anthropic_provider, name, "ANTHROPIC_API_KEY")
        return anthropic_provider, anthropic_provider.model
    if name == "local":
        from app.ai.providers.llm import LocalLlamaProvider

        local_provider = LocalLlamaProvider()
        _require_available(local_provider, name, "LOCAL_LLM_BASE_URL")
        return local_provider, local_provider.model
    raise SystemExit(f"unknown provider {name!r}")


def _require_available(provider: LlmProvider, name: str, env_var: str) -> None:
    if provider.available():
        return
    raise ProviderUnavailable(
        f"\n  Cannot evaluate the {name} path: {env_var} is not set.\n"
        f"\n  Refusing to run rather than degrade. Without a key every case would"
        f"\n  fall back to the rules layer and this tool would print a results"
        f"\n  table that reads as a model evaluation but measured nothing.\n"
        f"\n  To run it for real:"
        f"\n      export {env_var}=...    # then"
        f"\n      make eval-model PROVIDER={name}\n"
    )


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def print_table(name: str, m: metrics_module.Metrics, context: dict[str, Any]) -> None:
    print()
    print("=" * 72)
    print(f"  SihhatAI evaluation — {name}")
    print("=" * 72)
    # Which code path produced these numbers, stated before any of them. A
    # reader who sees a score must be unable to mistake the baseline for the
    # engine.
    print(f"  provider        {context['provider']}  ({context['model']})")
    print(f"  code path       {context['code_path']}")
    print(
        f"  vignette set    {context['set']} — {context['vignettes']} cases, "
        f"{context['advisor_reviewed']} clinician-reviewed"
    )
    print(f"  prompt version  {context['prompt_version']}")
    print("=" * 72)
    rows: list[tuple[str, str]] = [
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

    if m.should_have_declined or m.declined_wrongly:
        rows += [
            ("", ""),
            (
                "Declined when it should have  [SAFETY]",
                f"{_pct(m.decline_recall)}  ({m.declined_correctly}/{m.should_have_declined})",
            ),
            ("Declined when it should have answered", str(m.declined_wrongly)),
        ]

    if m.adversarial_danger_cases:
        rows += [
            ("", ""),
            (
                "Danger caught when paraphrased  [SAFETY]",
                f"{_pct(m.adversarial_danger_recall)}  "
                f"({m.adversarial_danger_caught}/{m.adversarial_danger_cases})",
            ),
            (
                "Decoys that wrongly fired",
                f"{_pct(m.adversarial_decoy_false_positive_rate)}  "
                f"({m.adversarial_decoy_fired}/{m.adversarial_decoy_cases})",
            ),
        ]

    if m.injection_cases:
        rows += [
            ("", ""),
            (
                "Injection: schema held",
                f"{m.injection_schema_held}/{m.injection_cases}",
            ),
            (
                "Injection: red flags held  [SAFETY]",
                f"{m.injection_red_flags_held}/{m.injection_cases}",
            ),
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

    if m.reliability_buckets:
        print()
        print("  Reliability (is a higher confidence actually more reliable?)")
        print("  " + "-" * 52)
        for bucket in m.reliability_buckets:
            print(
                f"    {bucket['low']:.1f}-{bucket['high']:.1f}   "
                f"n={int(bucket['n']):<4} mean conf {bucket['mean_confidence']:.2f}   "
                f"observed {bucket['accuracy'] * 100:5.1f}%"
            )
        if m.confidence_is_monotone:
            print("    monotone: yes")
        else:
            print("    monotone: NO — a higher score is not more reliable")
            for violation in m.monotonicity_violations:
                print(f"      {violation}")

    if m.adversarial_misses:
        print()
        print(f"  !! {len(m.adversarial_misses)} DANGERS MISSED WHEN PARAPHRASED")
        for miss in m.adversarial_misses[:12]:
            print(f"     {miss['vignette_id']} [{miss['language']}] rule {miss['target_rule']}")

    if m.adversarial_false_fires:
        print()
        print(f"  {len(m.adversarial_false_fires)} decoys wrongly fired")
        for fire in m.adversarial_false_fires[:12]:
            print(f"     {fire['vignette_id']} [{fire['language']}] rule {fire['target_rule']}")

    if m.injection_failures:
        print()
        print(f"  !! {len(m.injection_failures)} INJECTION FAILURES")
        for failure in m.injection_failures[:12]:
            print(
                f"     {failure['vignette_id']} [{failure['language']}] {failure['kind']}: "
                f"schema={failure['schema_valid']} flags={failure['red_flags_held']}"
            )

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
    parser.add_argument(
        "--set",
        dest="vignette_set",
        default="main",
        choices=sorted(VIGNETTE_SETS),
        help="which vignette set to run (default: main)",
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=None,
        help=(
            "deterministic stratified subset: N non-safety cases per presentation, "
            "plus every case carrying a must-not-miss red flag. For the paid model gate."
        ),
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

    vignettes_path = resolve_set(args.vignette_set)
    subset_ids = (
        stratified_subset(load_vignettes(vignettes_path), args.subset) if args.subset else None
    )

    results, lookup = run_suite(
        provider=provider,
        languages=languages,
        limit=args.limit,
        prompt_version=args.prompt_version,
        vignettes_path=vignettes_path,
        subset_ids=subset_ids,
    )
    m = metrics_module.compute(results, lookup)

    vignettes = load_vignettes(vignettes_path)
    if subset_ids is not None:
        chosen = set(subset_ids)
        vignettes = [v for v in vignettes if v.id in chosen]
    reviewed_count = sum(1 for v in vignettes if v.reviewed_by == "advisor_reviewed")

    label = args.label or f"{provider_name} ({model_name})"
    context = {
        "provider": provider_name,
        "model": model_name,
        "code_path": CODE_PATHS[provider_name],
        "set": args.vignette_set
        + (f" (stratified subset of {args.subset}/class)" if args.subset else ""),
        "vignettes": len(vignettes),
        "advisor_reviewed": reviewed_count,
        "prompt_version": prompts.prompt_version(args.prompt_version),
    }
    print_table(label, m, context)
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
            "provenance_note": provenance_note(vignettes_path),
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
    stamp = f"{datetime.now(UTC):%Y-%m-%d}-{provider_name}-{args.vignette_set}"
    path = write_results(payload, stamp=stamp)
    payload["results_file"] = str(path.name)
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
