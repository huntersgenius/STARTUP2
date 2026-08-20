# Evaluation integrity

**What the headline number means, and what it does not.**

Every figure in this document was produced by a command in this repository and
can be reproduced by running it. Every vignette in every set is **synthetic**
and has been reviewed by **no clinician**.

```bash
make eval-all        # every set, side by side
make eval-overlap    # the vocabulary measurement below
cd backend && python -m ml.evaluate_risk
```

---

## 1. The short version

| | in-vocabulary | out-of-vocabulary | change |
|---|---|---|---|
| Top-3 agreement | 97.6% | **31.0%** | −66.6 pp |
| Top-1 agreement | 94.4% | 23.8% | −70.6 pp |
| **Red-flag recall** | 100.0% | **4.5%** | **−95.5 pp** |
| Risk scorer sensitivity | 100.0% | **20.0%** | −80.0 pp |

Both columns are the same code on the same day. The only difference is who
chose the words.

**The 97.6% is not a measure of clinical ability. It is very largely a measure
of whether text written by this project matches a dictionary written by this
project.** The 31.0% is the more honest estimate, and it is still an
over-estimate, because the out-of-vocabulary set was also written here — by
someone who knew exactly which words to avoid, which is not the same as a
stranger's speech.

The red-flag number is the one to worry about. 100% → 4.5% means that of 22
dangers described in words the rule table does not contain, **21 were missed**.

---

## 2. Why the in-vocabulary number is high

Measured by `python -m app.ai.eval.overlap`:

| Finding | Value |
|---|---|
| Main-set vignette texts containing a terminology surface | 498 / 498 (100%) |
| Mean share of each vignette's words that *are* terminology surfaces | **58.9%** |
| Distinct templates behind the "249 vignettes" | **26** |
| Vignettes that are exact duplicates of another vignette | **157** |
| Largest single template group | 25 cases |
| Terminology surfaces never exercised by any vignette | **637 of 811 (78.5%)** |
| Presentation classes identifiable by one shared phrase | **8 of 11** |

Three of these deserve to be read twice.

**58.9% word overlap.** On average, more than half of every main-set vignette
consists of strings that are already keys in the terminology map. The system is
being asked to recognise its own dictionary.

**26 templates, not 249 vignettes.** 157 of the 249 are exact duplicates of
another entry; the largest group is one sentence repeated 25 times with
different numbers. So the set contains roughly **26 clinical scenarios**, and
per-class percentages are correspondingly coarse: getting one template right
scores up to 25 cases correct, and getting one wrong loses all of them at once.
`respiratory_infection` scoring "83.3% of n=72" is really *four of five
templates correct*, and the 12 failures are twelve copies of a single sentence.

**8 of 11 classes separable by one phrase.** For example every
`musculoskeletal_pain` vignette and no other contains "kuchayadi, dam olganda";
every `cardiovascular_risk` vignette and no other contains "vazn, sho'r ovqat,".
A class that can be identified by a single literal string is not testing a
diagnostic engine. **Those classes' 100.0% scores should be read as
meaningless, not as perfect.**

---

## 3. The out-of-vocabulary set

`backend/app/ai/eval/data/vignettes_oov.json` — 42 vignettes, all distinct, no
templates. Written deliberately against the map:

- regional and dialect words (`qadaldi`, `sanchadi`, `toshdek`, `ensam tortishadi`)
- uz/ru code-switching inside one sentence, as Tashkent actually speaks
- misspellings a tired feldsher makes (`kokragim ogriydi`, `gemaglabin`)
- negation and symptom denial (`ich ketishi yo'q, faqat qusish`)
- vague somatic complaint (`ichim yomon`, `holim yo'q`)
- time expressed as events (`Navro'zdan beri`, `Ramazondan buyon`)
- a relative reporting for a patient who never speaks
- patients who understate (`unchalik emas, ozgina ko'kragim siqilgandek`)
- six cases where the correct answer is **decline and ask**, not a diagnosis

Its overlap statistics confirm it does what it claims: 11.9% mean word coverage
against the main set's 58.9%, and 0.85 recognised concepts per text against
3.54. A regression test (`test_out_of_vocabulary_set_is_actually_out_of_vocabulary`)
fails if anyone "improves" the OOV score by adding its phrases to the map,
which would delete the measurement rather than fix the system.

One genuinely good result: **the system declined on 10 of the 12 cases where
declining was correct (83.3%)**. Faced with `ichim yomon`, it asks questions
instead of inventing a differential. That is the behaviour the design intended.

---

## 4. Adversarial red flags

`vignettes_adversarial.json` — every one of the 19 red-flag codes probed from
both directions.

| | result |
|---|---|
| Danger present, described in words the rule does not contain | **31.6% caught (12/38)** |
| Rule's trigger words present, no danger | 2.6% wrongly fired (1/38) |

**26 of 38 dangers were missed.** Confirmed misses include acute coronary
syndrome ("to'sh suyagim ortida tosh bosgandek og'irlik" — crushing retrosternal
heaviness), airway compromise, and stroke. The false-positive rate is genuinely
low, which is worth something, but it is the cheap half of the problem: a rule
table that only matches its own words will rarely fire wrongly.

**`158/158` on the main set is recall on text written in the rules' own
vocabulary.** `12/38` is recall when the words change. Neither is recall on a
real patient; the first is an over-estimate and the second is closer.

---

## 5. Confidence is not a probability

Reliability, main set (`make eval` prints this):

| confidence bucket | n | mean stated | observed correct |
|---|---|---|---|
| 0.0 – 0.2 | 12 | 0.00 | 0.0% |
| 0.4 – 0.6 | 102 | 0.52 | 92.2% |
| 0.6 – 0.8 | 320 | 0.71 | 100.0% |
| 0.8 – 1.0 | 64 | 0.85 | 100.0% |

Monotone, but badly calibrated: ECE **0.279**, and the system says 0.71 about
things it gets right 100% of the time. On the main set the miscalibration is in
the safe direction.

Out-of-vocabulary, the same table inverts:

| confidence bucket | n | mean stated | observed correct |
|---|---|---|---|
| 0.4 – 0.6 | 9 | 0.48 | 77.8% |
| 0.6 – 0.8 | 18 | 0.69 | 66.7% |
| 0.8 – 1.0 | 8 | 0.85 | **62.5%** |

**On text outside the map, a higher score was *less* often correct.** The
buckets are small (9, 18, 8) so this is suggestive rather than conclusive, and
the automated monotonicity check does not flag it for exactly that reason — it
requires n ≥ 20 and a drop over 5 points before calling a violation, so that
sampling noise is not reported as a defect. But the direction is the wrong one
and it is not something to wait for more data before acting on.

**What we did about it.** The clinician UI no longer displays a percentage. It
shows a three-level band — *kuchli / o'rtacha / zaif moslik* (strong / moderate
/ weak match) — with the explanatory line "how well the findings match the
protocol; this is not a probability". A widget test asserts no `%` appears
anywhere in a differential card.

**What we deliberately did not do.** We did not fit a temperature or an
isotonic calibration. Fitting on these vignettes would produce a number that
looks like a probability, was tuned on 26 templates, and would be wrong in the
field in a way nobody could see. Calibration is worth doing on real
consultations with recorded outcomes, and not before.

The 0.4 `insufficient_data` threshold is unchanged and is doing real work: it
is why the out-of-vocabulary set declines correctly 83.3% of the time.

---

## 6. The risk scorer at its operating point

`python -m ml.evaluate_risk`. Ground truth: the vignette carries a
must-not-miss red flag. Positive prediction: band `high` or `very_high`.

| set | n | sensitivity | specificity |
|---|---|---|---|
| main | 249 | 100.0% | 97.3% |
| **out-of-vocabulary** | 42 | **20.0%** | 90.6% |
| adversarial | 38 | 42.1% | 94.7% |

The scorer is built to avoid missing a high-risk patient. It achieves that only
when the input vocabulary is one it recognises — which is the same finding as
everywhere else in this document, because the scorer consumes concepts from the
same terminology map.

---

## 7. Which code path produced these numbers

**All of the above is the deterministic rules baseline. The eight-stage
diagnostic engine — the product — has never been evaluated.**

Every result table in this repository now names its provider and code path in
its header. `--provider openai` refuses to run without a key rather than
falling back to the rules layer and printing a table that reads as a model
evaluation. (It did exactly that on the first attempt, which is why the guard
exists and has a test.)

To measure the real path:

```bash
export OPENAI_API_KEY=...
make eval-model                  # full set, both languages, HTML report
make eval-model PROVIDER=anthropic
```

Until that has been run, the following are **unmeasured**, not "met":

- the $0.05 per-consultation cost ceiling
- the 6-second p95 online latency budget
- top-3 accuracy and red-flag recall on the engine
- whether the LLM path beats this rules baseline at all

The baseline's reported cost is `$0.0000` and its p95 is 19 ms because no model
was called. Those two figures should never be quoted as evidence that the
budgets are met.

---

## 8. What would make these numbers trustworthy

In the order that would move them most:

1. **A licensed Uzbek GP reviews and rewrites the vignette set**, and the
   template duplication is removed so that 249 vignettes are 249 scenarios.
2. **The model path is measured**, and the LLM-versus-baseline question is
   answered rather than assumed.
3. **Vignettes written by someone outside this project** — ideally transcribed
   from real consultations under consent — replace the synthetic set entirely.
4. **The terminology map stops being load-bearing for safety.** 4.5% red-flag
   recall on unfamiliar wording is not a coverage gap to be filled with more
   synonyms; it is an argument that deterministic keyword rules cannot be the
   only safety net.
