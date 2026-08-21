"""Failing tests left by the post-execution audit (2026-08-21).

These are not regressions introduced by the audit. Each one reproduces a P0
defect that exists on `claude/github-startup-repo-3qm5c6` at commit 208e460, and
each is left **failing on purpose** so the defect cannot be closed by argument.
Delete a test only together with the fix that makes it pass.

Run just these:

    cd backend && PYTHONPATH=.. ENVIRONMENT=test \\
      DATABASE_URL="sqlite+pysqlite:///:memory:" python -m pytest tests/test_audit_p0.py -v
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents, load_formulary

from app.ai.cache import InMemoryCacheBackend, SemanticCache
from app.ai.engine import DiagnosticEngine
from app.ai.providers.embeddings import HashingEmbeddings
from app.ai.providers.llm import ScriptedProvider
from app.ai.rag.retriever import HybridRetriever
from app.ai.router import ModelRouter
from app.models.consultation import Consultation
from app.models.patient import Patient, Sex
from tests.test_retrieval import CORPUS

FORMULARY_CSV = CORPUS.parent / "formulary.csv"

#: A patient whose identifiers a clinician has also typed into the free text —
#: the ordinary case, not an adversarial one. Rural notes read like this.
PATIENT_NAME = "Zulfiya Ismoilova"
PATIENT_PHONE = "+998901112233"


class RecordingEmbeddings(HashingEmbeddings):
    """Stands in for `OpenAIEmbeddings`, recording what it was handed.

    `get_embeddings()` returns `OpenAIEmbeddings` whenever `OPENAI_API_KEY` is
    set and the environment is not `test` (app/ai/providers/embeddings.py:79),
    and that class POSTs whatever it receives to api.openai.com
    (embeddings.py:63). So everything this double records is, in production,
    a request body leaving the country.
    """

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.sent.extend(texts)
        return super().embed(texts)


@pytest.fixture()
def knowledge(db):
    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(db, FORMULARY_CSV)
    return db


@pytest.fixture()
def patient(db, clinic_factory):
    clinic = clinic_factory()
    p = Patient(
        clinic_id=clinic.id, mrn="P-AUD0001", dob=date(1979, 3, 8), sex=Sex.female, pii_blob=b""
    )
    p.set_pii({"full_name": PATIENT_NAME, "phone": PATIENT_PHONE})
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def consultation(db, patient, user_factory):
    user = user_factory(patient.clinic)
    c = Consultation(
        patient_id=patient.id,
        user_id=user.id,
        clinic_id=patient.clinic_id,
        language="uz",
        # The clinician typed the patient's name and number into the note.
        chief_complaint=(
            f"Bemor {PATIENT_NAME}, tel {PATIENT_PHONE}. "
            "3 kundan beri balg'amli yo'tal, isitma 38.5, ko'krak og'rig'i"
        ),
        structured_symptoms={},
        vitals={"temperature_c": 38.5, "pulse_bpm": 96, "respiratory_rate": 20},
    )
    db.add(c)
    db.flush()
    return c


def _scripted_response(citation_id: str = "deadbeef") -> str:
    return json.dumps(
        {
            "differentials": [
                {
                    "condition": "Community-acquired pneumonia",
                    "icd10": "J18.9",
                    "confidence": 0.72,
                    "why": "Fever with productive cough.",
                    "red_flags": [],
                    "citations": [citation_id],
                }
            ],
            "recommended_tests": [],
            "treatment": {"items": [], "non_pharmacological": []},
            "risk": {"score": 0.4, "band": "moderate", "drivers": []},
            "referral": {"needed": False, "urgency": "none"},
        }
    )


def _engine(db, embeddings: RecordingEmbeddings) -> DiagnosticEngine:
    scripted = ScriptedProvider(default=_scripted_response())
    engine = DiagnosticEngine(
        db,
        router=ModelRouter(openai=scripted, anthropic=scripted, local=scripted),
        retriever=HybridRetriever(db, embeddings=embeddings),
        cache=SemanticCache(backend=InMemoryCacheBackend()),
    )
    # Production resolves this through get_embeddings(); the double records.
    engine.embeddings = embeddings
    return engine


# ---------------------------------------------------------------------------
# AUD-001 — raw chief complaint reaches the embedding provider
# ---------------------------------------------------------------------------


def test_raw_chief_complaint_is_not_sent_to_the_embedding_provider(
    knowledge, consultation, patient
):
    """P0. The de-identified payload is not the only thing that leaves.

    `DiagnosticEngine.analyze` builds the semantic-cache key from
    `case.chief_complaint` (app/ai/engine.py:571) — the raw column, not the
    `scrubbed` dict that `deidentify()` produced and that `assert_no_pii`
    checked. The retrieval arm on the line above uses the scrubbed text
    (engine.py:243-248), so the scrubbing is deliberate everywhere except here.

    In production `self.embeddings` is `OpenAIEmbeddings`, so this string is
    the body of an HTTPS request to api.openai.com: a patient name and phone
    number sent to a third-party model outside Uzbekistan, which is both a
    reportable breach and a data-residency violation.
    """
    embeddings = RecordingEmbeddings()
    engine = _engine(knowledge, embeddings)

    engine.analyze(consultation, patient, clinic_tier=2)

    outbound = " || ".join(embeddings.sent)
    assert PATIENT_NAME not in outbound, (
        "patient name was handed to the embedding provider; in production that "
        "is an HTTPS POST to api.openai.com"
    )
    assert PATIENT_PHONE not in outbound, (
        "patient phone number was handed to the embedding provider"
    )


def test_assert_no_pii_covers_every_outbound_payload_not_just_the_prompt(
    knowledge, consultation, patient
):
    """P0, same root cause, stated as the general rule.

    `assert_no_pii` runs once, inside `deidentify()`, on the `scrubbed` dict
    (engine.py:236). Nothing asserts on the bytes actually handed to an
    outbound client. This test states the invariant the code should hold:
    every string that reaches a network-capable provider is free of the
    patient's known identifiers.
    """
    embeddings = RecordingEmbeddings()
    engine = _engine(knowledge, embeddings)
    engine.analyze(consultation, patient, clinic_tier=2)

    pii = patient.get_pii()
    known = [str(v) for v in pii.values() if v and len(str(v)) > 2]
    leaked = sorted({v for v in known for text in embeddings.sent if v in text})
    assert leaked == [], f"{len(leaked)} identifier(s) reached an outbound provider"
