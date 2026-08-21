# What was actually measured

Workstreams 1 and 2. Audited 2026-08-21 at commit `208e460`.

---

## 1. Provider attribution

The brief expected to find baseline numbers presented as engine numbers. It was
true when the brief was written and it is not true now: the remediation pass
fixed it, and this audit confirms the fix rather than the defect.

Every table now prints the code path above the first number:

```
  provider        baseline  (rules-baseline-v1)
  code path       deterministic rules baseline (no model called)
  vignette set    main — 249 cases, 0 clinician-reviewed
```

`README.md` carries the caveat inside the same block as the figure, and a
section titled "What this repository has not shown" states in the first person
that the engine is unmeasured, that `$0.0000` and the latency figure are "the
cost and latency of calling no model at all", and that the $0.05 and 6-second
budgets are "**unmeasured, not met**". `PROGRESS.md` and
`docs/SAFETY_REVIEW.md` agree. I found no table anywhere in the repository that
presents a baseline figure without naming the provider.

**The refusal guard works.** With no key:

```
$ make eval-model
  Cannot evaluate the openai path: OPENAI_API_KEY is not set.
  Refusing to run rather than degrade.
exit 1
```

That is the right shape. A gate that reports numbers when it measured nothing
is worse than one that fails.

### Do the CI gates cover the model path?

Partly, and honestly labelled. `.github/workflows/ci.yml` parses (7 jobs:
`backend`, `eval`, `eval-integrity`, `eval-model`, `eval-model-full`, `web`,
`mobile`). `eval` and `eval-integrity` run free on every push. `eval-model`
exists, is key-gated, and emits a GitHub warning when no key is configured, so
silence is not mistaken for a pass.

So: **the gate that runs guards code the product does not run in production,
and the gate that would guard production has never executed.** That is stated
in the repository. It is still the single most important open item.

### Budgets

| Budget | Set in | Ever measured against a real provider? |
|---|---|---|
| < $0.05 per consultation | `config.py:58` | **No.** Reported `$0.0000` is the cost of calling nothing. |
| p95 < 6 s online | `config.py:60` | **No.** Reported 21 ms is the baseline's own arithmetic. |

Both are **unknown**, not met. The repository says so.

---

## 2. Is the evaluation an instrument or a mirror?

### 2.1 Overlap — reproduced exactly

```
$ make eval-overlap
    main
      texts containing a map surface   498 (100.0%)
      mean word coverage by surfaces   58.9%
      distinct texts / templates       92 / 26
      exact duplicate vignettes        157 (largest template group 25)
  Terminology surfaces never exercised: 637 of 811 (78.5%)
  Presentation classes separable by a single shared phrase:
    anemia   "yurganda nafas qisishi." in 83% of 24 cases, 0 elsewhere
    …8 of 11 classes
```

Every figure in `REMEDIATION.md` §2a reproduces to the digit. The "249
vignettes" are 26 templates; 8 of 11 presentation classes are identifiable by
one shared phrase; 78.5% of the vocabulary is never exercised.

The headline 97.6% is therefore a measurement of whether text this project
wrote matches a dictionary this project wrote — and the project now says so in
`README.md`. Classification of that number: **UNFALSIFIABLE**, and correctly
labelled.

One mechanism the overlap report does not mention, and which makes the
circularity tighter than 58.9% suggests: the baseline "model" never sees the
patient's sentence at all. It parses the *concepts* back out of the prompt:

```python
# backend/app/ai/providers/baseline.py:191, 219
_CONCEPTS_RE = re.compile(r"Recognised clinical concepts:\s*(.*)")
concepts_match = _CONCEPTS_RE.search(user)
```

and then adds `+4.0` to whichever ICD code the fired red flag maps to
(`baseline.py:242-245`). So on a case where a red flag fires, the "diagnosis"
is the rule's own conclusion read back. The 97.6% is one component — the
terminology map — being graded twice.

This also means the baseline is not a fair floor for the LLM to beat: the LLM
would receive the free text, the baseline never does.

### 2.2 The project's own out-of-vocabulary set — reproduced exactly

```
$ make eval-oov
  Top-3 (lenient)              31.0%
  Red-flag recall  [SAFETY]     4.5%  (1/22)
  Declined when it should      83.3%  (10/12)
```

### 2.3 The audit's own set — 44 vignettes, written independently

`audit/adversarial/vignettes_audit_oov.json`. Written without consulting
`knowledge/terminology.csv` or any file under `backend/app/ai/eval/data/`.
44 cases in Uzbek (Latin and Cyrillic) and Russian, covering dialect,
code-switching inside one sentence, dropped apostrophes, negation, symptom
denial, vague somatic complaint, event-based time ("Navro'zdan beri"),
third-party reporting, patient minimisation, and six cases where declining is
the correct answer. Then 14 red-flag evasion cases and 6 decoys.

Run through the project's own `run_suite` and `metrics.compute`, unchanged:

```
$ cd backend && PYTHONPATH=..:. ENVIRONMENT=test \
    DATABASE_URL="sqlite+pysqlite:///:memory:" python ../audit/adversarial/run_audit_set.py

  Top-3 (lenient)                   37.5%
  Red-flag recall  [SAFETY]         32.7%  (17/52)
  Decoys that wrongly fired         25.0%  (3/12)
  Declined when it should  [SAFETY] 70.0%  (7/10)
```

| set | top-3 | red-flag recall | decoy false positives |
|---|---|---|---|
| project main (in-vocabulary) | 97.6% | 100.0% (158/158) | — |
| project out-of-vocabulary | 31.0% | 4.5% (1/22) | — |
| project adversarial | 25.0% | 31.6% (12/38) | 2.6% (1/38) |
| **this audit's set** | **37.5%** | **32.7% (17/52)** | **25.0% (3/12)** |

The gap between column 1 and every other column is the finding, and it is one
the project has already published. What this set adds is the *shape* of the
surviving third.

### 2.4 The finding: only rules that read numbers survive paraphrase

Splitting the audit set's red-flag cases by whether an abnormal vital sign
backs them:

| | caught |
|---|---|
| backed by an abnormal vital sign | 14/38 — 36.8% |
| **text only** | **0/10 — 0.0%** |

Zero. Not one danger described only in words fired a rule. The cause is
structural, not lexical:

```
$ grep -rn "free_text" backend/app knowledge ml --include=*.py
backend/app/ai/red_flags.py:94:    free_text: str = ""
backend/app/ai/engine.py:213:                free_text=case.chief_complaint,
```

The field is declared, populated, and **read by nothing**. Every one of the 17
rules is a predicate over `facts.concepts` and vital-sign numbers. The safety
layer never sees the sentence.

Concept extraction on the dangers that were missed:

```
ACS radiating to the left shoulder        -> []
stroke, facial droop + slurred speech     -> []
child choking, going blue, silent         -> ['cough']
haematemesis, "qon aralash qusdim"        -> ['vomiting']
melena, "najasim qora, qatron kabi"       -> ['dizziness']
haemoptysis, "dastro'molda qon dog'lari"  -> ['rash']
"Ko'kragim og'ir"                         -> []
"Ko'kragim og'ir, sovuq ter bosdi, nafasim qisyapti" -> ['sweating', 'dyspnea']
```

Blood coughed onto a handkerchief is classified as a rash. And the last line
matters most: the associated features of an acute coronary syndrome are
recognised, but `chest_pain` is not, so the rule — which needs
`chest_pain AND (dyspnea|sweating|syncope)` — cannot fire however alarming the
sentence is.

**Consequence for the roadmap.** Adding synonyms raises the in-vocabulary score
and moves the text-only number from 0/10 to some other number that measures the
same thing. The fix has to put a reader of free text into the safety path.

### 2.5 Negation inverts the rules

```
"suvsizlanish belgilari yo'q"  (no signs of dehydration) -> ['diarrhea', 'dehydration']
"balg'amda qon yo'q"           (no blood in the sputum)  -> [..., 'hemoptysis']
"talvasa bo'lmadi"             (there was no seizure)    -> ['fever', 'febrile_seizure']
"Ich ketishi yo'q"             (no diarrhoea)            -> ['diarrhea', 'vomiting']
```

Three forbidden red flags fired on the audit's decoys, all Uzbek:

```
aud-dec-002[uz]  ['imci_danger_sign', 'pediatric_dehydration']
aud-dec-003[uz]  ['hemoptysis']
aud-dec-006[uz]  ['imci_danger_sign']
```

The project's decoy false-positive rate is 2.6%; on decoys that use negation it
is 25.0%. The project's decoy set does not test negation, which is why the
number looked good.

The identical Russian sentences return `[]`, so the two arms fail in opposite
directions — Uzbek over-fires on denial, Russian under-fires entirely. The
"Language gap +0.0 pp" on the main set is an artefact of parallel translation of
26 templates, not evidence of parity.

### 2.6 Prompt injection

Reproduced: 20/20 schema held, 20/20 red flags held on the baseline. The
project already writes this up as a weak result, and it is right to: a lookup
table has no instructions to override. Injection remains **untested on the only
path that can be injected**. Nothing in this audit changes that; it needs a key.

---

## 3. Calibration

Main set, this run:

```
  Calibration error (ECE)   0.288      Mean top confidence  0.672
    0.0-0.2   n=12   mean conf 0.00   observed   0.0%
    0.4-0.6   n=102  mean conf 0.52   observed  92.2%
    0.6-0.8   n=320  mean conf 0.71   observed 100.0%
    0.8-1.0   n=64   mean conf 0.85   observed 100.0%
    monotone: yes
```

Monotone on the main set, and the project reports that out-of-vocabulary it
**inverts**. So the score is ordered only where the vocabulary matches, which is
where it is least needed.

`REMEDIATION.md` reports ECE 0.279 and mean confidence 0.680; this run gives
0.288 and 0.672 from the same command at the same commit. Small, but it means
one of the two was taken from a different state of the tree. Not worth a
finding; worth not quoting the third decimal.

Two decisions in the remediation were checked and are right:

- **No calibration was fitted.** Fitting on 26 templates would produce a number
  that looks like a probability and is tuned to this project's own prose.
- **The clinician UI no longer shows a percentage.** Verified in the Flutter
  test run: `confidence is not shown as a probability › a differential shows a
  match band, never a percentage` passes. The `confidence` field survives in the
  JSON contract, which is correct — it is the model's own claim.

The `min_confidence_to_rank = 0.4` threshold is doing real work: 2.4% of main
cases and 58.3% of out-of-vocabulary cases decline rather than rank. Declining
is the safe failure and the system does it more as it understands less. That is
the single most reassuring behaviour in the evaluation.

---

## 4. Reproduction

| command | result |
|---|---|
| `make test` | 438 passed, 52.9 s |
| `make eval` | 97.6% / 100.0% / 0.0% FR, ECE 0.288 |
| `make eval-gate` | exit 0 |
| `make eval-oov` | 31.0% / 4.5% |
| `make eval-adversarial` | 25.0% / 31.6% caught / 2.6% decoys |
| `--set injection` | 20/20, 20/20 |
| `make eval-overlap` | 58.9% / 26 templates / 637 of 811 |
| `ml.evaluate_risk` | reproduces — but not by the documented command (AUD-008) |
| `run_audit_set.py` | 37.5% / 32.7% / 25.0% decoys / 0 of 10 text-only |
| `cd mobile && flutter analyze && flutter test` | clean, 53 passed |
| `cd web && npm run typecheck && npm run build` | clean, builds |
| `docker compose -f infra/docker-compose.yml up --build` | **not verified** — pip inside the build container cannot verify TLS to pypi.org in this audit environment. A control `FROM python:3.11-slim` + `pip install requests` fails identically, so this is my sandbox's proxy CA, not the repository. |
