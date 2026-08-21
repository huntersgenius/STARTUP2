"""Reproduction script for the post-execution audit (2026-08-21).

Every number and behavioural claim in `audit/01-findings.md` that concerns the
backend is produced by a test in this file. Tests named `test_probe_*` are
observations — they pass, and they print what they observed. Tests named
`test_defect_*` assert the behaviour the system should have and **fail**,
because it does not.

    cd backend && PYTHONPATH=..:../audit/adversarial ENVIRONMENT=test \\
      DATABASE_URL="sqlite+pysqlite:///:memory:" \\
      python -m pytest ../audit/adversarial/test_audit_probes.py -v -s

Fixtures come from `backend/tests/conftest.py`, so the audit runs against the
same wiring the project's own suite uses.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from knowledge.formulary import FormularyService
from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents, load_formulary

from app.ai.cache import InMemoryCacheBackend, SemanticCache
from app.ai.engine import DiagnosticEngine
from app.ai.providers.base import LlmUnavailable
from app.ai.rag.retriever import HybridRetriever
from app.ai.router import ModelRouter
from app.core import audit as audit_mod
from app.models.consultation import Consultation
from app.models.patient import Patient, Sex
from tests.test_retrieval import CORPUS

FORMULARY_CSV = CORPUS.parent / "formulary.csv"

#: Drugs a clinical model can plausibly name, none of which are in
#: knowledge/formulary.csv.
CONTROLLED_DRUGS = ["morphine", "tramadol", "diazepam", "fentanyl", "phenobarbital"]


@pytest.fixture()
def knowledge(db):
    ingest_documents(db, load_documents(DEFAULT_CORPUS), prefer_offline=True)
    load_formulary(db, FORMULARY_CSV)
    return db


@pytest.fixture()
def patient(db, clinic_factory):
    clinic = clinic_factory()
    p = Patient(
        clinic_id=clinic.id, mrn="P-PROBE01", dob=date(1979, 3, 8), sex=Sex.female, pii_blob=b""
    )
    p.set_pii({"full_name": "Zulfiya Ismoilova", "phone": "+998901112233"})
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
        chief_complaint="3 kundan beri balg'amli yo'tal, isitma 38.5, ko'krak og'rig'i",
        structured_symptoms={},
        vitals={"temperature_c": 38.5, "pulse_bpm": 96, "respiratory_rate": 20},
    )
    db.add(c)
    db.flush()
    return c


def _response_with_drug(drug: str, citation: str = "deadbeef") -> str:
    return json.dumps(
        {
            "differentials": [
                {
                    "condition": "Community-acquired pneumonia",
                    "icd10": "J18.9",
                    "confidence": 0.72,
                    "why": "Fever with productive cough.",
                    "red_flags": [],
                    "citations": [citation],
                }
            ],
            "recommended_tests": [],
            "treatment": {
                "items": [
                    {"drug": drug, "dose": "10 mg", "route": "oral", "duration": "3 days"}
                ],
                "non_pharmacological": [],
            },
            "risk": {"score": 0.4, "band": "moderate", "drivers": []},
            "referral": {"needed": False, "urgency": "none"},
        }
    )


class _Provider:
    """Returns a fixed body, or raises, on demand."""

    name = "probe"
    model = "probe-1"

    def __init__(self, body: str | None = None, raises: Exception | None = None) -> None:
        self.body = body
        self.raises = raises
        self.calls = 0

    def available(self) -> bool:
        return True

    def complete(self, *, system: str, user: str, **kw):
        from app.ai.providers.base import LlmResponse

        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return LlmResponse(
            text=self.body or "",
            model=self.model,
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
            cost_usd=0.0,
        )


def _engine(db, provider) -> DiagnosticEngine:
    return DiagnosticEngine(
        db,
        router=ModelRouter(openai=provider, anthropic=provider, local=provider),
        retriever=HybridRetriever(db),
        cache=SemanticCache(backend=InMemoryCacheBackend()),
    )


# ===========================================================================
# AUD-002 — the controlled-substance block is unreachable with shipped data
# ===========================================================================


def test_probe_formulary_contains_no_controlled_substance(knowledge):
    """Observation: the `controlled` column is false on all 49 rows."""
    from app.models.knowledge import FormularyItem as FormularyRow

    rows = knowledge.execute(sa.select(FormularyRow)).scalars().all()
    controlled = [r for r in rows if r.controlled]
    print(f"\n  formulary rows: {len(rows)}; controlled=true: {len(controlled)}")
    assert rows, "formulary did not load"
    assert controlled == [], "if this ever fails, the finding below has changed"


def test_probe_unknown_drug_is_not_reported_as_controlled(knowledge):
    """Observation: `check()` cannot classify a drug it has never heard of."""
    service = FormularyService(knowledge)
    for drug in CONTROLLED_DRUGS:
        verdict = service.check(drug, clinic_tier=2)
        print(f"  {drug:<15} controlled={verdict.controlled}  reason={verdict.reason}")
        assert verdict.controlled is False
        assert verdict.reason == "not_in_national_formulary"


def test_defect_controlled_substance_is_never_emitted(knowledge, consultation, patient):
    """P1 (AUD-002). `constrain_treatment` claims "Never output a controlled substance".

    It drops an item only when `verdict.controlled` is true, and that flag is
    read from `knowledge/formulary.csv`, where no row sets it. An opioid the
    model names is therefore not dropped: it reaches the clinician's screen
    carrying "Not available locally", which reads as a stocking problem rather
    than a prohibition.
    """
    emitted = []
    for drug in CONTROLLED_DRUGS:
        engine = _engine(knowledge, _Provider(body=_response_with_drug(drug)))
        result = engine.analyze(consultation, patient, clinic_tier=2)
        drugs = [i.drug for i in result.suggestion.treatment.items]
        if drug in drugs:
            emitted.append(drug)
    assert emitted == [], (
        f"{len(emitted)} controlled substance(s) survived constrain_treatment: {emitted}"
    )


# ===========================================================================
# AUD-003 — the append-only guarantee is not exercised by the test suite
# ===========================================================================


def test_defect_audit_log_rows_cannot_be_updated(db):
    """P2 (AUD-006). Immutability is a Postgres trigger; the suite runs on SQLite.

    `b1a2c3d4e5f6_audit_append_only.py` installs a trigger that makes UPDATE
    and DELETE on `audit_logs` fail. Tests build their schema with
    `Base.metadata.create_all` (backend/tests/conftest.py:36), which does not
    run migrations, so the trigger does not exist and `test_audit.py` verifies
    only that the application has no update path — not that the database
    refuses one.
    """
    row = audit_mod.record(
        db, action="probe.write", entity_type="probe", metadata={"n": 1}
    )
    original_hash = row.hash

    db.execute(
        sa.text("UPDATE audit_logs SET action = :a WHERE id = :i"),
        {"a": "probe.tampered", "i": str(row.id)},
    )
    db.flush()
    tampered = db.execute(
        sa.text("SELECT action FROM audit_logs WHERE id = :i"), {"i": str(row.id)}
    ).scalar_one()

    assert tampered == "probe.write", (
        "the database accepted an UPDATE on audit_logs; on this engine the "
        "append-only guarantee is application convention only"
    )
    assert original_hash


def test_probe_chain_verification_still_detects_the_tamper(db):
    """Observation: the hash chain does its job even where the trigger does not."""
    audit_mod.record(db, action="probe.a", entity_type="probe", metadata={})
    row = audit_mod.record(db, action="probe.b", entity_type="probe", metadata={})
    db.execute(
        sa.text("UPDATE audit_logs SET action = 'tampered' WHERE id = :i"), {"i": str(row.id)}
    )
    db.flush()
    # Without this the ORM identity map hands verify_chain the pre-UPDATE
    # object and the tamper is invisible for reasons that have nothing to do
    # with the chain. Re-read from the database.
    db.expire_all()
    ok, detail = audit_mod.verify_chain(db)
    print(f"\n  verify_chain after UPDATE: ok={ok} detail={detail}")
    assert ok is False, "detection failed as well as prevention"


# ===========================================================================
# AUD-004 — sync idempotency keys are global, not per clinic
# ===========================================================================


def test_defect_sync_operation_ids_are_scoped_to_a_clinic(
    client, db, clinic_factory, user_factory, auth_headers, patient_factory
):
    """P1 (AUD-005). One clinic can suppress another clinic's sync operation.

    `sync()` looks a receipt up by `operation_id` alone
    (backend/app/api/sync.py:149-151) with no clinic or device predicate, and
    `SyncReceipt.operation_id` is globally unique. A client chooses its own
    operation ids, so a device in clinic A that replays or guesses an id
    belonging to clinic B causes B's operation to return `duplicate` and be
    silently dropped — and the response hands back A's `server_entity_id`.
    """
    clinic_a = clinic_factory(name="Clinic A")
    clinic_b = clinic_factory(name="Clinic B")
    doctor_a = user_factory(clinic_a, email="a@sihhat.uz")
    doctor_b = user_factory(clinic_b, email="b@sihhat.uz")
    patient_b = patient_factory(clinic_b)

    shared_operation_id = f"op-{uuid.uuid4().hex[:12]}"

    first = client.post(
        "/api/v1/sync",
        headers=auth_headers("a@sihhat.uz"),
        json={
            "device_id": "device-a",
            "operations": [
                {
                    "operation_id": shared_operation_id,
                    "entity_type": "patient",
                    "op": "create",
                    "client_uuid": str(uuid.uuid4()),
                    "updated_at": "2026-08-21T00:00:00+00:00",
                    "data": {
                        "mrn": "A-0001",
                        "dob": "1990-01-01",
                        "sex": "male",
                        "pii": {"full_name": "Clinic A Patient"},
                    },
                }
            ],
        },
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/v1/sync",
        headers=auth_headers("b@sihhat.uz"),
        json={
            "device_id": "device-b",
            "operations": [
                {
                    "operation_id": shared_operation_id,
                    "entity_type": "consultation",
                    "op": "create",
                    "client_uuid": str(uuid.uuid4()),
                    "updated_at": "2026-08-21T00:00:00+00:00",
                    "data": {
                        "patient_server_id": str(patient_b.id),
                        "language": "uz",
                        "chief_complaint": "bosh og'rig'i",
                    },
                }
            ],
        },
    )
    assert second.status_code == 200, second.text
    result = second.json()["results"][0]
    print(f"\n  clinic B result: {result}")
    assert doctor_a.id and doctor_b.id  # keep the fixtures referenced

    assert result["status"] != "duplicate", (
        "clinic B's operation was dropped because clinic A had used the same "
        "operation_id; the idempotency key is not tenant-scoped"
    )


# ===========================================================================
# Probes that confirm claims the project makes (these pass)
# ===========================================================================


def test_probe_red_flags_survive_every_model_failure(knowledge, consultation, patient, db):
    """Spec claim: red flags are computed before the model and cannot be
    suppressed by it. Forced here through four distinct failure modes."""
    consultation.vitals = {"spo2": 88, "temperature_c": 39.0, "respiratory_rate": 34}
    db.flush()

    failures = {
        "provider outage": _Provider(raises=LlmUnavailable("provider down")),
        "schema-invalid response": _Provider(body="I am not JSON at all."),
        "empty response": _Provider(body=""),
        "half-valid JSON": _Provider(body='{"differentials": [}'),
    }
    for label, provider in failures.items():
        result = _engine(knowledge, provider).analyze(consultation, patient, clinic_tier=2)
        codes = [f.code for f in result.suggestion.red_flags]
        print(f"  {label:<26} degraded={result.degraded} red_flags={codes}")
        assert "hypoxia" in codes, f"hypoxia suppressed by: {label}"
        assert result.suggestion.referral.needed is True
        assert result.degraded is True, "a rules-only answer must be marked degraded"


def test_probe_open_circuit_breaker_still_fires_red_flags(knowledge, consultation, patient, db):
    """The breaker opening is the failure mode most likely in a real outage."""
    consultation.vitals = {"spo2": 85}
    db.flush()
    provider = _Provider(raises=LlmUnavailable("boom"))
    engine = _engine(knowledge, provider)
    for _ in range(6):
        engine.analyze(consultation, patient, clinic_tier=2)
    breakers = [b.state.value for b in engine.router.breakers.values()]
    result = engine.analyze(consultation, patient, clinic_tier=2)
    print(f"\n  breaker states: {breakers}")
    assert "hypoxia" in [f.code for f in result.suggestion.red_flags]


def test_probe_pediatric_dose_is_blocked_without_a_weight(knowledge, db, clinic_factory, user_factory):
    """Spec claim: no dose for a child under 12 without a recorded weight."""
    clinic = clinic_factory()
    child = Patient(
        clinic_id=clinic.id, mrn="P-CHILD1", dob=date.today().replace(year=date.today().year - 4),
        sex=Sex.male, pii_blob=b"",
    )
    child.set_pii({"full_name": "Test Child", "phone": "+998900000000"})
    db.add(child)
    db.flush()
    user = user_factory(clinic)
    c = Consultation(
        patient_id=child.id, user_id=user.id, clinic_id=clinic.id, language="uz",
        chief_complaint="isitma va yo'tal", structured_symptoms={},
        vitals={"temperature_c": 38.6},
    )
    db.add(c)
    db.flush()

    engine = _engine(knowledge, _Provider(body=_response_with_drug("amoxicillin")))
    result = engine.analyze(c, child, clinic_tier=2)
    treatment = result.suggestion.treatment
    print(f"\n  blocked_reason={treatment.blocked_reason} doses={[i.dose for i in treatment.items]}")
    assert treatment.blocked_reason == "pediatric_weight_required"
    assert all(i.dose is None for i in treatment.items)
