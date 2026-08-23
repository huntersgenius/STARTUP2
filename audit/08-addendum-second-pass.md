# Addendum — independent second audit pass

A second auditor ran the post-execution audit brief against the same commit
(`208e460`) without access to the first pass's working notes, and discovered the
first pass's output (`8365d54`) only after its own measurements were complete.
Two independent passes over the same system is a better instrument than one, so
this file records where they agree, where the second pass found something the
first did not, and where the second pass corrected itself.

Everything below was produced by running the system. Deviations from the brief's
setup block are recorded in §5.

---

## 1. Independent verification of the first pass's P0

**AUD-001 is VERIFIED independently.** The second pass re-derived it from the
source rather than accepting the finding:

- `backend/app/ai/engine.py:244` — retrieval correctly uses
  `scrubbed.get("chief_complaint", "")`.
- `backend/app/ai/engine.py:316` — presentation correctly uses `scrubbed`.
- `backend/app/ai/engine.py:571` — the semantic-cache embedding uses
  `case.chief_complaint`, which `normalize()` sets from
  `consultation.chief_complaint` verbatim at `engine.py:161`.

So one line out of three uses the raw text, and it is the line that calls
`self.embeddings.embed(...)` — `OpenAIEmbeddings` in production
(`backend/app/ai/providers/embeddings.py:53`). The de-identified copy exists
eleven lines earlier and is not used. The finding stands exactly as written.

`backend/tests/test_audit_p0.py` fails, as intended.

---

## 2. Findings the first pass did not report

### A2-001 (P1) — `make seed` fails, so `docker compose up` never starts the API

**VERIFIED.** `app/seed.py:78-79` calls `session.flush()` before
`patient.set_pii(...)` at line 80. The flush issues the INSERT with
`pii_blob = NULL`, violating the NOT NULL constraint declared at
`app/models/patient.py:37`.

Reproduced on both engines:

```
$ ENVIRONMENT=dev DATABASE_URL="postgresql+psycopg://sihhat:sihhat@localhost:5432/sihhat" \
    PYTHONPATH=.. ../.venv/bin/python -m app.seed --if-empty
sqlalchemy.exc.IntegrityError: (psycopg.errors.NotNullViolation)
  null value in column "pii_blob" of relation "patients" violates not-null constraint

$ # same against SQLite
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError)
  NOT NULL constraint failed: patients.pii_blob

$ echo $?
1
```

The `set_pii` hardening added in Sprint 3 — `if self.id is None: self.id =
uuid.uuid4()` at `app/models/patient.py:57-58` — exists precisely so that PII
can be set *before* the flush. The caller was never updated to match, so the old
ordering is now the wrong ordering.

**Consequence.** `infra/docker-compose.yml:48-50` runs
`alembic upgrade head && python -m app.seed --if-empty && uvicorn ...`. Because
seed exits 1, the `&&` chain stops and **uvicorn never starts**. The documented
one-command bring-up in `README.md:25-26` does not produce a running system, and
no test covers it — no file under `backend/tests/` imports `app.seed`.

This is why the second pass had to hand-write a seed script to get a running API
at all (§5).

**Fix:** move the `set_pii` call above `session.add`/`flush`, and add a test that
runs `app.seed` against a temporary database. Under an hour.

---

### A2-002 (P1) — the commonest Russian intensifier is read as tuberculosis

**VERIFIED.** `sil` is Uzbek for tuberculosis and is a terminology surface. The
Cyrillic→Latin pass at `knowledge/terminology.py:261` transliterates Russian
`сильно` to `silno`, and the five-character suffix allowance at
`knowledge/terminology.py:228-234` (`MAX_SUFFIX_CHARS = 5`) lets the surface
`sil` claim it.

```
$ PYTHONPATH=backend:. .venv/bin/python audit/adversarial/probe2.py "сильно болит голова"
text     : сильно болит голова
concepts : ['tuberculosis']
red flags: []
```

Every one of these injects a spurious `tuberculosis` concept:
`Сил нет`, `сильная боль`, `сильный кашель`, `сильно болит`, `У меня нет сил`.
These are not edge cases — `сильно болит` ("hurts badly") and `сил нет` ("no
strength") are among the most common things a Russian-speaking patient says.

It already reaches the repository's own evaluation: **8 of the 249 main-set
vignettes** carry a spurious `tuberculosis` concept from their Russian text
while belonging to a non-TB category, including all six `resp-sev-*` severe
pneumonia cases ("Сильный кашель 3 дня…").

**Consequence.** TB is a live differential in Uzbekistan. Seeding it from the
word "strongly" both corrupts the differential and, in the other direction,
trains a clinic to discount a TB signal that is usually noise. It also silently
contaminates the accuracy numbers.

**Fix:** require a minimum surface length before the suffix allowance applies
(a 3-character surface should not absorb a 2-character suffix), or exclude
single-syllable surfaces from the transliteration pass. Half a day, plus a
regression test per script.

Proven failing by `backend/tests/test_audit_p0_red_flag_evasion.py::test_russian_intensifier_is_not_read_as_tuberculosis`.

---

### A2-003 (P1) — `158/158` is 32 distinct assertions, and four rules are never tested

**VERIFIED.** The first pass established that the 249 vignettes are 92 distinct
texts. Decomposing the *safety* number specifically:

| | |
|---|---|
| Red-flag expectations counted in the headline | 158 |
| Distinct (text, flag) pairs behind them | **32** |
| Distinct texts carrying any expectation | 25 |
| Rules exercised by exactly **one** text | **10 of 15** |
| Rules in `red_flags.py` never exercised at all | **4 of 17** |

The ten single-text rules are `acs_suspected`, `stroke_fast`, `meningism`,
`pregnancy_bleeding`, `hypoglycemia`, `gi_bleeding`, `hemoptysis`,
`severe_anemia`, `imci_danger_sign`, `pediatric_dehydration` — that is, almost
every rule whose failure kills someone.

The four never exercised by the main set are **`airway_compromise`,
`preeclampsia_suspected`, `respiratory_distress`, `seizure`**.

Reproduce: `PYTHONPATH=backend:. .venv/bin/python audit/adversarial/probe2.py --help`
is not needed; the decomposition is a six-line script over
`backend/app/ai/eval/data/vignettes.json`, included as §4 of
`audit/adversarial/README-second-pass.md`.

**Consequence.** "100% red-flag recall (158/158)" reads to an investor or a
sandbox reviewer as 158 independent safety checks. It is 32, ten of which are
single points of evidence, and four rules that carry no evidence whatsoever.

---

### A2-004 (P1) — the only enforced safety gate is the one that cannot fail

**VERIFIED.** In `.github/workflows/ci.yml`:

- line 86 — the `eval` job gates `--fail-under-redflag 1.0` on the **main**
  (in-vocabulary) set.
- lines 122-123 — the `eval-integrity` job runs `--set oov` and
  `--set adversarial` with **no `--fail-under-*` flags at all**.
- line 125 — a redflag gate is applied to `--set injection` only.

So the number that is enforced on every push is the one measured against text
written in the rules' own vocabulary, which is 100% by construction. The two
numbers that describe behaviour on unfamiliar wording — 4.5% and 31.6% — are
printed to the log and gate nothing. A change that improved in-vocabulary recall
while destroying real-world recall would pass CI green.

**Fix:** add a floor to the oov and adversarial runs, set at today's measured
value, so the honest numbers can only move upward. An hour.

---

### A2-005 (P1) — the runbook's first two steps use an admin UI that does not exist

**VERIFIED.** `docs/PILOT_RUNBOOK.md:33-36` instructs the founder:
"Admin dashboard → Clinics → New clinic". `docs/PILOT_RUNBOOK.md:38-41`:
"Admin → Bulk users."

The admin app ships three routes — `/`, `/audit`, `/clinics` — confirmed by the
production build:

```
Route (app)                    Size     First Load JS
┌ ○ /                          3.58 kB        90.7 kB
├ ○ /_not-found                873 B            88 kB
├ ○ /audit                     2.98 kB        90.1 kB
└ ○ /clinics                   2.69 kB        89.8 kB
```

`web/src/app/clinics/page.tsx` contains no `form`, `button`, or submit handler —
it is read-only. There is no bulk-users route. The API supports both operations
(`POST /api/v1/admin/clinics`, `POST /api/v1/admin/users/bulk`), so the gap is
UI-only.

**Consequence.** The runbook's stated definition of done is "a clinic is
onboarded end to end by following this document alone, with no engineer
present." Steps 1.1 and 1.2 cannot be completed without an engineer holding a
bearer token and a terminal. Since the brief treats documentation that does not
reproduce as a P1, this is one.

**Fix:** either build the two forms (a day), or rewrite the runbook steps as
`curl` invocations with a token-acquisition step (an hour) and stop claiming
no engineer is needed.

---

## 3. A second, independently authored adversarial set

The brief requires the OOV set to be built "independently of anything in the
repository". The second pass wrote its own — 48 vignettes, 19 red-flag evasion
cases, 12 decoy cases — before reading `knowledge/terminology.csv` or the bodies
of the red-flag rules. It is deliberately *not* merged with the first pass's
44-case set; two blind sets agreeing is the evidence.

The scoring harness reproduces the repository's published figures exactly, which
is what licenses its other numbers:

```
$ PYTHONPATH=backend:. .venv/bin/python audit/adversarial/run_audit2_eval.py

  set              recall      n
  oov               32.3%     62      <- second pass, authored blind
  evasion           10.5%     38      <- second pass, danger present, rule's words absent
  decoy               n/a      0      <- 5 flags fired that must not have
  repo-main        100.0%    158      <- reproduces `make eval` exactly
  repo-oov           4.5%     22      <- reproduces REMEDIATION.md exactly
```

### 3.1 The real safety number is 10.5%

On the evasion set — one case per rule, the danger unambiguous, described in the
words a patient or relative would use — **4 of 38 expectations were met**. All
four came from an abnormal vital sign (`evade-sepsis`, `evade-preeclampsia`).
**Every text-driven rule scored zero: 0 of 34.**

The deterministic red-flag layer contributes essentially nothing outside its own
phrase dictionary. What survives is the numeric rules on vitals — which is worth
saying plainly, because it is also the honest description of what the product
can be sold as today.

Individually, and each one is a person:

| Case | Presentation | Concepts extracted | Flags |
|---|---|---|---|
| `evade-acs` | crushing chest pain radiating to jaw, breathless | `[]` | none |
| `evade-stroke` | pialat dropped from hand, mouth drooping, speech confused, 30 min ago | `['hypertension']` | none |
| `evade-seizure` | whole body stiffened then shook, bit tongue, incontinent | `[]` | none |
| `evade-gi-bleeding` | coffee-ground vomit, tar-black stool, dizzy | `['onset_1d']` | none |
| `evade-dehydration` | sunken eyes, no tears, skin tents, dry nappy | `[]` | none |
| `evade-severe-anemia` | pale as a wall, breathless lying still, fell twice today | `[]` | none |

### 3.2 The same layer fires on explicit denials

Five decoy cases produced a flag that must not have fired:

| Case | Text | Fired |
|---|---|---|
| `decoy-controlled-hypertension` | "**Ko'krak og'rig'i yo'q, nafas qisishi yo'q.** Retsept uchun keldim." | `acs_suspected` |
| `decoy-negated-hemoptysis` | "**Qon tupurish yo'q**, balg'am oq" | `hemoptysis` |
| `decoy-history-not-now` | "**O'tgan yili** … stent qo'yishgan. **Hozir shikoyatim yo'q**" | `acs_suspected` |
| `decoy-postictal-known-epilepsy` | "oxirgi tutqanoq **olti oy oldin**" | `seizure` |

`X yo'q` is Uzbek for "no X". There is no negation handling and no temporal
scoping: a symptom denied and a symptom present are the same token to the
matcher, as is a symptom from last year.

This corroborates the first pass's AUD-004 from a second, independently written
corpus.

### 3.3 The mechanism, isolated

The matcher is a contiguous-substring dictionary
(`knowledge/terminology.py:219`, `haystack.find(surface, start)`). Every
`chest_pain` surface is a multi-token phrase. So:

```
ko'kragim og'riyapti          -> ['chest_pain']
ko'kragim qattiq og'riyapti   -> []              <- "badly"
ko'kragim juda og'riyapti     -> []              <- "a lot"
ko'kragim biroz og'riyapti    -> ['severity_mild'] <- "a little"
ko'krakda og'riq bor          -> []              <- "there is pain in the chest"
```

Uzbek places the intensifier between the body part and the verb. **The system is
therefore monotonically worse at recognising the more severe presentation**, and
in the `biroz` case the only concept it extracts is the reassuring one.

Twelve assertions proving this are left failing in
`backend/tests/test_audit_p0_red_flag_evasion.py`. The correct fix is to make
the concept layer read the clinical picture, **not** to add these sentences to
`terminology.csv` — adding them would turn the tests green without making a
patient safer, which is the failure mode the tests exist to catch.

---

## 4. Where the second pass agrees with the first

- **`respiratory_infection` 83.3% is not a TB confusion.** Reached independently:
  all 12 failures are one text ("Кашель две недели, много мокроты, температуры
  нет. Курит.") duplicated across `resp-005/010/015/020/025/030` × 2 languages,
  on which the engine returns `predicted: []` — it declines. Twelve failures are
  one failure counted twelve times. The brief's hypothesis is **CONTRADICTED**.
- **Reporting integrity holds.** `README.md:78-130` names the provider above
  every table, states the engine has never been evaluated, and states the cost
  and latency budgets are unmeasured rather than met. The second pass looked for
  an unattributed baseline figure and did not find one.
- **Every published figure reproduces.** `make eval` → 97.6% / 94.4% /
  100.0% (158/158); `make test` → 438 passed.

---

## 5. Deviations from the brief's setup block

| Step | Result |
|---|---|
| `make test` | 438 passed in 46.5s |
| `make eval` | ran; figures as published |
| `make eval-gate` | passed |
| `cd backend && … python -m app.ai.eval.run --offline` | **failed** — `ModuleNotFoundError: sqlalchemy`. The brief's literal command uses the system `python`; the repository documents `make eval`, which works. Not a repository defect. |
| `cd mobile && flutter analyze && flutter test` | clean; 53 tests passed |
| `cd web && npm run typecheck && npm run build` | clean; 6 static routes |
| `docker compose -f infra/docker-compose.yml up --build` | **could not run** — no Docker daemon in the audit environment (`dial unix /var/run/docker.sock: no such file or directory`). |

Because the container path was unavailable, the second pass installed
PostgreSQL 16 with pgvector locally, ran `alembic upgrade head` (three
migrations, clean), ingested the corpus (10 documents → 32 chunks, 49 formulary
items, 133 terminology entries), and booted `uvicorn` directly. That is how
A2-001 was found: the seed step of the compose command fails, and would have
failed inside the container too.

A real consultation was then run end to end through the API. The transcript is
in `audit/evidence/`. Two observations from it:

- With the eval set's exact wording, `acs_suspected` fires and the response
  carries `risk 0.7 / very_high`, an immediate referral, and the disclaimer.
- With an ordinary paraphrase of the same clinical picture
  (`Ko'kragim qattiq og'riyapti va nafas qisyapti, ter bosdi`, BP 150/95,
  HR 104), the same endpoint returned `red_flags: []`, `differentials: []`,
  `risk 0.0 / low`, `referral.needed: false`.

`docs/PILOT_RUNBOOK.md:75` instructs the installer to verify on day 0 that "the
red-flag banner appears when you enter chest pain with breathlessness". Whether
that acceptance test passes depends on which words the installer happens to
type.

---

## 6. What the second pass could not verify

- **The container path.** No Docker daemon was available, so
  `infra/Dockerfile.backend`, `Dockerfile.web`, the edge bundle in
  `infra/edge/`, and the compose healthchecks were read but never executed.
- **Anything on the model path.** No `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
  exists in this environment, so the prompt-injection tests the brief requires
  on the model path could not be run, and neither could the cost and latency
  budgets. The first pass's AUD-001 is a code-path finding, not an observed
  network capture, for the same reason — the raw string is demonstrably passed
  to `embed()`, but no packet was watched leaving the process.
