# Post-execution audit — summary

SihhatAI, branch `claude/github-startup-repo-3qm5c6`, commit `208e460`,
audited 2026-08-21. Everything below was reproduced by running the code.

**Verdict.** The system is real, it builds, and its deterministic safety layer
survives every model failure I could force. The reporting is now honest — I
reproduced all eleven published evaluation figures to the digit and found no
table that presents a baseline number as an engine number. What the remediation
pass did not find are **one P0 and five P1s**, and one of them is the sentence
this whole product turns on: *the safety layer never reads the patient's words.*

**1 P0 · 5 P1 · 4 P2 · 1 P3.** Two failing tests are left in the tree
(`backend/tests/test_audit_p0.py`, and the `test_defect_*` cases in
`audit/adversarial/test_audit_probes.py`). Full detail in `01-findings.md`.

**A second auditor then ran the same brief independently** and wrote up
`08-addendum-second-pass.md`. It confirms the P0 from the source, corroborates
the red-flag findings from its own separately written 48-case corpus, and adds
**five more P1s** — the worst of which is that `make seed` fails, so the
documented `docker compose up` never starts the API at all. Combined total:
**1 P0 · 10 P1**. Read that file second.

---

## The three things that matter

**1. Patient names are being sent to OpenAI. (AUD-001, P0)**
`engine.py:571` builds the semantic-cache key from the *raw* chief complaint,
not the de-identified copy that `assert_no_pii` checked eleven lines earlier.
In production `self.embeddings` is `OpenAIEmbeddings`, which POSTs that string
to `api.openai.com`. The retrieval arm on the line above uses the scrubbed text,
so the scrubbing is deliberate everywhere except here. Disabling the cache does
not help — `embed()` is called before the cache check. A test proving it is in
the tree, failing:

```
AssertionError: 2 identifier(s) reached an outbound provider
assert ['+998901112233', 'Zulfiya Ismoilova'] == []
```

*Do not set `OPENAI_API_KEY` in any environment holding real patient data until
this is fixed.* Half a day of work.

**2. Red flags cannot see the sentence. (AUD-003/AUD-004, P1)**
`CaseFacts.free_text` is populated and read by nothing; all 17 rules are
predicates over terminology concepts and vital-sign numbers. On 44 vignettes I
wrote without looking at the terminology map:

| red-flag cases | caught |
|---|---|
| backed by an abnormal vital sign | 14/38 — 36.8% |
| **text only** | **0/10 — 0.0%** |

Crushing chest pain radiating to the left shoulder extracts no concepts at all.
Blood coughed onto a handkerchief is classified as a **rash**. And negation
inverts the rules: *"no signs of dehydration"* fires `pediatric_dehydration`,
*"no blood in the sputum"* fires `hemoptysis`, *"there was no seizure"* fires
`febrile_seizure` — a 25% decoy false-positive rate against the project's
reported 2.6%, because the project's decoys do not use negation. The same
sentences in Russian return nothing, so the two language arms fail in opposite
directions.

Adding synonyms will not fix this. The safety layer needs a reader of free text.

**3. The controlled-substance block cannot fire. (AUD-002, P1)**
`constrain_treatment` drops an item only when `verdict.controlled` is true, and
**no row in `knowledge/formulary.csv` sets it**. An unknown drug returns
`controlled=False`. All five of morphine, tramadol, diazepam, fentanyl and
phenobarbital reach the clinician's screen labelled "Not available locally",
which reads as a stocking problem rather than a prohibition. The formulary is a
whitelist being used as a lookup; unknown drugs must fail closed.

Also worth a paragraph of your time: a clinic can silently delete another
clinic's synced consultation, because the sync idempotency key is global rather
than per-tenant (AUD-005, one hour to fix); and
`docs/EXECUTIVE_SUMMARY.md`'s "zero direct competitors" is contradicted by a
Cabinet of Ministers resolution of 10 July 2025 that puts an AI medical
assistant and clinical decision support tools inside the national DMED system
by end-2026 (AUD-009).

---

## What is genuinely good, and should not be lost in the above

438 backend tests, 53 Flutter tests, clean analyze, clean typecheck, a web build
that works, and a CI workflow that finally parses. Red flags fire through
provider outage, invalid schema, empty response, malformed JSON and an open
circuit breaker — and the degraded answer is shown to the clinician as a banner,
not hidden in a database column. The clinician gate has no hole on any of the
seven paths I enumerated, including the offline sync path that used to have one.
Paediatric doses are blocked without a weight, and the block is displayed rather
than silently applied. Offline-first is not a bullet point; it works end to end.

And the reporting is honest in a way that is rare. `README.md` states, in the
same block as its own headline figure, that the number measures agreement with
its own answer key, that the engine has never been evaluated, that the cost and
latency budgets are "unmeasured, not met", and that CI had never run. The
remediation pass found a red-flag rule that contradicted the WHO guidance
shipped in this repository and fixed it. **That capacity for self-correction is
the asset here — more than the code, and much more than the 97.6%.**

---

## The next experiment

**Two commands and one study, in that order.**

*This week:* buy one API key and run `make eval-model`. Every claim about cost,
latency and whether the LLM beats a rules table that never sees the free text is
blocked on one hour and under $100. It has been blocked on that for weeks.

*This quarter:* a retrospective chart study. **300 consecutive consultations
from 3 clinics** — one urban polyclinic, one rural QVP, one feldsher point —
labelled by **two independent Uzbek physicians**, blind, with a third resolving
disagreements, none of them a founder and none of them the people who wrote the
vignettes. Measure, in this order: **red-flag recall on cases that turned out to
be emergencies**; false-referral rate priced in patient days of travel; top-3
agreement; and seconds per consultation with a stopwatch in the room. Roughly
two physician-months and $8-12k — 4% of the raise.

Everything else is downstream of one unknown: does the danger-sign layer work on
real Uzbek clinical speech? Every number that currently says yes was produced by
text this project wrote.

---

## Confidence in this audit, and what I could not verify

Confidence: **high** on the backend, the evaluation and the reporting — all of
it was reproduced from a clean clone by running the code, and the two P0/P1
defects are demonstrated by failing tests in the tree rather than by argument.
**Moderate** on the mobile UI, which I read and tested but never ran. **Low** on
anything clinical: I am not a clinician, my 44 vignettes are unreviewed, and the
ground truths I assigned are my own — they are useful for testing whether the
*mechanism* sees a danger sign, and are not a clinical benchmark.

The two things I could not verify from this repository alone:

1. **Whether the engine is any good.** No API key exists here, so the model path
   remains unmeasured — by me as well as by the project.
2. **Whether a feldsher would use it.** No device or emulator was available, so
   `flutter run` and the stopwatch were impossible, and seconds-per-consultation
   is the number the value proposition actually rests on.

One thing failed for reasons that are mine, not the repository's:
`docker compose up --build` cannot install Python packages in this sandbox,
because the build container does not trust the audit environment's TLS
interception. A control build of `python:3.11-slim` + `pip install requests`
fails identically. Unverified, not a finding.

---

| | |
|---|---|
| `01-findings.md` | every finding, sorted by severity, with reproduction |
| `02-evaluation-reality.md` | what was measured; the audit's own out-of-vocabulary set |
| `03-clinical-safety.md` | the gate enumeration, re-identification, TB, referrals |
| `04-plan-vs-built.md` | capability table, traction gates, recomputed economics |
| `05-regulatory.md` | device classification, sandbox, ZRU-547, observability |
| `06-next-90-days.md` | ordered plan, owners, effort, decisions unblocked |
| `07-strategic-verdict.md` | the feldsher question, the moat, the kill argument |
| `adversarial/` | 44 vignettes, probe suite, runnable reproduction |
