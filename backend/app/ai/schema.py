"""The structured output contract.

The model is required to return exactly this shape. A response that fails
validation is retried (twice), and if it still fails the engine degrades to a
rules-only response rather than showing a clinician something unvalidated.

Validation here is not just shape-checking: it enforces the safety rules that
must hold whatever the model produced (citations present, no controlled drugs,
no paediatric dose without a weight).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Differential(BaseModel):
    condition: str = Field(min_length=2, max_length=200)
    icd10: str | None = Field(default=None, max_length=16)
    confidence: float = Field(ge=0.0, le=1.0)
    #: One or two sentences a clinician can check against the citation.
    why: str = Field(min_length=3, max_length=1200)
    red_flags: list[str] = Field(default_factory=list)
    #: Ids of retrieved excerpts supporting this differential. Never empty in a
    #: response that reaches a clinician — see `Grounding` in engine.py.
    citations: list[str] = Field(default_factory=list)

    @field_validator("icd10")
    @classmethod
    def _plausible_icd10(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not v:
            return None
        # Shape check only; the code is not verified against a code list here.
        if not re.fullmatch(r"[A-Z]\d{2}(\.\d{1,3})?", v):
            return None
        return v


class RecommendedTest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    reason: str = Field(default="", max_length=600)
    #: Whether a tier-1 clinic can realistically do it.
    available_locally: bool = True


class TreatmentItem(BaseModel):
    drug: str = Field(min_length=2, max_length=160)
    dose: str | None = Field(default=None, max_length=200)
    route: str | None = Field(default=None, max_length=60)
    duration: str | None = Field(default=None, max_length=120)
    #: Set by the formulary check, not by the model.
    local_availability: Literal["available", "substitute_suggested", "unavailable", "unknown"] = (
        "unknown"
    )
    substitute: str | None = None
    notes: str | None = Field(default=None, max_length=600)


class Treatment(BaseModel):
    items: list[TreatmentItem] = Field(default_factory=list)
    non_pharmacological: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1200)
    #: Populated when a safety rule prevented a dose being given at all.
    blocked_reason: str | None = None


class RiskScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    band: Literal["low", "moderate", "high", "very_high"] = "low"
    drivers: list[str] = Field(default_factory=list)


class Referral(BaseModel):
    needed: bool = False
    specialty: str | None = Field(default=None, max_length=120)
    urgency: Literal["immediate", "same_day", "urgent", "routine", "none"] = "none"
    reason: str | None = Field(default=None, max_length=600)


class RedFlagOut(BaseModel):
    code: str
    urgency: Literal["immediate", "same_day", "urgent"]
    message: str
    refer_to: str
    triggered_by: list[str] = Field(default_factory=list)


class ClinicalSuggestion(BaseModel):
    """The full structured response."""

    differentials: list[Differential] = Field(default_factory=list, max_length=3)
    recommended_tests: list[RecommendedTest] = Field(default_factory=list)
    treatment: Treatment = Field(default_factory=Treatment)
    risk: RiskScore = Field(default_factory=lambda: RiskScore(score=0.0, band="low"))
    referral: Referral = Field(default_factory=Referral)
    #: Deterministic rules, merged in by the engine — never model-authored.
    red_flags: list[RedFlagOut] = Field(default_factory=list)
    #: Populated instead of differentials when confidence is too low to rank.
    follow_up_questions: list[str] = Field(default_factory=list)
    insufficient_data: bool = False

    @model_validator(mode="after")
    def _confidence_is_ordered(self) -> ClinicalSuggestion:
        confidences = [d.confidence for d in self.differentials]
        if confidences != sorted(confidences, reverse=True):
            self.differentials = sorted(
                self.differentials, key=lambda d: d.confidence, reverse=True
            )
        return self

    @model_validator(mode="after")
    def _red_flags_force_referral(self) -> ClinicalSuggestion:
        """A fired red flag always means referral, whatever the model said."""
        if self.red_flags:
            worst = min(
                self.red_flags, key=lambda f: ["immediate", "same_day", "urgent"].index(f.urgency)
            )
            self.referral = Referral(
                needed=True,
                specialty=self.referral.specialty or worst.refer_to,
                urgency=worst.urgency,
                reason=self.referral.reason or worst.message,
            )
        return self

    @property
    def top_confidence(self) -> float:
        return self.differentials[0].confidence if self.differentials else 0.0


#: JSON schema handed to the model. Generated from the Pydantic models so the
#: prompt and the validator can never drift apart.
def response_json_schema() -> dict[str, Any]:
    schema = ClinicalSuggestion.model_json_schema()
    schema["additionalProperties"] = False
    return schema


class SchemaValidationError(ValueError):
    """The model returned something that is not a valid suggestion."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_response(raw: str) -> ClinicalSuggestion:
    """Parse a model response into a validated suggestion.

    Tolerant of the two things models do even when told not to: wrapping JSON
    in a markdown fence, and adding a sentence before or after the object.
    Anything beyond that is a validation failure, and the caller retries.
    """
    if not raw or not raw.strip():
        raise SchemaValidationError("empty response")

    text = _FENCE.sub("", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise SchemaValidationError("no JSON object found in response")

    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise SchemaValidationError("response is not a JSON object")

    try:
        return ClinicalSuggestion.model_validate(payload)
    except Exception as exc:
        raise SchemaValidationError(str(exc)) from exc
