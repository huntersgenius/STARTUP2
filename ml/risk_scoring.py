"""Deterministic patient risk scoring.

A points-based model over findings the protocols in `knowledge/corpus` name as
risk factors. Every point is attributable, so the score can be explained to the
clinician who has to act on it and to the regulator who has to approve it.

This replaces an LLM-authored `risk.score`, which was an uncalibrated number
that looked computed. See `ml/README.md` for why a trained model comes later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Band = Literal["low", "moderate", "high", "very_high"]

#: Points per finding. Weights are ordinal, not probabilities: they rank
#: patients for attention, they do not estimate an event rate. Anything
#: claiming to be a probability needs outcome data we do not have.
CONCEPT_POINTS: dict[str, int] = {
    # Immediate-danger findings dominate by construction: a patient with one of
    # these must sort above any accumulation of chronic risk.
    "crushing_chest_pain": 40,
    "myocardial_infarction": 40,
    "stroke": 40,
    "unilateral_weakness": 35,
    "slurred_speech": 35,
    "meningism": 35,
    "neck_stiffness": 25,
    "hematemesis": 30,
    "melena": 30,
    "bloody_diarrhea": 20,
    "pregnancy_bleeding": 40,
    "hemoptysis": 25,
    "syncope": 20,
    "confusion": 25,
    "lethargy": 20,
    "unable_to_feed": 25,
    "dehydration": 20,
    "seizure": 25,
    "kussmaul_breathing": 25,
    # Sustained conditions.
    "chest_pain": 12,
    "dyspnea": 12,
    "pneumonia": 12,
    "tuberculosis": 15,
    "night_sweats": 6,
    "weight_loss": 8,
    "anemia": 8,
    "pallor": 6,
    "diabetes_t2": 8,
    "hypertension": 8,
    "cardiovascular_disease": 12,
    "obesity": 4,
    "overweight": 3,
    "tobacco_use": 6,
    "cholesterol": 4,
    "dietary_salt": 2,
}

#: Chronic conditions recorded on the patient, independent of today's visit.
CHRONIC_POINTS: dict[str, int] = {
    "diabetes": 8,
    "hypertension": 6,
    "heart_failure": 12,
    "ckd": 10,
    "copd": 8,
    "asthma": 4,
    "tuberculosis": 10,
    "immunosuppression": 12,
    "pregnancy": 6,
}

BAND_THRESHOLDS: tuple[tuple[int, Band], ...] = (
    (60, "very_high"),
    (35, "high"),
    (15, "moderate"),
)

#: A fired red flag pins the score to at least this, whatever else is true.
#: The rule layer has already decided this patient needs referral; the risk
#: score must not quietly disagree with it.
RED_FLAG_FLOOR = 70


@dataclass
class RiskDriver:
    """One contribution to the score, in words a clinician can check."""

    factor: str
    points: int
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass
class RiskAssessment:
    score: float
    band: Band
    points: int
    drivers: list[RiskDriver] = field(default_factory=list)

    @property
    def driver_texts(self) -> list[str]:
        return [driver.detail for driver in self.drivers]

    def to_payload(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "band": self.band,
            "drivers": self.driver_texts,
        }


def _band_for(points: int) -> Band:
    for threshold, band in BAND_THRESHOLDS:
        if points >= threshold:
            return band
    return "low"


def score_patient(
    *,
    concepts: set[str] | list[str],
    age_years: float | None = None,
    vitals: dict[str, Any] | None = None,
    chronic_flags: list[str] | None = None,
    red_flag_codes: list[str] | None = None,
    pregnant: bool = False,
) -> RiskAssessment:
    """Score one presentation. Pure function; no I/O, no model call."""
    vitals = vitals or {}
    drivers: list[RiskDriver] = []
    points = 0

    for concept in sorted(set(concepts)):
        weight = CONCEPT_POINTS.get(concept)
        if weight:
            points += weight
            drivers.append(RiskDriver(concept, weight, f"{concept.replace('_', ' ')} (+{weight})"))

    for flag in chronic_flags or []:
        weight = CHRONIC_POINTS.get(flag.strip().lower())
        if weight:
            points += weight
            drivers.append(RiskDriver(flag, weight, f"chronic: {flag} (+{weight})"))

    # --- age ---------------------------------------------------------------
    if age_years is not None:
        if age_years < 1:
            points += 15
            drivers.append(RiskDriver("age", 15, "infant under 1 year (+15)"))
        elif age_years < 5:
            points += 10
            drivers.append(RiskDriver("age", 10, "child under 5 (+10)"))
        elif age_years >= 80:
            points += 12
            drivers.append(RiskDriver("age", 12, "age 80 or over (+12)"))
        elif age_years >= 65:
            points += 8
            drivers.append(RiskDriver("age", 8, "age 65 or over (+8)"))

    if pregnant:
        points += 6
        drivers.append(RiskDriver("pregnancy", 6, "pregnant (+6)"))

    # --- vitals ------------------------------------------------------------
    for factor, weight, detail in _vital_points(vitals, age_years):
        points += weight
        drivers.append(RiskDriver(factor, weight, detail))

    # --- red flags dominate --------------------------------------------------
    if red_flag_codes:
        for code in red_flag_codes:
            drivers.append(RiskDriver(code, 0, f"red flag: {code}"))
        points = max(points, RED_FLAG_FLOOR)

    drivers.sort(key=lambda d: d.points, reverse=True)
    # Squash to 0-1 for the API without pretending it is a probability: 100
    # points is the practical ceiling, and anything above it is already
    # "very high" and cannot be more urgent.
    score = min(1.0, points / 100)
    return RiskAssessment(score=score, band=_band_for(points), points=points, drivers=drivers)


def _vital_points(vitals: dict[str, Any], age_years: float | None) -> list[tuple[str, int, str]]:
    """Vital-sign contributions, using the thresholds in the corpus protocols."""
    out: list[tuple[str, int, str]] = []

    def number(key: str) -> float | None:
        value = vitals.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    spo2 = number("spo2")
    if spo2 is not None:
        if spo2 < 90:
            out.append(("spo2", 30, f"SpO2 {spo2:.0f}% (+30)"))
        elif spo2 < 94:
            out.append(("spo2", 15, f"SpO2 {spo2:.0f}% (+15)"))

    systolic = number("systolic_bp")
    if systolic is not None:
        if systolic < 90:
            out.append(("systolic_bp", 30, f"systolic {systolic:.0f} mmHg (+30)"))
        elif systolic >= 180:
            out.append(("systolic_bp", 20, f"systolic {systolic:.0f} mmHg (+20)"))
        elif systolic >= 160:
            out.append(("systolic_bp", 10, f"systolic {systolic:.0f} mmHg (+10)"))
        elif systolic >= 140:
            out.append(("systolic_bp", 5, f"systolic {systolic:.0f} mmHg (+5)"))

    pulse = number("pulse_bpm")
    if pulse is not None:
        if pulse >= 130 or pulse < 45:
            out.append(("pulse_bpm", 20, f"pulse {pulse:.0f}/min (+20)"))
        elif pulse >= 110:
            out.append(("pulse_bpm", 10, f"pulse {pulse:.0f}/min (+10)"))

    # Respiratory-rate thresholds are age dependent; a rate of 40 is an
    # emergency in an adult and unremarkable in an infant.
    rate = number("respiratory_rate")
    if rate is not None:
        infant = age_years is not None and age_years < 1
        toddler = age_years is not None and age_years < 5
        limit_high = 60 if infant else 50 if toddler else 30
        limit_mid = 50 if infant else 40 if toddler else 22
        if rate >= limit_high:
            out.append(("respiratory_rate", 25, f"respiratory rate {rate:.0f}/min (+25)"))
        elif rate >= limit_mid:
            out.append(("respiratory_rate", 12, f"respiratory rate {rate:.0f}/min (+12)"))

    temperature = number("temperature_c")
    if temperature is not None:
        if temperature >= 40.0 or temperature < 35.0:
            out.append(("temperature_c", 15, f"temperature {temperature:.1f} °C (+15)"))
        elif temperature >= 38.5:
            out.append(("temperature_c", 5, f"temperature {temperature:.1f} °C (+5)"))

    glucose = number("glucose_mmol")
    if glucose is not None:
        if glucose >= 20 or glucose < 3.0:
            out.append(("glucose_mmol", 30, f"glucose {glucose:.1f} mmol/L (+30)"))
        elif glucose >= 11.1:
            out.append(("glucose_mmol", 8, f"glucose {glucose:.1f} mmol/L (+8)"))

    return out
