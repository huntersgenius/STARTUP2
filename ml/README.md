# ml/

Risk scoring and, later, model fine-tuning.

## What is here now

`risk_scoring.py` — a deterministic, interpretable risk model.

## Why not XGBoost yet

The business plan specifies XGBoost or LightGBM for patient risk
stratification, and that is the right destination. It is not the right
starting point, for one reason: **we have no training data.** There are no
labelled Uzbek primary care outcomes to fit on, and a gradient-boosted model
fitted to synthetic vignettes would learn the vignette generator, not
medicine — while looking far more authoritative than the rules it replaced.

So the first risk model is a points-based score built from published risk
factors in the protocols under `knowledge/corpus`. It has three properties a
trained model would not have today:

- **It is auditable.** Every point it assigns names the finding that earned it,
  so a clinician can disagree with the reasoning rather than only the number,
  and a regulator can read the whole model in one sitting.
- **It cannot overfit data we do not have.**
- **It is a baseline the eventual XGBoost model must beat**, measured on the
  same evaluation set.

## Where every threshold comes from

Each numeric threshold cites the protocol it is taken from, in the code and
here. The *relative weights* are a different matter and are labelled as such:
no published instrument scores this particular mix of findings, so their
ordering is a clinical judgement to be reviewed, not a fitted parameter. A
weight with an invented citation would be worse than one that admits what it is.

| Threshold | Source |
|---|---|
| SpO2 < 90 / < 94 | UzMoH pneumonia protocol, CRB-65 section — `knowledge/corpus/uz-moh-pneumonia-protocol.md` ("SpO2 92% dan past bo'lsa … shoshilinch yo'naltiring") |
| Systolic < 90 | qSOFA / CRB-65 hypotension criterion, same protocol |
| Systolic ≥ 140 / ≥ 180 | WHO hypertension guideline 2021 — `knowledge/corpus/who-hypertension-primary-care.md` |
| Respiratory rate ≥ 30 (adult) | CRB-65, UzMoH pneumonia protocol |
| Respiratory rate ≥ 50 (2–11 mo) / ≥ 40 (1–5 y) | WHO IMCI fast-breathing bands |
| Glucose ≥ 20 / < 3.0 | UzMoH diabetes protocol, urgent-referral section — `knowledge/corpus/uz-moh-diabetes-t2.md` |
| Glucose ≥ 11.1 | WHO/IDF random plasma glucose diagnostic threshold, same protocol |
| Temperature ≥ 40 / < 35 | Sepsis-3 supporting criteria (extremes only) |
| Age ≥ 65 | CRB-65 |
| Age ≥ 80 | **No source** — a judgement that the very old deserve a further step |
| Age < 1 / < 5 | WHO IMCI treats under-5s as a distinct risk group |
| Band cut-points (15 / 35 / 60) | **No source** — chosen so any single immediate-danger finding reaches `very_high` and chronic factors alone cannot |
| Red-flag floor (70) | **No source** — a design constraint, so the score cannot contradict a fired rule |

## Operating point, and what it measures

The scorer is deliberately tuned to **avoid missing a high-risk patient**, at
the cost of flagging low-risk ones. The two errors are not symmetric in a rural
clinic: a missed deterioration can be fatal, while an unnecessary "high" band
costs a clinician's attention — and note that referral is decided by the
red-flag rules and the clinician, not by this band, so a false "high" does not
by itself send anyone travelling.

Measured by `python -m ml.evaluate_risk`. Ground truth is "the vignette carries
a must-not-miss red flag"; a positive prediction is band `high` or `very_high`.

| set | n | sensitivity | specificity |
|---|---|---|---|
| in-vocabulary (main) | 249 | 100.0% | 97.3% |
| **out-of-vocabulary** | 42 | **20.0%** | 90.6% |
| adversarial | 38 | 42.1% | 94.7% |

**All labels are synthetic and reviewed by no clinician.** The out-of-vocabulary
row is the one to read: the scorer consumes concepts from the terminology map,
and on wording outside that map most concepts are never recognised, so the
score has almost nothing to work with. 100% sensitivity is what this design
achieves when it recognises the words; 20% is what it achieves when it does not.
That gap is a property of the terminology map, not of the scoring weights, and
adding synonyms would move the number without fixing the fragility.

## When to replace it

Once the pilot has produced roughly 2,000 consultations with recorded outcomes
(referral made, diagnosis confirmed, patient deteriorated), refit as a proper
model and compare against this baseline in `app/ai/eval/ab.py`. Until the
trained model wins on the eval set *and* keeps red-flag recall at 100%, it does
not ship.

## Why this is not left to the LLM

Before this module, `risk.score` came from whatever number the model wrote in
its JSON. That is exactly the kind of value an LLM should not be inventing:
it looks quantitative, it is not calibrated against anything, and a clinician
reading "risk 0.7" reasonably assumes something computed it. Now something did.
