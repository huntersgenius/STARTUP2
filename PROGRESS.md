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

## Sprint 3 — The AI engine ✅

**Shipped**
- `app/ai/engine.py`: the eight-stage pipeline exactly as specified —
  normalize → de-identify → retrieve → route → reason → ground → constrain → present.
- `app/ai/deident.py` + a **100-case red-team fixture set** of realistic Uzbek and Russian
  clinical text. Two layers, and the distinction is the point:
  **layer 1** redacts the patient's own identifiers (from the decrypted PII blob) by exact
  match with Uzbek suffix tolerance — this is the guarantee, and it is 100% on all 100 cases;
  **layer 2** is a pattern and gazetteer net for people whose values we do not hold, which the
  suite *measures* (currently 100%, floor held at 95%) rather than assuming.
- `app/ai/red_flags.py`: 17 deterministic rules — ACS, sepsis (qSOFA-style), stroke FAST,
  meningism, IMCI danger signs, paediatric dehydration, pregnancy bleeding, pre-eclampsia,
  GI bleeding, haemoptysis, the TB triad, glucose and hypertensive emergencies, severe anaemia.
  A test asserts `red_flags.py` imports nothing model-related, so the safety layer cannot
  come to depend on a provider being reachable.
- `app/ai/prompts/v1/`: prompts as versioned files. `prompt_version` is `v1@<content-hash>`,
  so an edited template cannot masquerade as the version it replaced.
- `app/ai/schema.py`: strict structured output, 2 retries on invalid JSON, then graceful
  degradation to a rules-only response.
- `app/ai/router.py`: cost/latency budget per request, circuit breaker per provider, and
  routing that sends simple and offline cases to the local model.
- `app/ai/cache.py`: Redis semantic cache keyed on the symptom vector **plus clinical
  context** — a child can never be served an adult's cached answer, and degraded responses
  are never cached.
- `POST /consultations/{id}/analyze` and `POST /suggestions/{id}/decision`, both fully audited.

**Numbers**: 383 tests green, 87% coverage, mypy clean on 54 files.

**Bug found and fixed while testing**: `Patient.set_pii` bound the ciphertext to `self.id`,
which is `None` until INSERT — so PII encrypted on a freshly constructed object could never be
decrypted. `set_pii` now assigns the id first. This would have silently corrupted every patient
created through a path that did not pre-assign an id.

**Design note**: ICD-10 candidates are no longer passed as a retrieval *filter*. They are
derived from symptoms (R05 cough) while protocols are labelled with conditions (J18.9
pneumonia); requiring an intersection returned nothing at all. They still reach the model as
prompt context, where they help.

**Stubbed**
- The second-opinion (Claude) pass is wired through the router but is not yet invoked
  automatically after a low-confidence first pass — that lands with the eval harness in
  Sprint 5, where its value can actually be measured.
- Cassettes are recorded per prompt hash; no live-API recordings are committed yet.

**Next**: Sprint 4 — the Flutter offline-first clinic app.

## Sprint 4 — Flutter clinic app (offline-first) ✅

**Shipped** — and genuinely verified: Flutter 3.24.5 was installed in this environment, so
`flutter analyze` is clean and all **51 tests pass**, rather than the code merely being written.

- Drift (SQLite) local store as the record of truth while offline. Two schema-level invariants:
  nothing is deleted on sync (rows are marked), and **every mutation writes its outbox row in the
  same transaction** as the data it describes, so there is no window where a consultation exists
  with nothing scheduled to send it.
- `SyncEngine`: idempotent per `operation_id`, exponential backoff, and an outbox row that is
  deleted only after the server confirms it. A rejected operation is kept and surfaced, never
  dropped — losing a patient record because the server disliked it is not an option.
- **On-device red flags** (`local_red_flags.dart`): 12 rules mirroring the server's table, so a
  feldsher with no signal still gets the immediate-referral banner. A test asserts every device
  code exists in the server's rule table, so the two cannot drift apart silently.
- `OfflineEngine` deliberately produces **no differentials** offline. Without retrieval, a
  citation or a formulary check, a ranked list would be a guess dressed up as advice; what it
  does produce is the red flags, a complete captured case, and honest follow-up questions.
- UI built for the actual user: 64dp touch targets, 18sp body text, high contrast, symptom chips
  plus free text plus mic, uz/ru toggle on every screen.
- `SyncIndicator` states three things a non-technical user can act on: how many records are
  waiting, when it last worked, and a retry button.
- Safety surfaces are enforced by test: red flags render **above** any differential, the
  disclaimer is present and non-dismissible, a blocked paediatric dose is shown rather than
  hidden, and the accept/edit/reject gate must be closed before a consultation completes.
- **Airplane-mode end-to-end test**: a full consultation is entered, assessed and decided with
  the network down, and the record is verified on disk and in the outbox afterwards.

**Two real bugs found by these tests**
1. *Sync ordering.* A patient and their first consultation are created seconds apart offline and
   became due in the same batch — but the consultation's payload still carried the patient's
   **local** id, which the server had never seen, so it would have been rejected as an orphan.
   The engine now sends parents before children and rewrites the references in between.
2. *Touch targets.* `VisualDensity.comfortable` silently subtracted 4dp from every button,
   rendering the promised 64dp target at 60dp. The theme now uses standard density.

**Stubbed**
- Voice input is wired through an injected recorder so tests can drive it; the Whisper upload
  path itself queues audio but is not yet transcribing.
- The patient handout (`printing`/`pdf`) is a dependency, not yet a screen.
- The edge-server (Ollama) client is a URL swap in `providers.dart`, not a separate transport.

**Next**: Sprint 5 — the evaluation harness.

## Sprint 5 — Evaluation harness ✅

**Shipped**
- **249 gold-standard vignettes** across the 10 target presentations plus an emergency set.
  Each carries Uzbek *and* Russian text, age, sex, vitals, ground-truth ICD-10, clinically
  acceptable alternatives, red flags that **must** fire, and red flags that must **not** —
  because a system that refers everyone would otherwise score perfect recall.
- `app/ai/eval/metrics.py`: top-1/top-3 (strict and lenient), red-flag recall, false-referral
  rate, expected calibration error, p50/p95 latency, cost per case, and the uz-vs-ru gap.
- `make eval` prints the table and writes `results/<date>.json`; `make eval-gate` applies the
  CI floors; `make eval-ab` compares two arms.
- `eval/report.html` — a report for a medical advisor, an investor or a sandbox reviewer,
  with the provenance banner above the numbers and a test asserting it stays there.
- A/B harness that flags **safety regressions specifically**: a top-3 improvement that costs a
  caught red flag exits non-zero, because that is a regression, not a win.
- `RetrievalBaselineProvider`: a deterministic offline reasoner so the gate runs on every PR
  with no keys and no network. It is labelled in every report — a baseline number must never
  be read as a GPT-4o number — and it doubles as the quality floor for a clinic whose models
  are all unreachable.

**Results (offline rules baseline, 498 runs across both languages)**

| Metric | Result | Floor |
|---|---|---|
| Top-3 accuracy | **97.6%** | 70% |
| Top-1 accuracy | 94.4% | — |
| **Red-flag recall** | **100%** (158/158) | **100%** |
| False-referral rate | 10.8% | — |
| Calibration error (ECE) | 0.279 | — |
| p95 latency | 25 ms | 6000 ms |
| Cost per case | $0.0000 | $0.05 |
| Language gap (uz − ru) | 0.0 pp | — |

**What the eval caught — this is why the sprint exists.** The first full run reported
**62% red-flag recall: 60 missed red flags.** Every one was a real defect, none of which any
unit test had caught:

1. *Vocabulary, first person vs third.* The map had "kechasi terlayman" (*I* sweat at night)
   but not "kechasi terlaydi" (*the patient* sweats) — which is how a clinician writes it. TB
   suspicion was missed 24 times in Uzbek while working in Russian.
2. *Vocabulary, singular vs plural.* "ko'zi ichiga botgan" was mapped, "ko'zlari ichiga botgan"
   was not, so childhood dehydration went undetected.
3. *A silent false positive.* "kecha" (yesterday) was matching inside "kechasi" (at night),
   producing a wrong duration and suppressing the TB rule. Adding the longer surface fixed
   both the miss and the false positive.
4. *A rule bug.* Longest-match retrieval yields `pediatric_diarrhea`, never plain `diarrhea`,
   so the childhood-dehydration rule failed in Uzbek and passed in Russian. Red-flag rules now
   apply a `CONCEPT_IMPLIES` table, so a specialised concept satisfies a rule written against
   the general one.

155 synonyms and 3 concepts were added; the terminology map is now 132 concepts and **803
recognised surfaces**. Recall went 62% → 96.2% → **100%**.

**Honest limits**
- **Every vignette is synthetic and unreviewed by a clinician.** These numbers describe
  engineering behaviour, not clinical accuracy, and the report says so above the fold. Advisor
  review is open question #1 in `docs/PLAN.md` and blocks any clinical claim.
- 97.6% on a set the same team wrote is a measure of internal consistency. The number that
  matters comes from advisor-reviewed vignettes and, later, real consultations.
- The baseline is a rules engine, not an LLM. Its ECE (0.28) is poor because a rules table
  cannot really estimate confidence; that is a known gap the LLM arms should beat.

**Next**: Sprint 6 — admin dashboard, deployment, edge bundle, pilot runbook.

## Sprint 6 — Admin dashboard, deployment, edge bundle, pilot readiness ✅

**Shipped**
- **Next.js admin dashboard** (uz/ru, dark-mode aware), verified: `npm run lint`,
  `typecheck` and `build` all clean. Leads with **AI acceptance rate** — the key product
  metric — and puts **undecided suggestions** next to it, because an open clinician gate is
  the one number that must never be quietly ignored. Per-clinic table adds edit/reject rates,
  red flags fired, mean latency, degraded share, sync conflicts and cost.
- Audit page: chain verification and the CSV export that goes to the regulatory sandbox
  reviewer, with the guarantee stated in the clinician's language on the page itself.
- The browser never sees the API address or a token: requests go through a same-origin
  Next.js rewrite.
- **Edge bundle** (`infra/edge/`): docker-compose running Postgres+pgvector, Redis, Ollama and
  the API on a clinic mini-PC. It deliberately holds **no cloud API keys** — a stolen box
  cannot spend the API budget. `INSTALL.md` is a one-page procedure written for a non-engineer,
  including what to do when it goes wrong.
- **Terraform** for staging and prod with encrypted RDS, Secrets-Manager-managed credentials,
  encrypted ElastiCache, immutable ECR tags, and a 30-day backup window in prod. The region is
  a variable with a comment pointing at ADR 0002, so nobody settles data residency by editing
  a default.
- **Backups that are actually verified**: `infra/ops/backup.sh` restores every dump into a
  scratch database and counts rows — including the audit chain — before declaring success. A
  backup nobody has restored is a hope, not a backup. `restore.sh` requires typed confirmation
  and prints what it will overwrite.
- **Ops**: Sentry wired with a `before_send` hook that strips identifiers by key *and* by
  pattern, request bodies never sent, and five Prometheus alerts that each name what a human
  should do. One of them, `NoDecisionsRecorded`, treats a silent clinician gate as a
  compliance incident rather than a bug.
- **`docs/PILOT_RUNBOOK.md`**: blockers before travel, install, a 45-minute training script,
  first-week checks, the weekly metrics review, rollback (always available, never a failure),
  exit criteria, and the printable one-page staff guide in Uzbek.

**Two judgements worth recording**
- The runbook says a **90%+ acceptance rate is a negative result** until proven otherwise.
  Rubber-stamping is the most likely way this product fails safely-looking.
- Rollback is documented as ordinary and blameless. A clinician who feels they cannot stop
  using a tool will work around it instead, which is worse for the patient and worse for us.

**Numbers**: backend 393 tests green, 87% coverage, mypy clean on 62 files; Flutter analyze
clean with 51 tests; web lint, typecheck and build clean.

**Stubbed / next**
- ECS services and load balancer are not in terraform yet — the modules define data, network
  and registry; compute is the next slice.
- The dashboard reads live metrics but has no charts over time yet; the API returns a single
  window, not a series.
- Whisper transcription still queues audio without transcribing it.

## Post-sprint — adversarial safety review ✅

Ran the review prompt from the build pack against the whole system, as a hostile senior
engineer and a medical safety reviewer. **Five defects found, all fixed, each with a
regression test that names the defect.** Full write-up: [`docs/SAFETY_REVIEW.md`](docs/SAFETY_REVIEW.md).

The two that mattered:

1. **A clinician's decision made offline was silently discarded.** The UI said "done", nothing
   was written to the device, and the consultation reached the server with no evidence a human
   had ever reviewed the output — breaking the offline-first guarantee and the
   clinician-in-the-loop guarantee simultaneously, in exactly the setting this product exists
   for. The device now persists the offline suggestion and queues it with the decision and the
   red flags the clinician actually saw; the server records all three plus an audit row.

2. **`chronic_flags` reached the prompt unscrubbed.** Every other field came from the
   de-identified payload; this one came straight from the patient row. Chronic flags are free
   text a clinician types, so a name written there would have gone to a third-party model. The
   red-team suite missed it because it tests the scrubber in isolation rather than what the
   prompt builder assembles — the new test asserts on the prompt string itself.

Also fixed: the clinical gate could be bypassed by syncing (a nurse is refused online but was
accepted offline — a rule that depends on connectivity is not a rule), and the raw model
output was being copied into the audit metadata exported to the regulator as CSV.

Checked and found sound: red-flag rules import nothing model-related and still fire with every
provider down; no test asserts something trivially true (the five assertion-free red-team tests
call a helper that raises, and that helper has its own mutation test).

**Final state**: backend 414 tests at 88% coverage with mypy clean; Flutter analyze clean with
51 tests; web lint, typecheck and build clean; eval gate green at 97.6% top-3 and 100%
red-flag recall.
