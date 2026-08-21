# Next 90 days

Ordered. Each item names the decision it unblocks, because anything that does
not unblock a decision can wait.

Owner types: **ENG** backend/mobile engineer · **CLIN** licensed Uzbek
physician (not yet engaged) · **FOUND** founder · **LEGAL** regulatory counsel.

---

## Week 1 — stop the bleeding

| # | Do | Owner | Effort | Unblocks |
|---|---|---|---|---|
| 1 | Fix AUD-001: use `scrubbed["chief_complaint"]` for the cache vector, and move `assert_no_pii` to a wrapper around every provider's outbound call. `backend/tests/test_audit_p0.py` goes green. | ENG | 0.5 d | Any deployment with an API key. Until this ships, do not set `OPENAI_API_KEY` in any environment holding real data. |
| 2 | Fix AUD-005: make the sync receipt lookup and uniqueness `(clinic_id, operation_id)`. | ENG | 1 h + migration | A second pilot clinic. |
| 3 | Fix AUD-002 both ways: populate `controlled` in `knowledge/formulary.csv`, **and** make an unknown drug fail closed. | ENG + CLIN | 1 d | Any claim to a regulator that controlled substances are never emitted. |
| 4 | Delete the unused `record` dependency. | ENG | 10 min | Honest dependency surface. |
| 5 | Fix AUD-008 — the documented `ml.evaluate_risk` command — and add a `make` target. | ENG | 10 min | `docs/PILOT_RUNBOOK.md` reproducing. |

## Weeks 2-3 — measure the thing you are selling

| # | Do | Owner | Effort | Unblocks |
|---|---|---|---|---|
| 6 | **Buy one API key and run `make eval-model`.** Report top-3, red-flag recall, p95 latency and mean cost against the $0.05 / 6 s budgets, on main **and** on both out-of-vocabulary sets. | ENG | 1 d, < $100 | Every financial and product claim that currently reads "unmeasured". This is the highest-information hour in the whole plan. |
| 7 | Run the injection set on the model path. | ENG | 2 h | The only injection number that means anything. |
| 8 | Publish the delta: does GPT-4o beat a rules table that never sees the free text? | ENG + FOUND | 0.5 d | The decision in §"the fork" below. |

## Weeks 2-6 — the safety layer that reads words

| # | Do | Owner | Effort | Unblocks |
|---|---|---|---|---|
| 9 | Negation scope in the matcher (`yo'q`, `emas`, `bo'lmadi`, `нет`, `не`), with tests in both languages written by a native speaker. | ENG | 2-3 d | The 25% decoy false-positive rate. A clinic that gets referred for "no dehydration" stops using the product. |
| 10 | Give the safety layer a reader of free text: either a separate cheap model call that may only **add** flags, or a mandatory danger-sign checklist feeding `concepts`. Choose with the clinical advisor. | ENG + CLIN | 1-2 w | The 0-of-10 text-only recall. Nothing else moves it. |
| 11 | Instrument **red-flag firing rate per 100 consultations**, per clinic, and alert on a drop. | ENG | 1 d | The only field signal that would reveal AUD-003 in production. |
| 12 | Add rejection-rate and degraded-share alerts, not just counters. | ENG | 1 d | Knowing quality has slipped before a clinician tells you. |

## Weeks 4-8 — make the evidence admissible

| # | Do | Owner | Effort | Unblocks |
|---|---|---|---|---|
| 13 | **Engage the clinical advisor.** First task: review and rebuild the vignette set — 26 templates become ~150 genuinely distinct cases, written by a clinician, with no phrase shared across a class. | FOUND + CLIN | 3-4 w | Every clinical number. Until this happens "accuracy" means agreement with our own answer key, and a reviewer will say so. |
| 14 | Run the audit tests against a Postgres service container (AUD-006). | ENG | 0.5 d | Knowing the append-only trigger is actually there. |
| 15 | Make the clinic audit export verifiable — per-clinic chain, or an inclusion proof (AUD-007). | ENG | 1-2 d | The sandbox application's central artefact. |
| 16 | Key rotation: key-id prefix on the ciphertext, plus a restore test that decrypts a real name from a backup. | ENG | 2 d | A second clinic, and any honest answer to "what happens if you lose the key". |
| 17 | Put the SaMD classification question to regulatory counsel in writing. | FOUND + LEGAL | 2 w elapsed | The timeline. A 6-12 month device registration sitting between pilot and revenue is a fundraising fact. |
| 18 | Decide hosting, in writing, against ZRU-547 as amended 27 March 2026. Default to Uzbekistan. | FOUND + LEGAL | 1 w | AUD-001's legal half, and the plan's Mumbai line. |

## Weeks 6-12 — the experiment that decides the company

| # | Do | Owner | Effort | Unblocks |
|---|---|---|---|---|
| 19 | **The retrospective chart study.** See below. | FOUND + CLIN | 6-8 w | Whether any of this works. |
| 20 | Rewrite the competitor claim in `EXECUTIVE_SUMMARY.md` (AUD-009). | FOUND | 1 h | Not being caught by the first diligence call. |
| 21 | Rename the CI accuracy gate so it cannot be read as the business gate. | ENG | 30 min | The same. |

---

## The single highest-information experiment

**Not more building. A retrospective chart study.**

**Design.** 300 consecutive completed consultations, pulled from the paper or
DMED records of **3 clinics** — one urban polyclinic, one rural QVP, one
feldsher point — covering all four seasons if the records allow, or at minimum
one full winter month and one summer month. Take them consecutively, not
sampled: a sampled set will quietly exclude the messy ones.

**Labelling.** Two independent Uzbek physicians assign the final diagnosis from
the record, blind to the system's output and to each other. Disagreements go to
a third. **The labellers must not be the people who wrote the vignettes**, and
none may be a founder. Report inter-rater agreement — if two doctors cannot
agree on the answer, no accuracy figure means anything.

**Measure, in this order of importance:**

1. **Red-flag recall on the cases that turned out to be emergencies.** This is
   the number the company lives or dies by. On synthetic rule-shaped text it is
   100%; on the audit's independently written text it is 32.7%, and 0% where the
   danger is only in words. The true field number is somewhere in that range and
   nobody knows where.
2. **False-referral rate**, priced in patient days of travel.
3. Top-3 agreement with the physician label — the accuracy number, and the least
   important of the three.
4. **Time per consultation**, measured with a stopwatch in the room.

**Cost.** Roughly two physician-months plus the API spend. Call it $8-12k. It is
4% of the raise and it is the only thing that converts this repository from an
engineering artefact into evidence.

**Why this and not more building.** Every remaining product question is
downstream of one unknown: does the danger-sign layer work on real Uzbek
clinical speech? Every number in the repository that says yes was produced by
text this project wrote. Building more features on top of an unmeasured safety
layer increases the amount of work that has to be redone when the answer
arrives.

---

## The fork, stated plainly

Item 6 (one API key, one command) and item 19 (the chart study) between them
produce two facts that determine the shape of the company:

- **If the LLM beats the rules baseline by a wide margin on out-of-vocabulary
  text**, the product is an LLM product, the $0.05 budget is the binding
  constraint, and the roadmap is cost engineering and caching.
- **If it does not**, the LLM is not earning its cost, latency or regulatory
  exposure, and the honest product is a very good structured intake and
  formulary-checking tool with a deterministic alarm layer — which is smaller,
  cheaper, easier to register, and might be the better business in a market
  where connectivity is the binding constraint.

Both are viable. Neither is knowable today. The cost of finding out is one key
and one command, and it has been one key and one command for weeks.

## Stop doing

- **Stop quoting 97.6%.** It is agreement between text this project wrote and a
  dictionary this project wrote, over 26 templates. `README.md` already says so;
  say it out loud in every room too.
- **Stop reporting per-class 100.0% figures.** Eight of eleven are separable by
  a single shared phrase.
- **Stop adding terminology surfaces to raise the out-of-vocabulary score.** The
  remediation added a test that fails if anyone does. Keep it.
- **Stop building nice-to-have features** (images, SMS, voice) until item 19
  reports.
