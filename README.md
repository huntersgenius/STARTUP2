# SihhatAI

AI clinical decision support for primary care clinics in Uzbekistan.

A doctor, feldsher or nurse types or speaks a patient's symptoms in Uzbek or
Russian; the system returns ranked probable conditions with confidence and an
explicit "why", recommended tests, a treatment protocol limited to locally
available medicines, a risk score, and a referral recommendation.

**Every output is a suggestion for a licensed clinician. It is never a
diagnosis, and it always passes through an accept / edit / reject gate that is
recorded.**

Business context: [`docs/BUSINESS_PLAN.md`](docs/BUSINESS_PLAN.md) ·
[`docs/EXECUTIVE_SUMMARY.md`](docs/EXECUTIVE_SUMMARY.md) ·
engineering plan: [`docs/PLAN.md`](docs/PLAN.md) ·
status: [`PROGRESS.md`](PROGRESS.md)

---

## Quick start

```bash
cp .env.example backend/.env      # then edit the keys
make up                           # postgres+pgvector, redis, backend, web, mailhog
make seed                         # a demo clinic and one user per role (dev only)
open http://localhost:8000/docs   # API
open http://localhost:3000        # admin dashboard
```

Without Docker:

```bash
make test        # backend suite
make eval        # the clinical evaluation suite + HTML report
make lint typecheck
```

---

## What is here

| Path | What it is |
|---|---|
| `backend/` | FastAPI service: domain, auth, audit chain, offline sync, the AI engine |
| `backend/app/ai/` | The pipeline: normalize → de-identify → retrieve → route → reason → ground → constrain → present |
| `backend/app/ai/eval/` | 249-vignette evaluation harness, metrics, A/B, HTML report |
| `knowledge/` | Protocol corpus, ingestion, terminology map (uz/ru/en → ICD-10), national formulary |
| `ml/` | Deterministic risk scoring; the XGBoost baseline to beat once pilot data exists |
| `mobile/` | Flutter tablet app, offline-first (Drift + outbox sync) |
| `web/` | Next.js admin dashboard |
| `infra/` | docker-compose, Dockerfiles, terraform, edge bundle, ops scripts and alerts |
| `docs/` | Plan, ADRs, pilot runbook |

---

## The six constraints that shape every design decision

1. **Not a diagnosis.** The clinician gate is enforced server-side, and a
   suggestion with no recorded decision is reported as `undecided` on the
   dashboard so it cannot be quietly ignored.
2. **Offline-first.** The tablet is the record of truth while disconnected.
   Every mutation writes its outbox row in the same transaction as the data,
   sync is idempotent, and a rejected operation is kept rather than dropped.
3. **Bilingual.** Uzbek (Latin and Cyrillic) and Russian, via a terminology map
   of 132 concepts and 803 recognised surfaces built from colloquial usage —
   not textbook Uzbek, and not raw LLM translation.
4. **Privacy.** Identifiers live in an AES-256-GCM blob bound to the patient
   row. De-identification runs before every outbound call, with a 100-case
   red-team suite that may never be skipped.
5. **Auditable.** Append-only hash-chained audit log, enforced by a database
   trigger, exportable as CSV for the regulatory sandbox.
6. **Cost ceiling.** Under $0.05 per consultation: semantic caching keyed on
   clinical context, and routing that keeps simple and offline cases local.

---

## Current evaluation results

Offline rules baseline, 249 vignettes × 2 languages:

| Metric | Result | Floor |
|---|---|---|
| Top-3 accuracy | 97.6% | 70% |
| **Red-flag recall** | **100%** (158/158) | **100%** |
| False-referral rate | 10.8% | — |
| p95 latency | 25 ms | 6000 ms |
| Cost per consultation | $0.00 | $0.05 |

> **Every vignette is synthetic and has not been reviewed by a licensed
> clinician.** These numbers describe engineering behaviour, not clinical
> accuracy. Advisor review is the first open question in `docs/PLAN.md` and it
> blocks any clinical claim.

Regenerate with `make eval`; the CI gate is `make eval-gate`.

---

## Before this touches a real patient

Four things, none of them engineering:

1. A licensed Uzbek clinician engaged as advisor, and the vignette set reviewed.
2. IT Park **Regulatory Sandbox** admission.
3. A data residency decision for production (`docs/adr/0002`).
4. The national formulary replaced with the current MoH export.

`docs/PILOT_RUNBOOK.md` treats the first two as hard blockers.

---

## Development

```bash
make help          # every target
make migrate       # apply migrations
make ingest        # rebuild the knowledge base from knowledge/corpus
make test          # backend tests
make coverage      # with the 80% gate
make eval          # clinical evaluation + report
make web-check     # admin: lint, typecheck, build
make mobile-check  # Flutter: analyze + test
```

CI runs lint, types, backend tests at an 80% coverage gate, the
de-identification red-team suite as its own job, the migration round-trip, the
clinical evaluation gate, the web build, and Flutter analyze + test.
