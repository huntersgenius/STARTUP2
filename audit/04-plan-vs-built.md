# Plan versus built

Workstream 6.

---

## 1. MVP feature set (`docs/BUSINESS_PLAN.md` §3.3)

**Must-have, month 3-4:**

| # | Promised | State | Evidence |
|---|---|---|---|
| 1 | Symptom input, structured form + free text, uz/ru | **implemented** | `mobile/lib/features/consultation/consultation_screen.dart`, chips + free text, both languages |
| 2 | Top-3 conditions with confidence scores | **implemented, deliberately altered** | ranked list present; the *percentage* was replaced with a three-level match band after the calibration work. Correct call, and a departure from the plan |
| 3 | Treatment protocols from WHO guidelines | **implemented** | `knowledge/corpus/`, RAG citations enforced by `ground()` — an uncited differential is dropped |
| 4 | Patient record creation and storage | **implemented** | `app/api/patients.py`, AES-256-GCM `pii_blob`, offline Drift store |
| 5 | Basic analytics dashboard | **implemented** | `web/`, builds clean; `/`, `/clinics`, `/audit` |

**Nice-to-have, month 5-6:**

| # | Promised | State | Evidence |
|---|---|---|---|
| 6 | Medical image upload and analysis | **absent** | no image path anywhere |
| 7 | Voice input (Whisper) | **absent** | `record: ^5.1.2` in `pubspec.yaml` under `# Voice`; no Dart file imports it, no transcription code in `backend/`. AUD-010 |
| 8 | Offline mode with sync | **implemented, and the strongest part** | Drift local store, `app/api/sync.py`, on-device rule engine, `airplane mode end to end` widget test |
| 9 | SMS interface for feature phones | **absent** | — |
| 10 | Pharmacy inventory integration | **partial** | formulary availability by clinic tier is modelled; no live inventory link |

Honest count: **5 of 5 must-haves, 1.5 of 5 nice-to-haves.** The descoped items
are genuinely absent rather than half-present, with one exception — the unused
`record` dependency, which should be deleted until the feature exists.

---

## 2. Stack (`docs/BUSINESS_PLAN.md` §3.3, "Tech Stack Decisions")

| Layer | Planned | Built |
|---|---|---|
| Mobile | Flutter | Flutter ✅ |
| Web | React + Next.js | Next.js ✅ |
| Backend | FastAPI | FastAPI ✅ |
| Database | PostgreSQL + Redis | PostgreSQL + Redis ✅ |
| Inference | GPT-4o + self-hosted Llama 3 | both wired, **neither ever called** |
| Vector search | **Pinecone (cloud) / ChromaDB (edge)** | neither — in-repo store + pgvector. A better decision than the plan's, and it removes a foreign data processor |
| Speech | OpenAI Whisper API | absent |
| Hosting | **AWS ap-south-1 (Mumbai)** | undecided; `README.md` says "no data-residency decision for production" |
| CI/CD | GitHub Actions | present; **first executed this month** |
| Monitoring | Sentry + Datadog | Sentry DSN config only |

Two of these are decisions, not gaps, and both deserve to be written down as
decisions: dropping Pinecone removes a cross-border processor, and the Mumbai
hosting line in the plan is now in tension with the personal-data law
(`audit/05-regulatory.md`).

---

## 3. Traction gates (`docs/EXECUTIVE_SUMMARY.md`, "Traction Plan")

The summary presents these as a **plan**, in future tense, under a heading that
says so. It does not claim any of them has happened. That is worth stating
plainly because it is the cheapest possible thing to be caught on and this
document is not doing it.

| Gate | Status |
|---|---|
| 20+ doctor interviews | **not started.** Nothing in the repository implies otherwise |
| 3 Letters of Intent | **not started** |
| IT Park membership | **not started**; `docs/PILOT_RUNBOOK.md` §0 lists sandbox application as a blocker |
| MVP built and tested with pilot doctors | built; **not tested with any doctor.** `README.md`: "No clinician has reviewed any vignette" |
| 70%+ diagnostic accuracy on top-10 conditions | **not met, and not measured on anything resembling real cases** |
| 3-5 paying pilot clinics, 500+ consultations, $750 MRR | **not started.** "No real patient case has ever been processed" |

The one that needs care is the accuracy gate. The repository's CI gate is
`--fail-under-top3 0.70` — numerically identical to the business gate — and it
passes at 97.6%. Those are not the same measurement and nothing in the repo
suggests they are, but an investor reading a green CI badge next to a 70%
business target will conflate them. Rename the CI gate, or state its floor as
"agreement with our own answer key" in the job name.

### Claims in `EXECUTIVE_SUMMARY.md` that do not survive a check

| Line | Claim | Verdict |
|---|---|---|
| 33 | "First mover … with zero direct competitors" | **contradicted.** AUD-009 |
| 81 | "No competitor has built healthcare AI for this 38.2 million-person market" | **contradicted.** The Cabinet of Ministers' 10 July 2025 roadmap includes an AI digital medical assistant integrated into DMED, piloting in two Tashkent districts, plus clinical decision support tools, by end-2026 |
| 35 | "Regulatory Sandbox (2025)" as an existing advantage | **unverified.** An EY–IT Park agreement to establish a sandbox exists, and healthcare is named a priority area in the AI sandbox framework. I found no published admission criteria or health-AI cohort. Treat as a route to apply for, not an advantage held |
| 9 | "892 diet-related deaths per 100,000 (Lancet 2019)", "27.4 doctors per 10,000", "2,834 rural clinics" | **not checked.** Out of scope for a code audit; flagged because all three carry a decimal point that invites belief |
| 73 | "Series A of $5-10M at $30-50M valuation within 24-30 months" | a projection, labelled as one |

---

## 4. Unit economics, recomputed from the implementation

The plan assumes $5,500/month payroll and $900-1,900/month infrastructure. The
per-consultation cost is the number that has changed now that code exists — and
it is still **unknown**, because no model has ever been called. What the code
does let us bound:

**Token volume per consultation.** The prompt assembles a system prompt, the
case block, up to 6 retrieved protocol excerpts, and the full tier-filtered
formulary list rendered one drug per line. With 49 formulary rows and 6
excerpts, the user message is on the order of 3-5k tokens before the patient's
own text. At `gpt-4o` list pricing that is roughly $0.01-0.02 per call for
input alone, plus up to two schema-retry calls (`MAX_SCHEMA_RETRIES = 2`), each
of which resends the whole prompt with an error suffix.

**So the $0.05 ceiling is not comfortable — it is the worst case of a single
consultation that retries twice.** `Budget.can_afford` enforces the ceiling per
request, so the failure mode is not a surprise bill; it is silent degradation to
rules-only on exactly the hard cases that triggered the retries.

Two implementation choices that were not in the plan and change the economics
materially, both in the right direction:

- **The semantic cache** (`cosine ≥ 0.97`, 7-day TTL, bucketed by age band, sex,
  pregnancy, language, red-flag set and prompt version). In a clinic where
  presentations repeat, this is the difference between the plan's numbers and
  something better. It is also currently the vehicle for AUD-001.
- **The router degrades to local Llama** before it exceeds budget or latency,
  so cost is capped by construction rather than by discipline.

Costs the plan does not carry at all:

| Item | Plan | Reality |
|---|---|---|
| Embeddings | not costed | one call per consultation, plus corpus re-ingest |
| Edge hardware | not costed | one mini-PC per offline clinic — a per-clinic capex line against a $200-500/month subscription |
| Whisper | costed | feature absent, so $0 today; when built, it is also a biometric-data problem |

**Recommendation.** Do not put a per-consultation figure in any deck until
`make eval-model` has run once. It is one command and one key. Until then the
correct number in the financial model is a range with a footnote, and the
correct answer to an investor asking is "we have not measured it, here is the
command that will".
