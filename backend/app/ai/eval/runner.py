"""Runs the evaluation set through the real engine."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.engine import DiagnosticEngine
from app.ai.eval.schema import CaseResult, Vignette
from app.ai.providers.base import LlmProvider
from app.ai.providers.baseline import RetrievalBaselineProvider
from app.ai.rag.retriever import HybridRetriever
from app.ai.router import ModelRouter
from app.models import Base, Clinic, ClinicType, Consultation, Patient, Sex, User, UserRole

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"
VIGNETTES_PATH = DATA_DIR / "vignettes.json"


def load_vignettes(path: Path = VIGNETTES_PATH) -> list[Vignette]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Vignette.from_json(item) for item in payload["vignettes"]]


def provenance_note(path: Path = VIGNETTES_PATH) -> str:
    return json.loads(path.read_text(encoding="utf-8")).get("provenance_note", "")


def build_session() -> Session:
    """An in-memory database seeded with the committed knowledge base."""
    from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents, load_formulary

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    ingest_documents(session, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(session, Path(DEFAULT_CORPUS).parent / "formulary.csv")
    session.commit()
    return session


def _seed_clinic(session: Session) -> tuple[Clinic, User]:
    clinic = Clinic(name="Eval QVP", region="Eval", type=ClinicType.gov, tier=2, offline_mode=False)
    session.add(clinic)
    session.flush()
    user = User(
        email=f"eval-{uuid.uuid4().hex[:8]}@sihhat.uz",
        full_name="Eval Runner",
        hashed_password="x" * 60,
        role=UserRole.doctor,
        clinic_id=clinic.id,
    )
    session.add(user)
    session.flush()
    return clinic, user


def _make_patient(session: Session, clinic: Clinic, vignette: Vignette) -> Patient:
    dob = date.today() - timedelta(days=int(vignette.age_years * 365.25))
    patient = Patient(
        clinic_id=clinic.id,
        mrn=f"P-EVAL{vignette.id[:8].upper()}",
        dob=dob,
        sex=Sex(vignette.sex) if vignette.sex in ("male", "female") else Sex.unknown,
        chronic_flags=list(vignette.chronic_flags),
        pii_blob=b"",
    )
    # Synthetic identifiers, so the de-identification stage is genuinely
    # exercised rather than skipped on empty PII.
    patient.set_pii({"full_name": f"Eval Patient {vignette.id}", "phone": "+998900000000"})
    session.add(patient)
    session.flush()
    return patient


def run_case(
    engine: DiagnosticEngine,
    session: Session,
    clinic: Clinic,
    user: User,
    vignette: Vignette,
    language: str,
) -> CaseResult:
    patient = _make_patient(session, clinic, vignette)
    symptoms: dict = {}
    if vignette.pregnant:
        symptoms["pregnant"] = True
    if vignette.duration_days is not None:
        symptoms["duration_days"] = vignette.duration_days

    consultation = Consultation(
        patient_id=patient.id,
        user_id=user.id,
        clinic_id=clinic.id,
        language=language,
        chief_complaint=vignette.text(language),
        structured_symptoms=symptoms,
        vitals=dict(vignette.vitals),
    )
    session.add(consultation)
    session.flush()

    try:
        result = engine.analyze(consultation, patient, clinic_tier=clinic.tier)
    except Exception as exc:  # noqa: BLE001 - one bad case must not stop the run
        return CaseResult(
            vignette_id=vignette.id,
            language=language,
            category=vignette.category,
            predicted_codes=[],
            predicted_labels=[],
            confidences=[],
            fired_red_flags=[],
            referral_needed=False,
            latency_ms=0,
            cost_usd=0.0,
            degraded=True,
            insufficient_data=True,
            error=f"{type(exc).__name__}: {exc}",
        )

    suggestion = result.suggestion
    return CaseResult(
        vignette_id=vignette.id,
        language=language,
        category=vignette.category,
        predicted_codes=[d.icd10 or "" for d in suggestion.differentials],
        predicted_labels=[d.condition for d in suggestion.differentials],
        confidences=[d.confidence for d in suggestion.differentials],
        fired_red_flags=[f.code for f in suggestion.red_flags],
        referral_needed=suggestion.referral.needed,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        degraded=result.degraded,
        insufficient_data=suggestion.insufficient_data,
    )


def make_engine(
    session: Session, provider: LlmProvider | None = None, prompt_version: str = "v1"
) -> DiagnosticEngine:
    model = provider or RetrievalBaselineProvider()
    return DiagnosticEngine(
        session,
        router=ModelRouter(openai=model, anthropic=model, local=model),
        retriever=HybridRetriever(session),
        # The cache is disabled: a cache hit would measure the cache, not the
        # model, and identical vignettes appear many times in this set.
        cache=None,
        prompt_version=prompt_version,
    )


def run_suite(
    *,
    provider: LlmProvider | None = None,
    languages: tuple[str, ...] = ("uz", "ru"),
    limit: int | None = None,
    prompt_version: str = "v1",
) -> tuple[list[CaseResult], dict[str, Vignette]]:
    vignettes = load_vignettes()
    if limit:
        vignettes = vignettes[:limit]
    lookup = {v.id: v for v in vignettes}

    session = build_session()
    clinic, user = _seed_clinic(session)
    engine = make_engine(session, provider, prompt_version)

    results: list[CaseResult] = []
    for vignette in vignettes:
        for language in languages:
            results.append(run_case(engine, session, clinic, user, vignette, language))
    session.close()
    return results, lookup


def write_results(payload: dict, *, stamp: str | None = None) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(UTC).strftime("%Y-%m-%d")
    path = RESULTS_DIR / f"{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
