# SihhatAI — MVP Build Plan

> Working document for the engineering team. Derived from `docs/BUSINESS_PLAN.md`
> and the MVP build prompt pack. Updated at the end of every sprint alongside
> `PROGRESS.md`.

## 1. What we are building

A clinical decision support system (CDSS) for primary care clinics in Uzbekistan.
A doctor, feldsher or nurse enters a patient's symptoms in Uzbek (Latin) or Russian
— typed or spoken — and gets back:

- ranked probable conditions with confidence and an explicit "why",
- recommended tests,
- a treatment protocol restricted to the national formulary,
- a risk score,
- a referral recommendation.

Every output is a **suggestion to a licensed clinician**, never a diagnosis, and
every suggestion passes through an accept / edit / reject gate that is recorded.

## 2. Non-negotiables (these drive every design decision)

| # | Constraint | How it is enforced in code |
|---|------------|----------------------------|
| 1 | Not a diagnosis | `ClinicianDecision` row required before a suggestion is "closed"; disclaimer rendered by both clients; `/analyze` response always carries `disclaimer` + `requires_clinician_review: true` |
| 2 | Offline-first | Flutter Drift outbox + local red-flag rules + edge Ollama; server-side idempotent `/sync` with per-field last-write-wins and a merge log |
| 3 | Bilingual | `knowledge/terminology.csv` (uz colloquial → ru → en → ICD-10) consulted *before* any LLM call; message catalogs for uz/ru/en; eval reports a uz-vs-ru gap metric |
| 4 | Privacy | PII stored as an AES-GCM encrypted blob; `app/ai/deident.py` runs before every outbound call, with a 100-case red-team suite asserting zero leakage; identifiers re-attached locally only |
| 5 | Auditable | Hash-chained append-only `AuditLog`; every `AiSuggestion` stores input hash, model, prompt version, raw output, latency, cost, decision |
| 6 | Cost ceiling | Redis semantic cache keyed on the normalized symptom vector; cheap router sends simple/offline cases to local Llama; per-request budget enforced in `app/ai/router.py`; `cost_usd` logged per consultation |

## 3. Architecture

```
Flutter tablet (offline-first, Drift)
    │  outbox / sync
    ▼
Edge server (optional, per clinic): Ollama + slim API + ChromaDB
    │
    ▼
FastAPI backend  ──►  Postgres 16 + pgvector   (patients, consultations, audit, protocol chunks)
    │                 Redis                     (semantic cache, queues)
    ├── app/ai/engine.py    normalize → de-identify → retrieve → route → reason → ground → constrain → present
    ├── app/ai/red_flags.py deterministic, pre-LLM, never suppressible
    └── providers: OpenAI GPT-4o · Anthropic Claude · local Llama (vLLM/Ollama)
    ▲
Next.js admin dashboard (clinic metrics, acceptance rate, audit export)
```

### Key abstraction boundaries

- **`LlmProvider`** protocol — `OpenAIProvider`, `AnthropicProvider`, `LocalLlamaProvider`,
  and `ScriptedProvider` (cassette playback) all satisfy it. Tests never touch the network.
- **`EmbeddingProvider`** protocol — `OpenAIEmbeddings` in prod, `HashingEmbeddings`
  (deterministic, dependency-free) offline and in CI.
- **`VectorStore`** protocol — `PgVectorStore` in cloud, `InMemoryVectorStore` for CI
  and small edge deployments, ChromaDB adapter on the edge box.

This is what makes "runs offline" and "runs in CI without secrets" the same problem
solved once.

## 4. Domain model

`Clinic` → `User` → `Patient` → `Consultation` → `AiSuggestion` → `ClinicianDecision`,
with `AuditLog` hanging off everything as an append-only hash chain.
Row scoping is by `clinic_id` on every query path; cross-clinic reads are a tested
failure case, not a code review convention.

## 5. Milestones

| Sprint | Deliverable | Definition of done |
|--------|-------------|--------------------|
| 1 | Skeleton, auth, domain, audit chain, i18n | `docker compose up` serves the API; `pytest` green; cross-clinic access test passes |
| 2 | Knowledge base + RAG + terminology + formulary | An Uzbek query returns correctly cited protocol chunks |
| 3 | AI engine (8-stage pipeline), red flags, endpoints | Full pipeline runs live and against cassettes; cost logged |
| 4 | Flutter offline-first clinic app | Consultation completes with the network unplugged, syncs on reconnect |
| 5 | Evaluation harness (200 vignettes) | `make eval` reports ≥70% top-3, 100% red-flag recall |
| 6 | Admin dashboard, deploy, edge bundle, runbook | A clinic can be onboarded from the runbook alone |

## 6. File-by-file breakdown

### backend/
- `app/main.py` — app factory, middleware (request id, i18n, audit), router mounting
- `app/core/config.py` — pydantic-settings; every secret from env, no defaults in prod
- `app/core/security.py` — JWT access/refresh, password hashing, role dependencies
- `app/core/crypto.py` — AES-GCM envelope for the patient PII blob
- `app/core/audit.py` — hash-chained append-only writer
- `app/core/i18n.py` — uz/ru/en catalogs, `Accept-Language` resolution
- `app/models/*.py` — SQLAlchemy 2 models, one file per aggregate
- `app/schemas/*.py` — Pydantic v2 request/response models
- `app/api/{auth,patients,consultations,ai,admin,sync}.py` — routers
- `app/ai/engine.py` — the pipeline orchestrator
- `app/ai/deident.py` — PII stripping + `assert_no_pii`
- `app/ai/router.py` — model routing, budget, circuit breaker
- `app/ai/red_flags.py` — deterministic rule table
- `app/ai/prompts/` — versioned prompt template files
- `app/ai/rag/retriever.py` — hybrid vector + BM25 retrieval with filters
- `app/ai/eval/` — vignettes, metrics, runner, HTML report
- `tests/` — mirrors `app/`

### knowledge/
`ingest.py` (PDF/markdown → chunks → embeddings → store), `terminology.py` +
`terminology.csv`, `formulary.csv` + loader, `corpus/` sample protocols committed
so tests run without network.

### mobile/, web/, ml/, infra/
Flutter app (Riverpod + Drift), Next.js admin, XGBoost risk scorer, docker-compose /
Dockerfiles / terraform / GitHub Actions.

## 7. Open questions (need a human answer)

1. **Medical advisor sign-off.** The 200-vignette gold set is synthetic until a
   licensed Uzbek GP reviews it. Every vignette carries `reviewed_by` — currently
   `synthetic`. This blocks any clinical claim.
2. **Regulatory sandbox.** IT Park sandbox admission is required before real patient
   data touches this system. Until then the pilot runs on synthetic/consented data.
3. **Data residency.** "No PII leaves the country boundary" and "AWS ap-south-1
   (Mumbai)" are in tension. De-identification makes the LLM calls compliant, but the
   primary datastore should be domestically hosted for production. See `docs/adr/0002`.
4. **Formulary source of truth.** The committed `formulary.csv` is a starter list and
   needs replacing with the current MoH national formulary export.
5. **Whisper on Uzbek.** Word error rate on rural dialects is unmeasured; Sprint 4 ships
   voice as an assist with mandatory text review, not as trusted input.

## 8. How we work

- Tests alongside code. No sprint closes with a failing test.
- `PROGRESS.md` updated at the end of each sprint: shipped / stubbed / next.
- Deviations from spec get an ADR in `docs/adr/NNN-title.md`.
- Ask before: adding a paid service, changing the DB, or touching safety rules.
