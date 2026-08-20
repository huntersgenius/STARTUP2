"""The diagnostic pipeline.

    normalize → de-identify → retrieve → route → reason → ground → constrain → present

Each stage is a method, each is independently testable, and the order is not
negotiable: de-identification happens before anything leaves the process, and
red flags are computed before the model is called at all, so no model failure
can suppress them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from knowledge.formulary import FormularyService
from knowledge.terminology import get_terminology
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.cache import SemanticCache, context_bucket
from app.ai.deident import assert_no_pii, deidentify_payload, input_hash
from app.ai.providers.base import LlmUnavailable
from app.ai.providers.embeddings import get_embeddings
from app.ai.rag.retriever import HybridRetriever, RetrievedChunk
from app.ai.red_flags import CaseFacts, RedFlag, evaluate
from app.ai.router import Budget, ModelRouter, RoutingDecision, choose_tier
from app.ai.schema import (
    ClinicalSuggestion,
    Differential,
    RedFlagOut,
    Referral,
    RiskScore,
    SchemaValidationError,
    Treatment,
    TreatmentItem,
    parse_response,
)
from app.core.config import get_settings
from app.core.i18n import translate
from app.models.consultation import Consultation
from app.models.patient import Patient

logger = logging.getLogger("sihhatai.ai.engine")

MAX_SCHEMA_RETRIES = 2

#: Below this age a dose may never be given without a recorded weight.
PEDIATRIC_AGE_LIMIT = 12


@dataclass
class NormalizedCase:
    """The canonical symptom object every downstream stage reads."""

    chief_complaint: str
    language: str
    concepts: list[str]
    icd10_candidates: list[str]
    age_years: float | None
    age_band: str
    sex: str
    pregnant: bool
    chronic_flags: list[str]
    vitals: dict[str, Any]
    structured_symptoms: dict[str, Any]
    duration_days: float | None
    clinic_tier: int
    offline: bool

    @property
    def is_pediatric(self) -> bool:
        return self.age_years is not None and self.age_years < PEDIATRIC_AGE_LIMIT

    @property
    def weight_kg(self) -> float | None:
        weight = self.vitals.get("weight_kg")
        return float(weight) if weight is not None else None


@dataclass
class EngineResult:
    suggestion: ClinicalSuggestion
    model: str
    prompt_version: str
    input_hash: str
    latency_ms: int
    cost_usd: float
    degraded: bool
    cache_hit: bool
    raw_output: str | None
    #: What actually happened, for the audit row and for debugging.
    trace: dict[str, Any] = field(default_factory=dict)


#: Duration phrases the terminology map recognises, in days.
_DURATION_DAYS = {
    "onset_1d": 1.0,
    "onset_3d": 3.0,
    "onset_1w": 7.0,
    "onset_2w": 14.0,
    "onset_1m": 30.0,
    "onset_over_3w": 21.0,
}


class DiagnosticEngine:
    def __init__(
        self,
        db: Session,
        *,
        router: ModelRouter | None = None,
        retriever: HybridRetriever | None = None,
        cache: SemanticCache | None = None,
        prompt_version: str = prompts.DEFAULT_VERSION,
    ) -> None:
        self.db = db
        self.settings = get_settings()
        self.router = router or ModelRouter()
        self.retriever = retriever or HybridRetriever(db)
        self.cache = cache if cache is not None else SemanticCache()
        self.formulary = FormularyService(db)
        self.terminology = get_terminology()
        self.embeddings = get_embeddings()
        self.prompt_dir = prompt_version
        self.prompt_version = prompts.prompt_version(prompt_version)

    # --- 1. normalize ----------------------------------------------------
    def normalize(
        self,
        consultation: Consultation,
        patient: Patient,
        *,
        clinic_tier: int = 1,
        offline: bool = False,
    ) -> NormalizedCase:
        text_parts = [consultation.chief_complaint]
        symptoms = consultation.structured_symptoms or {}
        for value in symptoms.values():
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, list):
                text_parts.extend(str(v) for v in value)
        combined = " ".join(text_parts)

        concepts = self.terminology.clinical_concepts(combined)
        vitals = dict(consultation.vitals or {})
        # Vitals are structured, so they contribute concepts directly rather
        # than being re-derived from prose.
        concepts.extend(c for c in self._vital_concepts(vitals) if c not in concepts)

        duration = next(
            (_DURATION_DAYS[c] for c in concepts if c in _DURATION_DAYS),
            symptoms.get("duration_days"),
        )

        return NormalizedCase(
            chief_complaint=consultation.chief_complaint,
            language=consultation.language,
            concepts=concepts,
            icd10_candidates=self.terminology.icd10_candidates(combined),
            age_years=patient.age_years,
            age_band=patient.age_band,
            sex=patient.sex.value if hasattr(patient.sex, "value") else str(patient.sex),
            pregnant=bool(symptoms.get("pregnant")) or "pregnancy" in concepts,
            chronic_flags=list(patient.chronic_flags or []),
            vitals=vitals,
            structured_symptoms=symptoms,
            duration_days=float(duration) if duration is not None else None,
            clinic_tier=clinic_tier,
            offline=offline,
        )

    @staticmethod
    def _vital_concepts(vitals: dict[str, Any]) -> list[str]:
        concepts: list[str] = []
        temperature = vitals.get("temperature_c")
        if temperature is not None and float(temperature) >= 38.0:
            concepts.append("fever")
        systolic = vitals.get("systolic_bp")
        diastolic = vitals.get("diastolic_bp")
        if (systolic and float(systolic) >= 140) or (diastolic and float(diastolic) >= 90):
            concepts.append("hypertension")
        spo2 = vitals.get("spo2")
        if spo2 is not None and float(spo2) < 92:
            concepts.append("dyspnea")
        glucose = vitals.get("glucose_mmol")
        if glucose is not None and float(glucose) >= 7.0:
            concepts.append("diabetes_t2")
        return concepts

    # --- red flags (before any model call) -------------------------------
    def red_flags(self, case: NormalizedCase) -> list[RedFlag]:
        return evaluate(
            CaseFacts(
                concepts=set(case.concepts),
                age_years=case.age_years,
                age_band=case.age_band,
                sex=case.sex,
                pregnant=case.pregnant,
                temperature_c=_as_float(case.vitals.get("temperature_c")),
                pulse_bpm=_as_int(case.vitals.get("pulse_bpm")),
                systolic_bp=_as_int(case.vitals.get("systolic_bp")),
                diastolic_bp=_as_int(case.vitals.get("diastolic_bp")),
                respiratory_rate=_as_int(case.vitals.get("respiratory_rate")),
                spo2=_as_int(case.vitals.get("spo2")),
                weight_kg=_as_float(case.vitals.get("weight_kg")),
                glucose_mmol=_as_float(case.vitals.get("glucose_mmol")),
                duration_days=case.duration_days,
                free_text=case.chief_complaint,
            )
        )

    # --- 2. de-identify --------------------------------------------------
    def deidentify(
        self, case: NormalizedCase, patient: Patient
    ) -> tuple[dict[str, Any], dict[str, str]]:
        try:
            pii = patient.get_pii()
        except Exception:  # noqa: BLE001 - a decrypt failure must not leak, just degrade
            logger.exception("could not decrypt patient PII; proceeding with pattern layer only")
            pii = {}

        known_values = [str(v) for v in pii.values() if v]
        payload = {
            "chief_complaint": case.chief_complaint,
            "structured_symptoms": case.structured_symptoms,
            "vitals": case.vitals,
            "chronic_flags": case.chronic_flags,
        }
        scrubbed, mapping = deidentify_payload(payload, known_values=known_values)
        # The last line of defence, on the exact object about to be serialised.
        assert_no_pii(scrubbed, known_values)
        return scrubbed, mapping

    # --- 3. retrieve -----------------------------------------------------
    def retrieve(
        self, case: NormalizedCase, scrubbed: dict[str, Any], limit: int = 6
    ) -> list[RetrievedChunk]:
        query = " ".join(
            [str(scrubbed.get("chief_complaint", "")), " ".join(case.concepts)]
        ).strip()
        # ICD-10 is deliberately not passed as a filter here. The candidates
        # come from symptoms (R05 cough, R50.9 fever) while protocols are
        # labelled with conditions (J18.9 pneumonia); requiring an intersection
        # excludes every relevant protocol. The codes still reach the model in
        # the prompt, where they are useful context. The retriever keeps the
        # icd10 filter for callers who know the diagnosis already.
        return self.retriever.retrieve(
            query,
            limit=limit,
            language=case.language,
            age_band=case.age_band,
            sex=case.sex if case.sex in ("male", "female") else None,
        )

    # --- 4. route --------------------------------------------------------
    def route(
        self, case: NormalizedCase, red_flags: list[RedFlag], *, clinic_offline_mode: bool = False
    ) -> RoutingDecision:
        return choose_tier(
            concepts=set(case.concepts),
            red_flags=len(red_flags),
            offline=case.offline,
            clinic_offline_mode=clinic_offline_mode,
        )

    # --- 5. reason -------------------------------------------------------
    def build_prompt(
        self,
        case: NormalizedCase,
        scrubbed: dict[str, Any],
        chunks: list[RetrievedChunk],
        red_flags: list[RedFlag],
    ) -> tuple[str, str]:
        system = prompts.load("system", self.prompt_dir)
        template = prompts.load("diagnose", self.prompt_dir)

        excerpts = (
            "\n\n".join(f"[{chunk.id[:8]}] ({chunk.citation})\n{chunk.text}" for chunk in chunks)
            or "No protocol excerpts retrieved. Do not invent citations; return insufficient_data."
        )

        available = self.formulary.available_at_tier(case.clinic_tier)
        formulary_text = (
            "\n".join(
                f"- {item.generic_name} {item.strength or ''} ({item.form})".strip()
                for item in available
            )
            or "No formulary loaded."
        )

        vitals_text = (
            "\n".join(f"- {k}: {v}" for k, v in (scrubbed.get("vitals") or {}).items())
            or "None recorded."
        )
        flags_text = (
            "\n".join(f"- {f.code} ({f.urgency.value}): {f.message('en')}" for f in red_flags)
            or "None."
        )
        age_detail = f" ({case.age_years:.0f} years)" if case.age_years is not None else ""

        user = template.format(
            age_band=case.age_band,
            age_detail=age_detail,
            sex=case.sex,
            pregnant="yes" if case.pregnant else "no/unknown",
            # From `scrubbed`, not `case`: chronic flags are free text a
            # clinician typed and can carry a name.
            chronic_flags=", ".join(scrubbed.get("chronic_flags") or []) or "none recorded",
            vitals=vitals_text,
            language=case.language,
            chief_complaint=scrubbed.get("chief_complaint", ""),
            concepts=", ".join(case.concepts) or "none recognised",
            icd10_candidates=", ".join(case.icd10_candidates) or "none",
            duration=f"{case.duration_days:.0f} days" if case.duration_days else "not stated",
            red_flags=flags_text,
            protocol_excerpts=excerpts,
            formulary=formulary_text,
            clinic_tier=case.clinic_tier,
        )
        return system, user

    def reason(
        self, system: str, user: str, decision: RoutingDecision, budget: Budget
    ) -> tuple[ClinicalSuggestion | None, dict[str, Any]]:
        """Call the model, validating and retrying on a malformed response."""
        trace: dict[str, Any] = {"attempts": [], "schema_errors": []}
        current_user = user

        for attempt in range(MAX_SCHEMA_RETRIES + 1):
            try:
                result = self.router.complete(
                    system=system, user=current_user, decision=decision, budget=budget
                )
            except LlmUnavailable as exc:
                trace["attempts"].append({"attempt": attempt, "error": str(exc)})
                return None, trace

            trace["attempts"].append(
                {
                    "attempt": attempt,
                    "provider": result.provider_name,
                    "model": result.response.model,
                    "latency_ms": result.response.latency_ms,
                    "cost_usd": result.response.cost_usd,
                    "degraded": result.degraded,
                }
            )
            # `raw_output` is returned to the caller so it can be persisted on
            # AiSuggestion, then popped before the trace is written to the
            # audit metadata — that metadata is exported to the regulator as
            # CSV, and it should carry the length, not the model's prose.
            trace["raw_output"] = result.response.text
            trace["response_chars"] = len(result.response.text)
            trace["model"] = result.response.model
            trace["degraded"] = result.degraded

            try:
                return parse_response(result.response.text), trace
            except SchemaValidationError as exc:
                trace["schema_errors"].append(str(exc))
                logger.warning("schema validation failed (attempt %s): %s", attempt, exc)
                current_user = (
                    f"{user}\n\n## Your previous response was rejected\n"
                    f"Error: {exc}\nReturn ONLY a valid JSON object matching the schema."
                )

        return None, trace

    # --- 6. ground -------------------------------------------------------
    def ground(
        self, suggestion: ClinicalSuggestion, chunks: list[RetrievedChunk]
    ) -> tuple[ClinicalSuggestion, list[str]]:
        """Drop any differential that cannot cite a retrieved chunk.

        An uncited differential is either a hallucination or knowledge we
        cannot show the clinician the basis for. Either way it does not go on
        the screen.
        """
        valid_ids = {chunk.id[:8] for chunk in chunks} | {chunk.id for chunk in chunks}
        kept: list[Differential] = []
        dropped: list[str] = []

        for differential in suggestion.differentials:
            citations = [c for c in differential.citations if c.strip("[] ") in valid_ids]
            if citations:
                kept.append(differential.model_copy(update={"citations": citations}))
            else:
                dropped.append(differential.condition)

        suggestion.differentials = kept
        if dropped:
            logger.info("dropped %d uncited differentials: %s", len(dropped), dropped)
        return suggestion, dropped

    # --- 7. constrain ----------------------------------------------------
    def constrain_treatment(
        self, suggestion: ClinicalSuggestion, case: NormalizedCase
    ) -> ClinicalSuggestion:
        """Cross-check every suggested drug against the national formulary."""
        constrained: list[TreatmentItem] = []

        for item in suggestion.treatment.items:
            verdict = self.formulary.check(
                item.drug,
                clinic_tier=case.clinic_tier,
                pediatric=case.is_pediatric,
                pregnant=case.pregnant,
            )
            update: dict[str, Any] = {}
            if verdict.controlled:
                # Never output a controlled substance. Drop the item entirely.
                logger.warning("dropped controlled substance suggestion: %s", item.drug)
                continue
            if verdict.available:
                update["local_availability"] = "available"
            elif verdict.substitute is not None:
                update["local_availability"] = "substitute_suggested"
                update["substitute"] = verdict.substitute.generic_name
                update["notes"] = _append_note(
                    item.notes,
                    f"Not stocked here ({verdict.reason}); consider {verdict.substitute.generic_name}.",
                )
            else:
                update["local_availability"] = "unavailable"
                update["notes"] = _append_note(
                    item.notes, f"Not available locally ({verdict.reason})."
                )
            constrained.append(item.model_copy(update=update))

        suggestion.treatment.items = constrained

        # A paediatric dose without a weight is blocked outright, whatever the
        # model produced.
        if case.is_pediatric and case.weight_kg is None and any(i.dose for i in constrained):
            suggestion.treatment.items = [i.model_copy(update={"dose": None}) for i in constrained]
            suggestion.treatment.blocked_reason = "pediatric_weight_required"
            suggestion.treatment.notes = _append_note(
                suggestion.treatment.notes,
                translate("error.pediatric_weight_required", case.language),
            )
        return suggestion

    # --- 8. present ------------------------------------------------------
    def present(
        self, suggestion: ClinicalSuggestion, case: NormalizedCase, red_flags: list[RedFlag]
    ) -> ClinicalSuggestion:
        suggestion.red_flags = [
            RedFlagOut(
                code=flag.code,
                urgency=flag.urgency.value,
                message=flag.message(case.language),
                refer_to=flag.refer_to,
                triggered_by=list(flag.triggered_by),
            )
            for flag in red_flags
        ]

        # Low confidence means questions, not a ranked guess.
        if (
            suggestion.differentials
            and suggestion.top_confidence < self.settings.min_confidence_to_rank
        ):
            suggestion.insufficient_data = True
            if not suggestion.follow_up_questions:
                suggestion.follow_up_questions = _default_questions(case)
            suggestion.differentials = []
        if not suggestion.differentials and not suggestion.red_flags:
            suggestion.insufficient_data = True
            if not suggestion.follow_up_questions:
                suggestion.follow_up_questions = _default_questions(case)

        # Re-run the validator so a red flag forces referral even if the model
        # or a later stage changed the referral block.
        return ClinicalSuggestion.model_validate(suggestion.model_dump())

    # --- degradation -----------------------------------------------------
    def rules_only(self, case: NormalizedCase, red_flags: list[RedFlag]) -> ClinicalSuggestion:
        """What the clinician gets when every model is unavailable.

        Deliberately not empty: the deterministic layer is the part that
        catches the dangerous cases, and it still works.
        """
        suggestion = ClinicalSuggestion(
            differentials=[],
            treatment=Treatment(),
            risk=RiskScore(
                score=0.5 if red_flags else 0.1,
                band="high" if red_flags else "low",
                drivers=[f.code for f in red_flags],
            ),
            referral=Referral(
                needed=bool(red_flags),
                specialty=red_flags[0].refer_to if red_flags else None,
                urgency=red_flags[0].urgency.value if red_flags else "none",
                reason=red_flags[0].message(case.language) if red_flags else None,
            ),
            insufficient_data=True,
            follow_up_questions=_default_questions(case),
        )
        return self.present(suggestion, case, red_flags)

    # --- orchestration ---------------------------------------------------
    def analyze(
        self,
        consultation: Consultation,
        patient: Patient,
        *,
        clinic_tier: int = 1,
        clinic_offline_mode: bool = False,
        offline: bool = False,
    ) -> EngineResult:
        started = time.perf_counter()
        budget = Budget(
            max_cost_usd=self.settings.cost_ceiling_per_consultation_usd,
            max_latency_ms=self.settings.latency_budget_ms,
        )

        case = self.normalize(consultation, patient, clinic_tier=clinic_tier, offline=offline)
        red_flags = self.red_flags(case)
        scrubbed, _mapping = self.deidentify(case, patient)
        chunks = self.retrieve(case, scrubbed)
        decision = self.route(case, red_flags, clinic_offline_mode=clinic_offline_mode)
        system, user = self.build_prompt(case, scrubbed, chunks, red_flags)

        trace: dict[str, Any] = {
            "concepts": case.concepts,
            "red_flags": [f.code for f in red_flags],
            "routing": {"tier": decision.tier.value, "reason": decision.reason},
            "retrieved": [
                {"id": c.id[:8], "source": c.source_id, "score": round(c.score, 4)} for c in chunks
            ],
        }

        # Cache lookup happens after routing, because the bucket depends on it.
        bucket = context_bucket(
            age_band=case.age_band,
            sex=case.sex,
            pregnant=case.pregnant,
            language=case.language,
            red_flag_codes=[f.code for f in red_flags],
            prompt_version=self.prompt_version,
            model_tier=decision.tier.value,
        )
        query_vector = self.embeddings.embed([f"{case.chief_complaint} {' '.join(case.concepts)}"])[
            0
        ]
        cached = self.cache.get(bucket, query_vector) if self.cache else None

        suggestion: ClinicalSuggestion | None = None
        cache_hit = False
        raw_output: str | None = None
        model_name = "rules-only"
        degraded = False

        if cached is not None:
            try:
                suggestion = parse_response(cached.response)
                cache_hit = True
                raw_output = cached.response
                model_name = f"{cached.model} (cached)"
                trace["cache"] = {"hit": True, "model": cached.model}
            except SchemaValidationError:
                # A poisoned cache entry must not break the consultation.
                logger.warning("discarding malformed cache entry")
                suggestion = None

        if suggestion is None:
            trace.setdefault("cache", {"hit": False})
            suggestion, reason_trace = self.reason(system, user, decision, budget)
            raw_output = reason_trace.pop("raw_output", None)
            trace["reasoning"] = reason_trace
            model_name = reason_trace.get("model", "rules-only")
            degraded = bool(reason_trace.get("degraded", False))

            if suggestion is not None and self.cache is not None:
                self.cache.put(
                    bucket,
                    query_vector,
                    raw_output or "",
                    model=model_name,
                    prompt_version=self.prompt_version,
                    degraded=degraded,
                )

        if suggestion is None:
            # Every model failed or every response was malformed.
            degraded = True
            suggestion = self.rules_only(case, red_flags)
            trace["degradation"] = "rules_only"
        else:
            suggestion, dropped = self.ground(suggestion, chunks)
            if dropped:
                trace["dropped_uncited"] = dropped
            suggestion = self.constrain_treatment(suggestion, case)
            suggestion = self.present(suggestion, case, red_flags)

        return EngineResult(
            suggestion=suggestion,
            model=model_name,
            prompt_version=self.prompt_version,
            input_hash=input_hash(scrubbed),
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=round(budget.spent_usd, 6),
            degraded=degraded,
            cache_hit=cache_hit,
            raw_output=raw_output,
            trace=trace,
        )


def _append_note(existing: str | None, addition: str) -> str:
    return f"{existing} {addition}".strip() if existing else addition


def _default_questions(case: NormalizedCase) -> list[str]:
    """Targeted questions, in the clinician's language, when data is thin."""
    questions = {
        "uz": [
            "Shikoyat qachon boshlangan va qanday o'zgargan?",
            "Harorat o'lchandimi? Necha daraja?",
            "Boshqa qanday belgilar bor (nafas qisishi, og'riq, qusish)?",
            "Qanday dorilar qabul qilinmoqda?",
            "Surunkali kasalliklar yoki allergiya bormi?",
        ],
        "ru": [
            "Когда началась жалоба и как менялась?",
            "Измерялась ли температура? Сколько?",
            "Какие ещё есть симптомы (одышка, боль, рвота)?",
            "Какие лекарства принимает пациент?",
            "Есть ли хронические заболевания или аллергия?",
        ],
        "en": [
            "When did this start and how has it changed?",
            "Has the temperature been measured? What was it?",
            "What other symptoms are present (breathlessness, pain, vomiting)?",
            "What medicines is the patient taking?",
            "Any chronic conditions or allergies?",
        ],
    }
    base = questions.get(case.language, questions["en"])
    if case.is_pediatric and case.weight_kg is None:
        weight_question = {
            "uz": "Bolaning vazni necha kg?",
            "ru": "Какой вес ребёнка в кг?",
            "en": "What is the child's weight in kg?",
        }[case.language if case.language in ("uz", "ru") else "en"]
        return [weight_question, *base]
    return base


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
