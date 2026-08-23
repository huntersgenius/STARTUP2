"""Score the audit's own vignette sets on the engine's real red-flag path.

This reuses the production code path exactly — `TerminologyMap.clinical_concepts`
plus `DiagnosticEngine._vital_concepts` plus `red_flags.evaluate` — so the numbers
are directly comparable with the repository's own `--offline` red-flag recall.
Nothing is mocked and no answer key is inferred from the engine.

Usage:
    PYTHONPATH=backend:. python audit/adversarial/run_audit_eval.py
    PYTHONPATH=backend:. python audit/adversarial/run_audit_eval.py --set evasion
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.ai.engine import DiagnosticEngine
from app.ai.red_flags import CaseFacts, evaluate
from knowledge.terminology import get_terminology

HERE = Path(__file__).parent
SETS = {
    "oov": HERE / "vignettes_audit2_oov.json",
    "evasion": HERE / "redflag_evasion.json",
    "decoy": HERE / "redflag_decoy.json",
}
REPO_SETS = {
    "repo-main": HERE.parent.parent / "backend/app/ai/eval/data/vignettes.json",
    "repo-oov": HERE.parent.parent / "backend/app/ai/eval/data/vignettes_oov.json",
}


def age_band(age: float | None) -> str:
    """Mirrors app/models/patient.py:74-90 exactly. Band names are load-bearing:
    the paediatric rules test `facts.age_band in ("infant", "under5")`."""
    if age is None:
        return "unknown"
    if age < 1:
        return "infant"
    if age < 5:
        return "under5"
    if age < 12:
        return "child"
    if age < 18:
        return "adolescent"
    if age < 65:
        return "adult"
    return "elderly"


def fire(text: str, vignette: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (concepts, red-flag codes) exactly as the engine would derive them."""
    mapping = get_terminology()
    vitals = vignette.get("vitals") or {}
    concepts = mapping.clinical_concepts(text)
    concepts.extend(c for c in DiagnosticEngine._vital_concepts(vitals) if c not in concepts)
    facts = CaseFacts(
        concepts=set(concepts),
        age_years=vignette.get("age_years"),
        age_band=age_band(vignette.get("age_years")),
        sex=vignette.get("sex", "unknown"),
        pregnant=bool(vignette.get("pregnant")) or "pregnancy" in concepts,
        temperature_c=vitals.get("temperature_c"),
        pulse_bpm=vitals.get("pulse_bpm"),
        systolic_bp=vitals.get("systolic_bp"),
        diastolic_bp=vitals.get("diastolic_bp"),
        respiratory_rate=vitals.get("respiratory_rate"),
        spo2=vitals.get("spo2"),
        weight_kg=vitals.get("weight_kg"),
        glucose_mmol=vitals.get("glucose_mmol"),
        duration_days=vignette.get("duration_days"),
        free_text=text,
    )
    return concepts, [f.code for f in evaluate(facts)]


def load(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["vignettes"] if isinstance(data, dict) else data


def score(name: str, path: Path, verbose: bool = False) -> dict[str, Any]:
    vignettes = load(path)
    expected = missed = fired_wrongly = 0
    by_phenomenon: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses: list[tuple[str, str, list[str], list[str]]] = []
    false_fires: list[tuple[str, str, list[str]]] = []

    for v in vignettes:
        for lang in ("uz", "ru"):
            text = v.get(f"text_{lang}")
            if not text:
                continue
            concepts, codes = fire(text, v)
            for want in v.get("must_not_miss", []):
                expected += 1
                hit = want in codes
                if not hit:
                    missed += 1
                    misses.append((v["id"] + "/" + lang, want, concepts, codes))
                for ph in v.get("phenomena", ["untagged"]):
                    by_phenomenon[ph][1] += 1
                    by_phenomenon[ph][0] += int(hit)
            for forbid in v.get("must_not_fire", []):
                if forbid in codes:
                    fired_wrongly += 1
                    false_fires.append((v["id"] + "/" + lang, forbid, concepts))

    recall = (expected - missed) / expected if expected else None
    print(f"\n=== {name} ({len(vignettes)} vignettes, {path.name})")
    print(f"  red-flag expectations       {expected}")
    if recall is not None:
        print(f"  RED-FLAG RECALL             {recall:6.1%}  ({expected - missed}/{expected})")
    print(f"  forbidden flags that fired  {fired_wrongly}")

    if by_phenomenon:
        print("\n  by phenomenon")
        for ph, (hit, tot) in sorted(by_phenomenon.items(), key=lambda kv: kv[1][0] / kv[1][1]):
            print(f"    {ph:28s} {hit/tot:6.1%}  ({hit}/{tot})")

    if verbose and misses:
        print("\n  missed (case, expected flag, concepts the engine actually extracted)")
        for case, want, concepts, got in misses:
            print(f"    {case:16s} want={want:24s} concepts={concepts} got={got}")
    if verbose and false_fires:
        print("\n  fired when it must not")
        for case, code, concepts in false_fires:
            print(f"    {case:16s} fired={code:24s} concepts={concepts}")

    return {"set": name, "expected": expected, "missed": missed, "recall": recall}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="which", default="all")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    targets = {**SETS, **REPO_SETS}
    chosen = targets if args.which == "all" else {args.which: targets[args.which]}
    results = [score(n, p, args.verbose) for n, p in chosen.items() if p.exists()]

    print("\n=== side by side")
    print(f"  {'set':14s} {'recall':>8s}  {'n':>5s}")
    for r in results:
        rec = f"{r['recall']:.1%}" if r["recall"] is not None else "n/a"
        print(f"  {r['set']:14s} {rec:>8s}  {r['expected']:5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
