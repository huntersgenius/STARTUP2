# SihhatAI — Progress

Updated at the end of every sprint. Format: shipped / stubbed / next.

## Sprint 1 — Skeleton, auth, domain, audit, i18n ✅

**Shipped**
- `infra/docker-compose.yml`: postgres 16 + pgvector, redis, backend, mailhog, all health-checked.
- FastAPI app with pydantic-settings, `.env.example`, `/health` (build SHA + DB/Redis status),
  `/health/live`, `/metrics` (dependency-free Prometheus text format).
- Full domain model + Alembic migrations, verified up and down. Patient identifiers are an
  AES-256-GCM blob bound to the row id; a database dump contains no names.
- JWT access/refresh with role dependencies. Cross-clinic reads return **404, not 403**, so the
  existence of another clinic's record is not leaked. Nine tests cover the isolation boundary.
- Append-only hash-chained `AuditLog`, plus a Postgres trigger that rejects UPDATE/DELETE, so
  tampering requires visibly dropping the trigger. Identifiers are refused in audit metadata at
  write time.
- Offline sync (`POST /sync`): idempotent by `operation_id`, per-field last-write-wins, and every
  discarded value recorded in `SyncMergeLog` — last-write-wins is only acceptable if the loser is
  recoverable. One bad operation cannot discard the rest of a batch.
- Admin surfaces: clinic onboarding, bulk users, per-clinic metrics (acceptance rate is the headline),
  audit chain verification, CSV audit export for the regulatory sandbox.
- i18n: uz/ru/en catalogs with a test asserting the clinical strings are actually translated,
  not copied from English. `uz-Cyrl` and `kaa` resolve to `uz`.
- CI: ruff, ruff-format, mypy, pytest with an 80% coverage gate, a separate un-skippable red-team job,
  and a migration up/down check.

**Numbers**: 70 tests green, 84% coverage on `app/`, mypy clean on 39 files.

**Stubbed**
- `app/api/ai.py` is an empty router until Sprint 3.
- `app/seed.py` has no test coverage (dev-only helper; refuses to run outside dev/test).
- The `web` and `mobile` CI jobs reference projects that arrive in Sprints 4 and 6.

**Next**: Sprint 2 — knowledge ingestion, terminology map, hybrid retrieval, formulary.

## Sprint 2 — Knowledge base, terminology, RAG, formulary ✅

**Shipped**
- `knowledge/ingest.py`: markdown/PDF → header-aware chunks → embeddings → store, with
  source, section, page, language and version on every chunk. Re-ingesting a source replaces
  it wholesale, so a protocol update leaves no stale chunks retrievable.
- Committed sample corpus of 10 protocols covering all 10 target conditions from
  `BUSINESS_PLAN.md` (WHO IMCI, hypertension, anaemia, low back pain, iodine, CVD/diet;
  UzMoH pneumonia, TB suspicion, type 2 diabetes, gastritis/H. pylori). Tests run offline.
- `knowledge/terminology.csv`: 129 concepts and **481 recognised surfaces** — the informal
  words patients and feldshers actually type, not textbook Uzbek. Uzbek Latin, Uzbek Cyrillic
  and Russian all resolve to the same concept and ICD-10 code.
- `app/ai/rag/retriever.py`: three-arm hybrid retrieval (concept + BM25 + vector) with
  weighted reciprocal rank fusion, age-band/sex/ICD-10 filters, and a citation on every hit.
  Reranking is stubbed behind a named interface rather than half-built.
- `knowledge/formulary.csv` + `FormularyService`: 49 items, availability tiers, pediatric and
  pregnancy contraindications, and therapeutic-group substitutes. An unavailable drug is
  flagged with an alternative for review, never silently swapped.

**Numbers**: **20/20** seeded queries (10 uz, 10 ru) retrieve the correct protocol.
144 tests green, 85% coverage, mypy clean.

**What this sprint actually taught us** — cross-lingual retrieval over a trilingual corpus
started at 5/20 and did not improve by tuning weights. Three vocabulary problems were doing
the damage, all now fixed in the terminology map and documented in `docs/adr/0003`:
Uzbek agglutination ("pnevmoniya**ni**"), British/American spelling ("anaemia" vs "anemia"),
and numeric findings ("qon bosimi 160/95" means hypertension, and no word map can see that).

**Stubbed**
- `Reranker` is the identity function until Sprint 5 measurements justify its cost.
- PDF ingestion works but needs `pypdf`, which is deliberately not a required dependency —
  the committed corpus is markdown so CI never needs it.
- The offline `HashingEmbeddings` is lexical, not semantic. Offline retrieval leans on the
  concept and BM25 arms; the eval report must label which embedder produced a run.

**Next**: Sprint 3 — the AI engine, de-identification red-team suite, red-flag rules.
