"""Run the audit's own vignette set through the project's engine.

    cd backend && PYTHONPATH=.. ENVIRONMENT=test \\
      DATABASE_URL="sqlite+pysqlite:///:memory:" \\
      python ../audit/adversarial/run_audit_set.py

Deliberately uses `app.ai.eval.runner.run_suite` and `app.ai.eval.metrics`
unchanged, so the numbers below are produced by the same code that produces the
numbers in `README.md`. The only thing that differs is the vignette file.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from app.ai.eval import metrics as metrics_module
from app.ai.eval.runner import load_vignettes, run_suite
from app.ai.providers.baseline import RetrievalBaselineProvider

HERE = Path(__file__).parent
VIGNETTES = HERE / "vignettes_audit_oov.json"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    vignettes = load_vignettes(VIGNETTES)
    results, lookup = run_suite(
        provider=RetrievalBaselineProvider(),
        languages=("uz", "ru"),
        vignettes_path=VIGNETTES,
    )
    m = metrics_module.compute(results, lookup)

    print()
    print("=" * 74)
    print("  Audit out-of-vocabulary set — written independently of the repository")
    print("=" * 74)
    print("  provider     baseline (rules-baseline-v1)")
    print("  code path    deterministic rules baseline (no model called)")
    print(f"  vignettes    {len(vignettes)}  ->  {len(results)} cases (uz + ru)")
    print("  reviewed     0 clinician-reviewed. SYNTHETIC.")
    print("=" * 74)
    print(f"  Top-1 (strict)                    {_pct(m.top1_accuracy)}")
    print(f"  Top-3 (strict)                    {_pct(m.top3_accuracy)}")
    print(f"  Top-3 (lenient)                   {_pct(m.top3_lenient_accuracy)}")
    print(
        f"  Red-flag recall  [SAFETY]         {_pct(m.red_flag_recall)}"
        f"  ({m.red_flags_caught}/{m.red_flags_expected})"
    )
    print(f"  Red flags fired wrongly           {m.false_red_flags}")
    print(f"  False-referral rate               {_pct(m.false_referral_rate)}")
    print(f"  Insufficient-data responses       {_pct(m.insufficient_share)}")
    print(
        f"  Declined when it should  [SAFETY] {_pct(m.decline_recall)}"
        f"  ({m.declined_correctly}/{m.should_have_declined})"
    )
    print(f"  Declined when it should not       {m.declined_wrongly}")
    if m.adversarial_danger_cases:
        print(
            f"  Danger caught when paraphrased    {_pct(m.adversarial_danger_recall)}"
            f"  ({m.adversarial_danger_caught}/{m.adversarial_danger_cases})"
        )
        print(
            f"  Decoys that wrongly fired         "
            f"{_pct(m.adversarial_decoy_false_positive_rate)}"
            f"  ({m.adversarial_decoy_fired}/{m.adversarial_decoy_cases})"
        )

    # --- the finding this set exists to produce -------------------------
    # Split the red-flag cases by whether an abnormal vital sign backs them.
    # A rule that reads a number survives paraphrase; a rule that reads words
    # does not. That distinction is invisible in an aggregate recall figure.
    vitals_keys = {
        "spo2",
        "respiratory_rate",
        "systolic_bp",
        "diastolic_bp",
        "glucose_mmol",
        "temperature_c",
        "pulse_bpm",
    }
    by_backing: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for result in results:
        vignette = lookup[result.vignette_id]
        if not vignette.must_not_miss:
            continue
        backed = bool(set(vignette.vitals) & vitals_keys)
        caught = all(code in result.fired_red_flags for code in vignette.must_not_miss)
        by_backing["vital-sign backed" if backed else "text only"].append(
            (f"{result.vignette_id}[{result.language}]", caught)
        )

    print()
    print("  Red-flag recall split by what the rule can key on")
    print("  " + "-" * 56)
    for label in ("vital-sign backed", "text only"):
        rows = by_backing.get(label, [])
        if not rows:
            continue
        caught = sum(1 for _, ok in rows if ok)
        print(f"    {label:<22} {caught}/{len(rows)}   {_pct(caught / len(rows))}")

    misses = [
        (f"{r.vignette_id}[{r.language}]", lookup[r.vignette_id].must_not_miss, r.fired_red_flags)
        for r in results
        if lookup[r.vignette_id].must_not_miss
        and not all(c in r.fired_red_flags for c in lookup[r.vignette_id].must_not_miss)
    ]
    print()
    print(f"  {len(misses)} MISSED RED FLAGS")
    for case, expected, fired in misses:
        print(f"    {case:<22} expected {expected}  fired {fired or '[]'}")

    wrong_fires = [
        (f"{r.vignette_id}[{r.language}]", sorted(set(r.fired_red_flags) & set(v.must_not_fire)))
        for r in results
        for v in [lookup[r.vignette_id]]
        if v.must_not_fire and set(r.fired_red_flags) & set(v.must_not_fire)
    ]
    print()
    print(f"  {len(wrong_fires)} FORBIDDEN RED FLAGS THAT FIRED")
    for case, codes in wrong_fires:
        print(f"    {case:<22} {codes}")

    out = HERE / "audit_oov_results.json"
    out.write_text(
        json.dumps(
            {
                "metrics": m.to_dict(),
                "split_by_backing": {
                    k: {"caught": sum(1 for _, ok in v if ok), "total": len(v)}
                    for k, v in by_backing.items()
                },
                "missed_red_flags": [
                    {"case": c, "expected": e, "fired": f} for c, e, f in misses
                ],
                "forbidden_red_flags_fired": [
                    {"case": c, "codes": codes} for c, codes in wrong_fires
                ],
                "cases": [
                    {
                        "vignette_id": r.vignette_id,
                        "language": r.language,
                        "predicted": r.predicted_codes,
                        "red_flags": r.fired_red_flags,
                        "insufficient_data": r.insufficient_data,
                    }
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
