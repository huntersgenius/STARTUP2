"""Types for the evaluation set and its results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: Provenance of a vignette. This distinction is the difference between a
#: number you can show an investor and one you can show a regulator.
Provenance = Literal["synthetic", "advisor_reviewed"]


@dataclass
class Vignette:
    id: str
    #: The presentation category, matching the 10 target conditions.
    category: str
    text_uz: str
    text_ru: str
    age_years: float
    sex: str
    vitals: dict[str, Any]
    #: The single correct answer.
    ground_truth_icd10: str
    ground_truth_label: str
    #: Diagnoses a competent clinician might also reasonably reach. Counted as
    #: correct for top-1/top-3, because marking them wrong would punish the
    #: system for being clinically reasonable.
    acceptable_alternatives: list[str] = field(default_factory=list)
    #: Red-flag codes that MUST fire. Missing one of these is the safety
    #: failure the eval exists to catch.
    must_not_miss: list[str] = field(default_factory=list)
    #: Red flags that must NOT fire — over-triage has a real cost in a country
    #: where referral means a day of travel.
    must_not_fire: list[str] = field(default_factory=list)
    pregnant: bool = False
    chronic_flags: list[str] = field(default_factory=list)
    duration_days: float | None = None
    reviewed_by: Provenance = "synthetic"
    notes: str | None = None
    #: True when the correct behaviour is to decline and ask, rather than rank.
    #: A confidently wrong differential in a clinic with no specialist is the
    #: failure mode this product exists to prevent, so declining is scored.
    expect_insufficient_data: bool = False
    #: Adversarial set only: "danger_paraphrased" or "trigger_words_no_danger".
    adversarial_kind: str | None = None
    target_rule: str | None = None
    #: Injection set only: what the injected text is trying to do.
    injection_kind: str | None = None

    def text(self, language: str) -> str:
        return self.text_ru if language == "ru" else self.text_uz

    @property
    def accepted_codes(self) -> set[str]:
        return {self.ground_truth_icd10, *self.acceptable_alternatives}

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Vignette:
        return cls(**payload)


@dataclass
class CaseResult:
    vignette_id: str
    language: str
    category: str
    #: ICD-10 codes the system ranked, best first.
    predicted_codes: list[str]
    predicted_labels: list[str]
    confidences: list[float]
    fired_red_flags: list[str]
    referral_needed: bool
    latency_ms: int
    cost_usd: float
    degraded: bool
    insufficient_data: bool
    error: str | None = None
    #: Whether the structured-output contract held. Only false when the engine
    #: could not produce a schema-valid suggestion at all.
    schema_valid: bool = True

    @property
    def top_code(self) -> str | None:
        return self.predicted_codes[0] if self.predicted_codes else None

    @property
    def top_confidence(self) -> float:
        return self.confidences[0] if self.confidences else 0.0
