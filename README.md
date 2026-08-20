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
| `docs/EVAL_INTEGRITY.md` | What the headline number means, measured rather than asserted |
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
   of 133 concepts and 811 recognised surfaces built from colloquial usage —
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

**Produced by the deterministic rules baseline, not by the diagnostic engine.**
The eight-stage engine has never been evaluated — see "What this repository has
not shown" below. Every vignette is synthetic and reviewed by no clinician.

| Metric | In-vocabulary set | Out-of-vocabulary set |
|---|---|---|
| Corpus | 249 synthetic vignettes (26 distinct templates) | 42 synthetic vignettes, all distinct |
| Provider | rules baseline — no model called | rules baseline — no model called |
| Top-3 agreement with our own answer key | 97.6% | **31.0%** |
| Top-1 agreement | 94.4% | 23.8% |
| **Red-flag recall** | 100.0% (158/158) | **4.5% (1/22)** |
| False-referral rate | 0.0% | 3.1% |
| Declined correctly when it should | — | 83.3% (10/12) |
| Risk scorer sensitivity | 100.0% | 20.0% |

> The two columns are the same code on the same day; only the wording differs.
> The left column is very largely a measure of whether text written by this
> project matches a dictionary written by this project — 58.9% of each
> in-vocabulary vignette's words are already terminology-map entries, and 8 of
> 11 presentation classes are identifiable by a single shared phrase. **The
> right column is the more honest estimate, and is itself optimistic.**
> Full working: [`docs/EVAL_INTEGRITY.md`](docs/EVAL_INTEGRITY.md).

Adversarial red-flag probing — dangers described in words the rules do not
contain — catches **31.6% (12/38)**. `158/158` is recall on text written in the
rules' own vocabulary.

Regenerate everything with `make eval-all`; the free CI gate is `make eval-gate`
and the key-gated model gate is `make eval-model`.

## What this repository has not shown

Stated plainly, because everything above is easy to over-read:

- **No clinician has reviewed any vignette.** All 339 across all four sets are
  synthetic and written by this project. "Accuracy" throughout means agreement
  with our own answer key.
- **No real patient case has ever been processed.** There is no pilot data.
- **The diagnostic engine is unmeasured.** Every number published here comes
  from the rules baseline. Nothing has called GPT-4o or Claude, so the
  $0.05-per-consultation ceiling and the 6-second p95 budget are **unmeasured,
  not met** — the reported `$0.0000` and `19 ms` are the cost and latency of
  calling no model at all.
- **Whether the LLM path beats the rules baseline is unknown.** It is a wired,
  one-command experiment (`make eval-model`) that is blocked only on an API key.
- **Red-flag detection is fragile to wording**, at 4.5% recall on unfamiliar
  phrasing. The app must not be described to a clinician as a safety net for
  missed danger signs. See `docs/SAFETY_REVIEW.md` S1.
- **The regulatory position is unestablished.** No IT Park sandbox admission,
  no clinical advisor engaged, no data-residency decision for production.
- **CI has never actually run.** The workflow file was invalid YAML from Sprint 1
  until this pass; every prior "CI passes" claim meant the steps had been run by
  hand.

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
make eval          # baseline path, main set
make eval-all      # every set side by side + the overlap measurement
make eval-model    # the real engine (needs an API key; refuses without one)
make web-check     # admin: lint, typecheck, build
make mobile-check  # Flutter: analyze + test
```

CI runs lint, types, backend tests at an 80% coverage gate, the
de-identification red-team suite as its own job, the migration round-trip, the
clinical evaluation gate, the web build, and Flutter analyze + test.
