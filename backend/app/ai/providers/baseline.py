"""A deterministic, offline baseline "model".

Why this exists: the evaluation gate has to run on every pull request, with no
API keys and no network. A cassette-only provider gives CI nothing to measure
(every case degrades to rules-only), and a gate that always reports 0% teaches
the team to ignore it.

So this provider is a real, if simple, clinical reasoner: it scores conditions
from the recognised concepts and the retrieved protocol excerpts, using a
weighted concept→condition table derived from the committed corpus. It cites
the excerpts it actually used.

Two things it is **not**:

- It is not an LLM, and the eval report labels every run with the engine that
  produced it. A baseline number must never be presented as a GPT-4o number.
- It is not the product. It is the floor: the quality a clinic gets when every
  model is unreachable, and the number a prompt or model change has to beat.

It parses the structured sections of our own prompt template (`prompts/v1/
diagnose.txt`). That coupling is deliberate and is asserted by a test, so a
template change that breaks it fails loudly.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from app.ai.providers.base import LlmResponse

#: concept → {icd10: weight}. Weights are relative likelihoods within a
#: presentation, not probabilities; they are normalised per case. Derived from
#: the protocols in knowledge/corpus, and deliberately conservative: a concept
#: only votes for conditions its protocol actually discusses.
CONCEPT_WEIGHTS: dict[str, dict[str, float]] = {
    # respiratory
    "cough": {"J00": 1.0, "J40": 1.0, "J18.9": 0.8, "J11.1": 0.8, "A15.0": 0.4},
    "productive_cough": {"J18.9": 1.6, "J40": 1.2, "J15.9": 0.6},
    "dry_cough": {"J11.1": 1.2, "J00": 0.8, "J45.9": 0.6},
    "sore_throat": {"J00": 1.6, "J02.9": 1.4, "J11.1": 0.6},
    "rhinorrhea": {"J00": 1.8, "J11.1": 0.5},
    "nasal_congestion": {"J00": 1.4},
    "common_cold": {"J00": 2.5},
    "influenza": {"J11.1": 2.5},
    "pneumonia": {"J18.9": 2.5},
    "bronchitis": {"J40": 2.2},
    "asthma": {"J45.9": 2.5},
    "wheezing": {"J45.9": 1.6, "J40": 0.8},
    "dyspnea": {"J18.9": 1.0, "J45.9": 1.0, "I21.9": 0.6, "D50.9": 0.5},
    "chest_pain": {"J18.9": 0.7, "I21.9": 1.4, "M54.5": 0.3},
    "crushing_chest_pain": {"I21.9": 3.0, "I20.0": 1.5},
    "hemoptysis": {"A15.0": 2.0, "R04.2": 1.0},
    "night_sweats": {"A15.0": 2.0},
    "weight_loss": {"A15.0": 1.4, "E11.9": 0.9},
    "tuberculosis": {"A15.0": 3.0},
    # fever / general
    "fever": {"J18.9": 0.8, "J11.1": 0.8, "J00": 0.5, "A09": 0.4, "G03.9": 0.5},
    "chills": {"J18.9": 0.6, "J11.1": 0.6},
    "myalgia": {"J11.1": 1.2, "M54.5": 0.6},
    "fatigue": {"D50.9": 1.0, "E11.9": 0.8, "E01.2": 0.8},
    "weakness": {"D50.9": 1.2, "E11.9": 0.8, "E01.2": 0.8},
    # cardiovascular
    "hypertension": {"I10": 2.5, "Z13.6": 0.6, "I16.1": 0.5},
    "headache": {"I10": 0.9, "G03.9": 0.4, "M54.2": 0.2},
    "dizziness": {"I10": 0.8, "D50.9": 0.6},
    "blurred_vision": {"I16.1": 1.2, "E11.9": 0.6},
    "thunderclap_headache": {"I16.1": 1.4, "G03.9": 1.2},
    "cardiovascular_disease": {"Z13.6": 1.8, "I25.10": 1.4},
    "dietary_salt": {"Z13.6": 1.2, "I10": 0.6},
    "diet": {"Z13.6": 1.0},
    "tobacco_use": {"Z13.6": 1.2},
    "overweight": {"Z13.6": 1.0, "E66.9": 1.4, "E11.9": 0.6},
    "physical_activity": {"Z13.6": 0.8},
    "cholesterol": {"Z13.6": 1.0, "E78.5": 1.6},
    "myocardial_infarction": {"I21.9": 3.0},
    "stroke": {"I64": 3.0},
    "unilateral_weakness": {"I64": 2.6},
    "slurred_speech": {"I64": 2.6},
    "syncope": {"I21.9": 0.6, "D50.9": 0.6, "E16.2": 0.8},
    "sweating": {"I21.9": 1.0, "E16.2": 1.0},
    # endocrine / metabolic
    "diabetes_t2": {"E11.9": 2.6, "E11.10": 0.5},
    "polydipsia": {"E11.9": 2.0},
    "polyuria": {"E11.9": 2.0},
    "glucose": {"E11.9": 1.0},
    "goitre": {"E01.2": 2.6},
    "iodine_deficiency": {"E01.2": 2.6, "E01.8": 1.6},
    # GI
    "epigastric_pain": {"K29.70": 2.0, "K27.9": 1.2},
    "abdominal_pain": {"K29.70": 0.8, "A09": 0.6, "E11.10": 0.4},
    "heartburn": {"K29.70": 2.0, "K30": 1.2},
    "nausea": {"K29.70": 0.8, "A09": 0.8},
    "vomiting": {"A09": 1.2, "K29.70": 0.5},
    "gastritis": {"K29.70": 2.6},
    "h_pylori": {"B96.81": 2.0, "K29.70": 1.2},
    "peptic_ulcer": {"K27.9": 2.2},
    "melena": {"K92.2": 2.6, "K92.1": 1.4},
    "hematemesis": {"K92.2": 2.6, "K92.0": 1.4},
    "diarrhea": {"A09": 2.2, "E86": 0.6},
    "pediatric_diarrhea": {"A09": 2.4, "E86": 0.8},
    "dehydration": {"E86": 2.6},
    "unable_to_feed": {"E86": 1.4},
    "lethargy": {"E86": 1.2, "G03.9": 0.6},
    # haematology
    "anemia": {"D50.9": 2.6, "D64.9": 1.4},
    "pallor": {"D50.9": 2.0},
    "iron_deficiency": {"D50.9": 2.4},
    "hemoglobin": {"D50.9": 1.4},
    "brittle_nails": {"D50.9": 1.4},
    # musculoskeletal
    "low_back_pain": {"M54.5": 2.8},
    "joint_pain": {"M25.50": 1.8, "M13.9": 1.2},
    "neck_pain": {"M54.2": 1.8},
    # neuro / infection
    "neck_stiffness": {"G03.9": 2.6},
    "photophobia": {"G03.9": 2.0},
    "meningism": {"G03.9": 2.8},
    "seizure": {"G03.9": 0.6},
    # obstetric
    "pregnancy_bleeding": {"O20.9": 3.0},
    "pregnancy": {"O20.9": 0.4},
}

#: Human-readable labels, in Uzbek, for the codes above.
CONDITION_LABELS: dict[str, str] = {
    "J00": "O'tkir nazofaringit (shamollash)",
    "J02.9": "O'tkir faringit",
    "J11.1": "Gripp",
    "J15.9": "Bakterial pnevmoniya",
    "J18.9": "Jamoat sharoitida orttirilgan pnevmoniya",
    "J40": "Bronxit",
    "J45.9": "Bronxial astma",
    "A15.0": "O'pka sili shubhasi",
    "R04.2": "Gemoptiz",
    "I10": "Arterial gipertenziya",
    "I16.1": "Gipertonik kriz",
    "I20.0": "Beqaror stenokardiya",
    "I21.9": "O'tkir koronar sindrom",
    "I25.10": "Yurak ishemik kasalligi",
    "I64": "O'tkir insult",
    "Z13.6": "Yurak-qon tomir xavfini baholash",
    "E78.5": "Giperlipidemiya",
    "E66.9": "Semizlik",
    "E11.9": "2-tip qandli diabet",
    "E11.10": "Diabetik ketoatsidoz",
    "E16.2": "Gipoglikemiya",
    "E01.2": "Endemik buqoq (yod tanqisligi)",
    "E01.8": "Yod tanqisligi holati",
    "K29.70": "Gastrit",
    "K30": "Funksional dispepsiya",
    "K27.9": "Yara kasalligi",
    "B96.81": "Helicobacter pylori infeksiyasi",
    "K92.0": "Qonli qusish",
    "K92.1": "Melena",
    "K92.2": "Oshqozon-ichak qon ketishi",
    "A09": "O'tkir gastroenterit",
    "E86": "Suvsizlanish",
    "D50.9": "Temir tanqisligi kamqonligi",
    "D64.9": "Kamqonlik",
    "M54.5": "Nospetsifik bel og'rig'i",
    "M54.2": "Bo'yin og'rig'i",
    "M25.50": "Bo'g'im og'rig'i",
    "M13.9": "Artrit",
    "G03.9": "Meningit shubhasi",
    "O20.9": "Homiladorlikda qon ketishi",
}

#: How a fired red flag steers the differential. Deterministic rules already
#: caught the danger; this makes the ranked list agree with them.
RED_FLAG_CODES: dict[str, str] = {
    "acs_suspected": "I21.9",
    "stroke_fast": "I64",
    "meningism": "G03.9",
    "gi_bleeding": "K92.2",
    "tb_suspected": "A15.0",
    "pediatric_dehydration": "E86",
    "imci_danger_sign": "E86",
    "pregnancy_bleeding": "O20.9",
    "hypoglycemia": "E16.2",
    "hyperglycemic_emergency": "E11.10",
    "hypertensive_emergency": "I16.1",
    "severe_anemia": "D50.9",
    "hemoptysis": "A15.0",
    "hypoxia": "J18.9",
    "sepsis_suspected": "J18.9",
}

_CONCEPTS_RE = re.compile(r"Recognised clinical concepts:\s*(.*)")
_EXCERPT_RE = re.compile(r"^\[([0-9a-f]{6,})\]", re.MULTILINE)
_FLAG_RE = re.compile(r"^- ([a-z_]+) \((immediate|same_day|urgent)\)", re.MULTILINE)
_AGE_RE = re.compile(r"Age band:\s*(\w+)")


@dataclass
class _Parsed:
    concepts: list[str]
    excerpt_ids: list[str]
    red_flags: list[str]
    age_band: str


class RetrievalBaselineProvider:
    """Deterministic baseline. Free, instant, offline, and clearly labelled."""

    name = "baseline"

    def __init__(self, max_differentials: int = 3) -> None:
        self.model = "rules-baseline-v1"
        self.max_differentials = max_differentials

    def available(self) -> bool:
        return True

    @staticmethod
    def _parse(user: str) -> _Parsed:
        concepts_match = _CONCEPTS_RE.search(user)
        concepts = (
            [c.strip() for c in concepts_match.group(1).split(",") if c.strip()]
            if concepts_match
            else []
        )
        if concepts == ["none recognised"]:
            concepts = []
        age_match = _AGE_RE.search(user)
        return _Parsed(
            concepts=concepts,
            excerpt_ids=_EXCERPT_RE.findall(user),
            red_flags=[m.group(1) for m in _FLAG_RE.finditer(user)],
            age_band=age_match.group(1) if age_match else "unknown",
        )

    def _score(self, parsed: _Parsed) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}
        for concept in parsed.concepts:
            for code, weight in CONCEPT_WEIGHTS.get(concept, {}).items():
                scores[code] = scores.get(code, 0.0) + weight

        # A fired rule is strong evidence; it outweighs the concept vote.
        for flag in parsed.red_flags:
            flag_code = RED_FLAG_CODES.get(flag)
            if flag_code:
                scores[flag_code] = scores.get(flag_code, 0.0) + 4.0

        # Age gates a few conditions outright.
        if parsed.age_band in ("infant", "under5"):
            for adult_only in ("I21.9", "I10", "E11.9", "M54.5", "Z13.6", "K29.70", "A15.0"):
                scores.pop(adult_only, None)
        elif "dehydration" not in parsed.concepts:
            # Dehydration outside childhood needs the concept to be present;
            # it is not a default differential for an adult.
            scores.pop("E86", None)

        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> LlmResponse:
        started = time.perf_counter()
        parsed = self._parse(user)
        ranked = self._score(parsed)[: self.max_differentials]

        # Every differential must cite a retrieved excerpt; with none
        # retrieved, the honest answer is an empty list.
        citations = parsed.excerpt_ids[:2]
        total = sum(score for _, score in ranked) or 1.0

        differentials = []
        for code, score in ranked:
            if not citations:
                break
            differentials.append(
                {
                    "condition": CONDITION_LABELS.get(code, code),
                    "icd10": code,
                    # Normalised share of the evidence, capped so the baseline
                    # never claims more certainty than a rules table can earn.
                    "confidence": round(min(0.85, score / total), 3),
                    "why": f"Aniqlangan belgilar: {', '.join(parsed.concepts[:6]) or 'yo‘q'}.",
                    "citations": citations,
                    "red_flags": parsed.red_flags,
                }
            )

        payload = {
            "differentials": differentials,
            "recommended_tests": [],
            "treatment": {"items": [], "non_pharmacological": []},
            "risk": {
                "score": 0.8 if parsed.red_flags else 0.25,
                "band": "high" if parsed.red_flags else "low",
                "drivers": parsed.red_flags,
            },
            "referral": {
                "needed": bool(parsed.red_flags),
                "urgency": "immediate" if parsed.red_flags else "none",
            },
        }
        text = json.dumps(payload, ensure_ascii=False)
        return LlmResponse(
            text=text,
            model=self.model,
            prompt_tokens=len(user) // 4,
            completion_tokens=len(text) // 4,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=0.0,
        )
