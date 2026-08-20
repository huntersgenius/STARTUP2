"""Measure how much of the evaluation score is vocabulary matching.

The 249 main vignettes, the terminology map and the red-flag rules were written
by the same process in the same sequence. A high score on that set therefore
partly measures whether the rules fire on text written to describe those rules,
rather than whether the system understands a patient.

This module quantifies that circularity so it can be published rather than
argued about. It answers four questions:

1. What share of each vignette's clinical content is already in the terminology
   map, verbatim?
2. How many terminology surfaces are never exercised by any vignette — coverage
   the eval does not test at all?
3. How many red-flag rules are only ever tested by text phrased in the rule's
   own vocabulary?
4. How do those figures differ on the out-of-vocabulary set, written
   deliberately to avoid the map?

Run: `python -m app.ai.eval.overlap`
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from knowledge.terminology import TerminologyMap, get_terminology

from app.ai.eval.runner import (
    ADVERSARIAL_VIGNETTES_PATH,
    OOV_VIGNETTES_PATH,
    VIGNETTES_PATH,
    load_vignettes,
)
from app.ai.eval.schema import Vignette
from app.ai.red_flags import RULES, CaseFacts

RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class SetOverlap:
    """Overlap statistics for one vignette set."""

    name: str
    vignettes: int
    texts: int = 0
    texts_with_any_surface: int = 0
    surface_hits: int = 0
    distinct_surfaces_used: int = 0
    #: Share of each text's words covered by a matched terminology surface,
    #: averaged over texts — "how much of this sentence is already in our
    #: dictionary".
    mean_surface_word_coverage: float = 0.0
    concepts_per_text: float = 0.0
    #: A set of 249 vignettes built from 26 templates is 26 clinical scenarios
    #: with varied numbers, not 249. Per-class accuracy on such a set reports
    #: whether a handful of templates were matched, and one template failing
    #: drags a whole class down by however many copies it has.
    distinct_texts: int = 0
    distinct_templates: int = 0
    exact_duplicates: int = 0
    largest_template_group: int = 0

    @property
    def share_with_any_surface(self) -> float:
        return self.texts_with_any_surface / self.texts if self.texts else 0.0

    @property
    def effective_scenarios(self) -> float:
        """Distinct templates as a share of the headline vignette count."""
        return self.distinct_templates / self.vignettes if self.vignettes else 0.0


@dataclass
class RuleCoverage:
    code: str
    main_cases: int = 0
    oov_cases: int = 0
    adversarial_cases: int = 0

    @property
    def only_tested_in_own_vocabulary(self) -> bool:
        return (self.oov_cases + self.adversarial_cases) == 0


@dataclass
class OverlapReport:
    sets: list[SetOverlap] = field(default_factory=list)
    unused_surfaces: int = 0
    total_surfaces: int = 0
    unused_surface_examples: list[str] = field(default_factory=list)
    rules: list[RuleCoverage] = field(default_factory=list)
    rules_without_out_of_vocabulary_test: list[str] = field(default_factory=list)
    #: Presentation classes identifiable by one shared phrase (remediation §4).
    trivially_separable_categories: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sets": [
                asdict(s)
                | {
                    "share_with_any_surface": s.share_with_any_surface,
                    "effective_scenarios": s.effective_scenarios,
                }
                for s in self.sets
            ],
            "unused_surfaces": self.unused_surfaces,
            "total_surfaces": self.total_surfaces,
            "unused_surface_examples": self.unused_surface_examples,
            "rules": [
                asdict(r) | {"only_tested_in_own_vocabulary": r.only_tested_in_own_vocabulary}
                for r in self.rules
            ],
            "rules_without_out_of_vocabulary_test": self.rules_without_out_of_vocabulary_test,
            "trivially_separable_categories": self.trivially_separable_categories,
        }


def measure_set(
    mapping: TerminologyMap, name: str, vignettes: list[Vignette]
) -> tuple[SetOverlap, Counter]:
    stats = SetOverlap(name=name, vignettes=len(vignettes))
    used: Counter = Counter()
    coverages: list[float] = []
    concept_counts: list[int] = []

    for vignette in vignettes:
        for language in ("uz", "ru"):
            text = vignette.text(language)
            stats.texts += 1
            surfaces = [match.surface for match in mapping.extract(text)]
            if surfaces:
                stats.texts_with_any_surface += 1
            stats.surface_hits += len(surfaces)
            used.update(surfaces)

            words = max(1, len(text.split()))
            covered = sum(len(surface.split()) for surface in surfaces)
            coverages.append(min(1.0, covered / words))
            concept_counts.append(len(mapping.clinical_concepts(text)))

    # Template duplication: mask the digits that vary between otherwise
    # identical vignettes, then count what is left.
    exact = Counter(v.text_uz for v in vignettes)
    templates = Counter(re.sub(r"[\d.,]+", "#", v.text_uz) for v in vignettes)
    stats.distinct_texts = len(exact)
    stats.distinct_templates = len(templates)
    stats.exact_duplicates = sum(n - 1 for n in exact.values() if n > 1)
    stats.largest_template_group = max(templates.values()) if templates else 0

    stats.distinct_surfaces_used = len(used)
    stats.mean_surface_word_coverage = sum(coverages) / len(coverages) if coverages else 0.0
    stats.concepts_per_text = sum(concept_counts) / len(concept_counts) if concept_counts else 0.0
    return stats, used


def _band(age: float | None) -> str:
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


def _f(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def rules_firing_from_text(mapping: TerminologyMap, vignette: Vignette, language: str) -> set[str]:
    """Rule codes that fire from this text alone, via the terminology map."""
    facts = CaseFacts(
        concepts=set(mapping.clinical_concepts(vignette.text(language))),
        age_years=vignette.age_years,
        age_band=_band(vignette.age_years),
        sex=vignette.sex,
        pregnant=vignette.pregnant,
        temperature_c=_f(vignette.vitals.get("temperature_c")),
        pulse_bpm=_i(vignette.vitals.get("pulse_bpm")),
        systolic_bp=_i(vignette.vitals.get("systolic_bp")),
        diastolic_bp=_i(vignette.vitals.get("diastolic_bp")),
        respiratory_rate=_i(vignette.vitals.get("respiratory_rate")),
        spo2=_i(vignette.vitals.get("spo2")),
        glucose_mmol=_f(vignette.vitals.get("glucose_mmol")),
        duration_days=vignette.duration_days,
    )
    return {flag.code for check in RULES for flag in (check(facts),) if flag is not None}


def find_trivially_separable(vignettes: list[Vignette]) -> list[dict[str, Any]]:
    """Categories where one phrase appears in most members and nowhere else.

    A class identifiable by a single string is not testing the diagnostic
    engine, it is testing string matching, and its score should be read as
    meaningless rather than perfect.
    """
    by_category: dict[str, list[str]] = {}
    for vignette in vignettes:
        by_category.setdefault(vignette.category, []).append(vignette.text_uz)

    findings: list[dict[str, Any]] = []
    for category, texts in sorted(by_category.items()):
        if len(texts) < 5:
            continue
        others = [t for c, ts in by_category.items() if c != category for t in ts]
        shingles: Counter = Counter()
        for text in texts:
            words = text.lower().split()
            shingles.update({" ".join(words[i : i + 3]) for i in range(max(0, len(words) - 2))})
        for phrase, count in shingles.most_common(30):
            share = count / len(texts)
            if share < 0.8:
                continue
            elsewhere = sum(1 for t in others if phrase in t.lower())
            if elsewhere == 0:
                findings.append(
                    {
                        "category": category,
                        "phrase": phrase,
                        "share_of_class": round(share, 3),
                        "appearances_outside_class": elsewhere,
                        "cases": len(texts),
                    }
                )
                break
    return findings


def build_report() -> OverlapReport:
    mapping = get_terminology()
    report = OverlapReport()

    main = load_vignettes(VIGNETTES_PATH)
    named_sets: list[tuple[str, list[Vignette]]] = [("main", main)]
    if OOV_VIGNETTES_PATH.exists():
        named_sets.append(("out_of_vocabulary", load_vignettes(OOV_VIGNETTES_PATH)))
    if ADVERSARIAL_VIGNETTES_PATH.exists():
        named_sets.append(("adversarial", load_vignettes(ADVERSARIAL_VIGNETTES_PATH)))

    all_used: Counter = Counter()
    for name, vignettes in named_sets:
        stats, used = measure_set(mapping, name, vignettes)
        report.sets.append(stats)
        all_used.update(used)

    report.total_surfaces = mapping.surface_count
    all_surfaces = set(mapping.all_surfaces())
    unused = sorted(all_surfaces - set(all_used))
    report.unused_surfaces = len(unused)
    report.unused_surface_examples = unused[:25]

    coverage: dict[str, RuleCoverage] = {}
    for name, vignettes in named_sets:
        for vignette in vignettes:
            for code in vignette.must_not_miss:
                entry = coverage.setdefault(code, RuleCoverage(code=code))
                if name == "main":
                    entry.main_cases += 1
                elif name == "out_of_vocabulary":
                    entry.oov_cases += 1
                else:
                    entry.adversarial_cases += 1

    report.rules = sorted(coverage.values(), key=lambda r: r.code)
    report.rules_without_out_of_vocabulary_test = sorted(
        r.code for r in report.rules if r.only_tested_in_own_vocabulary
    )
    report.trivially_separable_categories = find_trivially_separable(main)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure eval/vocabulary overlap")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print()
    print("=" * 74)
    print("  Evaluation / vocabulary overlap")
    print("=" * 74)
    print()
    print("  How much of each vignette is already in the terminology map?")
    print()
    for stats in report.sets:
        print(f"    {stats.name}")
        print(f"      vignettes                        {stats.vignettes}")
        print(f"      texts (uz + ru)                  {stats.texts}")
        print(
            f"      texts containing a map surface   {stats.texts_with_any_surface} "
            f"({stats.share_with_any_surface * 100:.1f}%)"
        )
        print(
            f"      mean word coverage by surfaces   {stats.mean_surface_word_coverage * 100:.1f}%"
        )
        print(f"      concepts recognised per text     {stats.concepts_per_text:.2f}")
        print(
            f"      distinct texts / templates       "
            f"{stats.distinct_texts} / {stats.distinct_templates}"
        )
        print(
            f"      exact duplicate vignettes        {stats.exact_duplicates} "
            f"(largest template group {stats.largest_template_group})"
        )
        print()

    print(
        f"  Terminology surfaces never exercised: "
        f"{report.unused_surfaces} of {report.total_surfaces} "
        f"({report.unused_surfaces / max(1, report.total_surfaces) * 100:.1f}%)"
    )
    if report.unused_surface_examples:
        print(f"    e.g. {', '.join(report.unused_surface_examples[:6])}")
    print()

    print(
        f"  Red-flag rules tested only in their own vocabulary: "
        f"{len(report.rules_without_out_of_vocabulary_test)} of {len(report.rules)}"
    )
    for code in report.rules_without_out_of_vocabulary_test:
        print(f"    {code}")
    print()

    if report.trivially_separable_categories:
        print("  Presentation classes separable by a single shared phrase:")
        for finding in report.trivially_separable_categories:
            print(
                f'    {finding["category"]:<24} "{finding["phrase"]}" in '
                f"{finding['share_of_class'] * 100:.0f}% of {finding['cases']} cases, "
                f"{finding['appearances_outside_class']} elsewhere"
            )
    else:
        print("  No presentation class is separable by a single shared phrase.")
    print()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "overlap.json"
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  written to {path}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
