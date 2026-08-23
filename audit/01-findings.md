# Findings

Post-execution audit of SihhatAI, `huntersgenius/startup2`, branch
`claude/github-startup-repo-3qm5c6`, commit `208e460`. Audited 2026-08-21.

Every finding below was produced by a command in this repository. Reproduction
commands are given inline; the backend ones live in
`audit/adversarial/test_audit_probes.py`, `backend/tests/test_audit_p0.py` and
`audit/adversarial/run_audit_set.py`.

Claim types: `VERIFIED` (reproduced), `UNFALSIFIABLE` (structured so it cannot
fail), `CONTRADICTED` (the code or a run says otherwise).

Two failing tests are left in the tree on purpose:
`backend/tests/test_audit_p0.py` (AUD-001) and the three `test_defect_*` cases
in `audit/adversarial/test_audit_probes.py` (AUD-002, AUD-005, AUD-006). Delete
each only with the fix that makes it pass.

> **A second, independent pass ran this same brief against the same commit and
> is written up in [`08-addendum-second-pass.md`](08-addendum-second-pass.md).**
> It re-derived AUD-001 from the source and confirms it, corroborates AUD-003
> and AUD-004 from a separately authored corpus, and adds five findings this
> file does not carry: **A2-001** (`make seed` fails, so `docker compose up`
> never starts the API — P1), **A2-002** (the Russian intensifier `сильно` is
> read as `tuberculosis` — P1), **A2-003** (`158/158` is 32 distinct assertions
> and four rules are never exercised — P1), **A2-004** (the only enforced CI
> safety gate is the one that cannot fail — P1), and **A2-005** (the runbook's
> first two steps use an admin UI that does not exist — P1). It leaves twelve
> further failing assertions in
> `backend/tests/test_audit_p0_red_flag_evasion.py`.
>
> Running total across both passes: **1 P0 · 10 P1**. `make test` reports
> `14 failed, 438 passed`; all 14 failures are deliberate audit artefacts.

---

## P0

### AUD-001 — the raw chief complaint is sent to a third-party embedding API

**VERIFIED.** Severity P0: patient identifiers reach a third-party model, and
leave Uzbekistan.

`DiagnosticEngine.analyze` builds the semantic-cache key from the unscrubbed
column:

```python
# backend/app/ai/engine.py:571
query_vector = self.embeddings.embed([f"{case.chief_complaint} {' '.join(case.concepts)}"])[0]
cached = self.cache.get(bucket, query_vector) if self.cache else None
```

`case.chief_complaint` is `consultation.chief_complaint` verbatim
(`engine.py:161`). The de-identified copy — the one `deidentify()` produced and
`assert_no_pii` checked (`engine.py:234-236`) — is `scrubbed`, and it is not
used here. The retrieval arm eleven lines earlier *does* use the scrubbed text
(`engine.py:243-248`), so the scrubbing is deliberate everywhere except on this
line.

In production `self.embeddings` is `OpenAIEmbeddings`:

```python
# backend/app/ai/providers/embeddings.py:79
def get_embeddings(prefer_offline: bool = False):
    if prefer_offline or settings.testing or not settings.openai_api_key:
        return HashingEmbeddings()
    return OpenAIEmbeddings()
```

and `OpenAIEmbeddings.embed` POSTs the strings it is given to
`https://api.openai.com/v1/embeddings` (`embeddings.py:63-76`).

**Failure scenario.** A feldsher types
`Bemor Zulfiya Ismoilova, tel +998901112233. 3 kundan beri balg'amli yo'tal…`
— which is how rural notes are written. The name and number are POSTed to a US
endpoint before the model call, and the audit row records only the *scrubbed*
`input_hash`, so nothing in the system shows it happened.

**Reproduction:**

```
cd backend && PYTHONPATH=.. ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///:memory:" \
  python -m pytest tests/test_audit_p0.py -v
```

```
AssertionError: 2 identifier(s) reached an outbound provider
assert ['+998901112233', 'Zulfiya Ismoilova'] == []
```

**Argument against.** *A deployment could leave `OPENAI_API_KEY` unset and run
only the local Llama, in which case `get_embeddings()` returns
`HashingEmbeddings` and nothing leaves.* That is true and it is why the tests
pass today. It does not survive contact with the intended production
configuration: the same `openai_api_key` setting selects `OpenAIProvider` for
the reasoning model, `openai_model` defaults to `gpt-4o`, and
`CODE_PATHS["openai"]` describes the online product as "full eight-stage
engine, GPT-4o". Any deployment that runs the online path necessarily sets the
key, and setting it silently switches the embedder too. A second counter — *the
semantic cache could be disabled* — fails on the code: `embed()` is called
unconditionally on line 571 and the `if self.cache` check is on line 574. The
finding stands.

**Fix.** Use `scrubbed["chief_complaint"]` for the cache vector, and move
`assert_no_pii` to a wrapper around every provider's outbound call rather than
around one intermediate dict. Half a day, plus a test that asserts on the bytes
handed to each provider.

**Legal note.** Under the Law "On Personal Data" ZRU-547 as amended in force
27 March 2026, ordinary personal data may be processed abroad only where
information-security requirements, international protection standards and
oversight by an authorised state body are satisfied *simultaneously*. See
`audit/05-regulatory.md`.

---

## P1

### AUD-002 — the controlled-substance block cannot fire

**CONTRADICTED.** The spec required that controlled substances are never
emitted; `constrain_treatment` says so in a comment:

```python
# backend/app/ai/engine.py:415-418
if verdict.controlled:
    logger.warning("dropped controlled substance suggestion: %s", item.drug)
    continue
```

`verdict.controlled` is read from the `controlled` column of
`knowledge/formulary.csv`. **No row in that file sets it.** For a drug that is
not in the formulary at all, `FormularyService.check` returns
`controlled=False, available=False, reason="not_in_national_formulary"`
(`knowledge/formulary.py:145-154`), so the item falls through to the `else`
branch and is presented with "Not available locally" — which reads to a
clinician as a stocking problem, not a prohibition.

**Reproduction:**

```
cd backend && PYTHONPATH=.. ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///:memory:" \
  python -m pytest ../audit/adversarial/test_audit_probes.py -k controlled -v -s
```

```
formulary rows: 49; controlled=true: 0
morphine        controlled=False  reason=not_in_national_formulary
tramadol        controlled=False  reason=not_in_national_formulary
diazepam        controlled=False  reason=not_in_national_formulary
AssertionError: 5 controlled substance(s) survived constrain_treatment:
  ['morphine', 'tramadol', 'diazepam', 'fentanyl', 'phenobarbital']
```

**Failure scenario.** GPT-4o proposes tramadol for the back-pain presentation
that is 40 of the 249 vignettes. The clinician sees `tramadol 10 mg oral` with
a note that it is not stocked. Nothing tells them it is prohibited.

**Argument against.** *A clinician still has to accept the suggestion, and a
clinician who prescribes an opioid for mechanical back pain has made their own
error.* Partly right — this is why it is P1 and not P0. But the product's
stated safety contract is that this class of drug never reaches the screen, and
that contract is what a regulator will be shown. A control that is unreachable
with the shipped data is not a control.

**Fix.** Two parts, and only doing the first is worse than doing neither:
populate `controlled` in the CSV from the national controlled-substances list,
**and** make an unknown drug fail closed — an item the formulary has never
heard of should be dropped or held, not annotated. One day plus clinical
review of the list.

---

### AUD-003 — the red-flag rules cannot read the patient's words

**VERIFIED.** Every rule in `backend/app/ai/red_flags.py` is a predicate over
`facts.concepts` and vital-sign numbers. `CaseFacts` declares a `free_text`
field (`red_flags.py:94`) and `engine.py:213` populates it, and **no rule reads
it**:

```
$ grep -rn "free_text" backend/app knowledge ml --include=*.py
backend/app/ai/red_flags.py:94:    free_text: str = ""
backend/app/ai/engine.py:213:                free_text=case.chief_complaint,
```

So a danger sign is detected if and only if `knowledge/terminology.csv`
contains a surface matching the words used. Measured on the audit's own
vignette set (`audit/adversarial/`, 44 cases written without reference to the
map):

| red-flag cases | caught |
|---|---|
| backed by an abnormal vital sign | 14/38 — 36.8% |
| **text only** | **0/10 — 0.0%** |

Not one text-only danger fired. The concept extractor on the same strings:

```
ACS radiating to the left shoulder   -> []
stroke, facial droop + slurred speech-> []
child choking, blue, silent          -> ['cough']
haematemesis ("qon aralash qusdim")  -> ['vomiting']
melena ("najasim qora, qatron kabi") -> ['dizziness']
haemoptysis ("dastro'molda qon dog'lari") -> ['rash']
"Ko'kragim og'ir"                    -> []
"Ko'kragim og'ir, sovuq ter bosdi, nafasim qisyapti" -> ['sweating', 'dyspnea']
```

The last line is the one to look at. Blood coughed onto a handkerchief is
classified as a **rash**. And the classic ACS sentence yields `sweating` and
`dyspnea` but never `chest_pain`, so `acute_coronary_syndrome`, which requires
`chest_pain AND (dyspnea|sweating|syncope)`, cannot fire no matter how many
associated features are present.

**Reproduction:**

```
cd backend && PYTHONPATH=..:. ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///:memory:" \
  python ../audit/adversarial/run_audit_set.py
```

**Failure scenario.** A 66-year-old describes crushing chest pain radiating to
the shoulder. No red flag fires, no referral banner appears, and the
differential engine has no concepts to rank, so the screen shows follow-up
questions. The clinician is not warned.

**Argument against.** *The project already publishes 4.5% red-flag recall on
its own out-of-vocabulary set and says in `README.md` that "the app must not be
described to a clinician as a safety net for missed danger signs."* That is
true and it is to their credit. What is added here is the mechanism and its
shape: the surviving 37% is entirely the rules that read numbers. Adding
vocabulary cannot fix the other half, because the failure is not lexical
coverage — it is that the safety layer never sees the sentence. That changes
what the fix has to be, so it is a finding and not a restatement.

**Fix.** Not a synonym list. Either the model gets a separate, cheap,
structured "danger present?" call whose output can only *add* flags, or the
clinician answers a short mandatory danger-sign checklist that feeds `concepts`
directly. Both are days of work; choosing between them needs the clinical
advisor.

---

### AUD-004 — negation inverts the rules

**VERIFIED.** The terminology map is surface matching with no negation scope,
so a symptom that is explicitly denied fires as if present:

```
"suvsizlanish belgilari yo'q"  (no signs of dehydration) -> ['diarrhea', 'dehydration']
"balg'amda qon yo'q"           (no blood in the sputum)  -> [..., 'hemoptysis']
"talvasa bo'lmadi"             (there was no seizure)    -> ['fever', 'febrile_seizure']
"Ich ketishi yo'q"             (no diarrhoea)            -> ['diarrhea', 'vomiting']
```

On the audit set this produced three forbidden red flags, all in Uzbek:

```
aud-dec-002[uz]  ['imci_danger_sign', 'pediatric_dehydration']
aud-dec-003[uz]  ['hemoptysis']
aud-dec-006[uz]  ['imci_danger_sign']
```

Decoy false-positive rate 25.0% (3/12) against the project's own reported 2.6%,
because the project's decoys do not use negation.

The same sentences in Russian return `[]`, so the two language arms fail in
opposite directions: Uzbek over-fires on denial, Russian under-fires entirely
(`aud-oov-005[ru]` and `aud-adv-005[ru]` missed flags their Uzbek twins
caught).

**Failure scenario.** A mother says her child has diarrhoea *but no signs of
dehydration and is drinking well*. The system raises an IMCI danger sign and
tells her to go to hospital. In a district where referral is a day of travel
and a day of lost wages, this is the finding that makes clinics stop using the
product — and it is the same defect that would let a genuinely negated red flag
be reported as caught.

**Fix.** A negation-scope pass over the matcher (a window of 3-5 tokens after
`yo'q`, `emas`, `bo'lmadi`, `нет`, `не`) with tests in both languages. Two to
three days, and it needs a native speaker, not a regex written from English
intuition.

---

### AUD-005 — sync idempotency keys are global, not per clinic

**VERIFIED.** Severity P1: silent loss of a clinical record, plus a cross-tenant
identifier disclosure.

```python
# backend/app/api/sync.py:149-151
existing_receipt = db.execute(
    select(SyncReceipt).where(SyncReceipt.operation_id == op.operation_id)
).scalar_one_or_none()
```

No clinic or device predicate. `operation_id` is chosen by the client
(`sync.py:52`) and `SyncReceipt.operation_id` is globally unique. Clinic B's
operation is then answered `duplicate` and never applied, and the response
returns clinic A's `server_entity_id`.

**Reproduction:** `test_defect_sync_operation_ids_are_scoped_to_a_clinic`

```
clinic B result: {'operation_id': 'op-cf0bdc6f54dd', 'status': 'duplicate',
 'entity_type': 'consultation', 'server_id': '4f33038f-0f00-47b1-8323-21a566012c76'}
```

`server_id` there is the patient row clinic **A** created.

**Failure scenario.** A clinic comes back online after a week and pushes 300
operations. Any whose id collides with another clinic's is reported accepted
and silently dropped. `sync.py:5` states the first principle of the module as
"Never lose a record."

**Argument against.** *Ids are client-generated UUIDs, so accidental collision
is vanishingly unlikely, and a device that forges one has to be authenticated
anyway.* The accidental case is indeed unlikely — though the schema permits any
8-to-80-character string, and a device that numbers operations `op-1`,
`op-2`… is not a strange implementation. The deliberate case needs only a valid
account at any clinic, which every pilot participant has. And the cost of the
fix is a two-column index. The finding stands.

**Fix.** Make the receipt lookup `(clinic_id, operation_id)` and the uniqueness
constraint composite. One hour plus a migration.

---

### AUD-009 — "zero direct competitors" is contradicted by public policy

**CONTRADICTED.** `docs/EXECUTIVE_SUMMARY.md:33` claims "**First mover** in
Uzbekistan healthcare AI with zero direct competitors" and line 81 "**No
competitor** has built healthcare AI for this 38.2 million-person market".

The Cabinet of Ministers approved an AI roadmap by resolution of 10 July 2025
which includes, for delivery by end-2026, an AI "digital medical assistant"
piloted in the Almazar and Yunusabad districts of Tashkent and integrated into
the national Unified Medical Information System (DMED) — and, in the same
roadmap, **clinical decision support tools**.

That is not a competitor in the ordinary sense; it is the state, building the
same product inside the system every clinic is already required to use. It is
the first thing a due-diligence call will surface.

**Fix.** Rewrite the claim. The defensible version is narrower and still
interesting: no *commercial* Uzbek-language CDS product is in market, the state
programme is a distribution channel as much as a rival, and the wedge is the
offline rural clinic that DMED integration does not reach.

---

## P2

### AUD-006 — the append-only guarantee is not exercised by the test suite

**VERIFIED.** Immutability of `audit_logs` is a Postgres trigger installed by
`backend/alembic/versions/b1a2c3d4e5f6_audit_append_only.py`. The test suite
builds its schema with `Base.metadata.create_all` on SQLite
(`backend/tests/conftest.py:29-38`), which does not run migrations, so the
trigger does not exist and an `UPDATE` succeeds:

```
test_defect_audit_log_rows_cannot_be_updated FAILED
```

The chain itself still does its job — after the same tamper,
`verify_chain` returns `ok=False, "hash mismatch at seq 2"` — so detection
holds even where prevention is absent. That is why this is P2 and not P1.

**Consequence.** A migration that drops or fails to apply the trigger would not
be caught by any test. **Fix:** run the audit tests against a Postgres service
container, as the project's own `ci.yml` already provisions for the `backend`
job. Half a day.

---

### AUD-007 — a clinic's audit export cannot be verified by the recipient

**VERIFIED by inspection.** `/admin/audit/export` filters rows to the caller's
clinic (`backend/app/api/admin.py:279-280`) while `seq` and `prev_hash` chain
across the whole installation (`backend/app/core/audit.py:98-100`). A clinic's
CSV therefore contains a subsequence with gaps whose `prev_hash` values point
at rows the recipient does not have, so `verify_chain` on that export reports
`sequence gap` immediately.

The export exists, per its own docstring, "for the regulatory sandbox
application". Its whole value is that a third party can check it, and a third
party cannot.

**Fix.** Either chain per clinic, or ship a Merkle inclusion proof alongside the
filtered rows. One to two days; the design choice matters more than the code.

---

### AUD-008 — a documented command does not run

**VERIFIED.** `docs/EVAL_INTEGRITY.md:12` gives

```
cd backend && python -m ml.evaluate_risk
```

which fails: `No module named 'ml'`. `REMEDIATION.md:221` gives it without the
`cd`, which fails the same way. The working invocation needs `PYTHONPATH=..`:

```
cd backend && PYTHONPATH=.. ENVIRONMENT=test \
  DATABASE_URL="sqlite+pysqlite:///:memory:" python -m ml.evaluate_risk
```

Once run, the numbers reproduce exactly (main 100.0%/97.3%, oov 20.0%/90.6%,
adversarial 42.1%/94.7%). **Fix:** ten minutes, or a `make` target.

---

### AUD-010 — voice input is in the plan and not in the code

**VERIFIED.** `mobile/pubspec.yaml` declares `record: ^5.1.2` under a `# Voice`
heading. No Dart file imports it; there is no transcription path anywhere in
`backend/` or `mobile/lib/`. The business plan's voice-input feature does not
exist.

This is worth knowing for two reasons beyond the feature gap. First, it is the
one MVP item where absent is *safer* than present: voice samples are biometric
data, which the amended personal-data law still requires to be stored inside
Uzbekistan, so a Whisper integration would have been a hard legal problem, not
a soft one. Second, an unused dependency in a medical app is a supply-chain
surface with no compensating benefit. **Fix:** delete the dependency until the
feature is built. Ten minutes.

---

## P3

### AUD-011 — the audit-verify endpoint leaks a cross-tenant volume signal

**VERIFIED by inspection.** `/admin/audit/verify`
(`backend/app/api/admin.py:260-263`) takes no `user` parameter and returns
`entries: audit.chain_length(db)` — the global row count — to any clinic admin.
Weak, but it is the only route in the API with no tenant predicate at all, and
it sits next to the one that does have one.

---

## Reporting claims that were checked and hold

Stated because the brief asks the audit to make claims harder to believe, and
these got harder to disbelieve.

| Claim | Result |
|---|---|
| `make test` → 438 passed | **VERIFIED**, 52.9 s |
| main set 97.6% top-3, 100.0% red-flag recall, 0.0% false referrals | **VERIFIED** exactly |
| out-of-vocabulary 31.0% top-3, 4.5% (1/22) red-flag recall | **VERIFIED** exactly |
| adversarial 31.6% (12/38) caught, 2.6% decoys | **VERIFIED** exactly |
| overlap: 58.9% word coverage, 26 templates, 637/811 surfaces unused, 8 phrase-separable classes | **VERIFIED** exactly |
| risk scorer 100.0%/97.3% main, 20.0%/90.6% oov | **VERIFIED** exactly |
| `--provider openai` refuses to run without a key | **VERIFIED**, exits 1 |
| `.github/workflows/ci.yml` parses | **VERIFIED**, 7 jobs |
| Flutter: analyze clean, 53 tests pass | **VERIFIED** |
| Web: `tsc --noEmit` clean, `next build` succeeds | **VERIFIED** |
| red flags survive outage, invalid schema, empty response, malformed JSON, open breaker | **VERIFIED** — all four failure modes and the open breaker still fire `hypoxia` and set `degraded=True` |
| paediatric dose blocked without a weight, and shown as blocked in the UI | **VERIFIED** (`suggestion_view.dart:61-71`) |
| degraded answers are visible to the clinician | **VERIFIED** — amber banner, `suggestion_view.dart:33-42` |
| cross-clinic patient and consultation reads return 404, not 403 | **VERIFIED** (`deps.py:83-97`, 9 isolation tests) |
| the nurse cannot close the clinical gate, online or via sync | **VERIFIED** (`ai.py:169`, `sync.py:233`) |
| a second decision on the same suggestion is refused | **VERIFIED** (`ai.py:186-192`, 409) |
| ECE reported as 0.279 | **drifts**: this run reported 0.288 with mean confidence 0.672 against 0.279/0.680 in `REMEDIATION.md`. Same command, same commit. Worth one look before anyone quotes the third decimal. |

One measurement is **UNFALSIFIABLE** by construction and is already labelled as
such by the project: every accuracy figure on the main set is agreement between
text this project wrote and a dictionary this project wrote, scored against an
answer key this project wrote. `README.md` now says so in the same block as the
number. No further action beyond what `audit/06-next-90-days.md` proposes.
