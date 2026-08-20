# Remediation pass — 2026-08-20

What the brief asked for, what I found, what I changed, what I deliberately did
not change, and what remains open.

Every figure here is reproducible by a command in this repository. Commands and
their real output are in [§7](#7-verification).

---

## Summary of what changed

| | before | after | why |
|---|---|---|---|
| Headline number's provenance | "offline rules baseline" in a caption | provider, model, code path and corpus printed above every table | the caption was true but the reader could still quote 97.6% as the product |
| Out-of-vocabulary accuracy | not measured | **31.0% top-3, 4.5% red-flag recall** | the honest estimate |
| Vignette/vocabulary overlap | not measured | **58.9% word overlap, 26 templates, 8/11 classes phrase-separable** | explains the 97.6% |
| Adversarial red flags | not measured | **31.6% caught when paraphrased** | `158/158` was recall on rule-shaped text |
| Prompt injection | not tested | 20/20 on baseline; model path wired, key-blocked | |
| False-referral rate | 10.8%, unanalysed | **0.0%** after a real rule fix | rule contradicted its own cited protocol |
| Risk scorer | no sources, no operating point | every threshold sourced or marked unsourced; sens/spec published | |
| Confidence display | "62%" | three-level match band | ECE 0.279, inverts out-of-vocabulary |
| CI | believed passing | **had never run — invalid YAML since Sprint 1** | |
| Model-path gate | none | present, key-gated, `--fail-under-redflag 1.0` | |

---

## 1. The evaluation measures the wrong thing

**Confirmed, with one correction to the brief.** `run.py` does resolve
`--offline` to the baseline, and everything published came from it. The brief
says `README.md` and `PROGRESS.md` presented the number "without saying which
provider produced it" — not quite: both said "offline rules baseline" in the
line above the table. The real defect was subtler and worse. The caption named
the provider while the table below it listed `p95 latency 25 ms` and
`cost $0.0000` against the 6-second and $0.05 budgets, which reads as *the
budgets are met*. They are not met; nothing was measured. A reader would take
away a false conclusion from an individually true sentence.

**1a — report what was measured.** Every table now prints provider, model, code
path (`deterministic rules baseline (no model called)` vs `full eight-stage
engine, GPT-4o`), vignette set, case count and clinician-reviewed count *above*
the first number. The same block heads the HTML report. Latency and cost now
carry a footnote saying they describe calling no model.

**1b — evaluate the real path.** **No API key exists in this environment**, so
there are no model numbers and I did not estimate any. What exists instead:

- `make eval-model [PROVIDER=openai|anthropic]` — one documented command,
  complete except for the key.
- `--provider openai` **refuses to run** without a key and exits 1.

That guard is the most useful thing I built in this section, because I built the
bug first: my initial version ran `--provider openai` with no key, degraded
every case to the rules layer, and printed a complete results table headed
"openai". Only `Injection: schema held 0/2` hinted that nothing had been
measured. That is precisely the failure this whole task is about, reproduced
inside the fix for it. It now exits with an explanation, and
`test_model_path_refuses_to_run_without_a_key` keeps it that way.

**Does the LLM beat the baseline?** Unknown. I will not guess. But the shape of
the question is now clear and it is in `PROGRESS.md`: a rules table scoring
97.6% does not show the rules are good, it shows the set is easy. The real bar
for the LLM is **31.0% top-3 and 4.5% red-flag recall on out-of-vocabulary
text**. If it cannot beat that by a wide margin it is not earning its cost or
latency.

**1c — gate both paths.** CI now has `eval` (baseline, free, every push),
`eval-integrity` (overlap + OOV + adversarial + injection, every push),
`eval-model` (stratified subset per push, key-gated, `--fail-under-redflag 1.0`)
and `eval-model-full` (nightly, full set). The subset is deterministic: cases
sorted by id, first 2 non-safety cases per presentation class, **plus every case
carrying a must-not-miss red flag regardless of the cap** — the safety metric is
never sampled. When no key is configured the job emits a GitHub warning saying
the engine is unmeasured, so silence is never mistaken for a pass.

---

## 2. The vignettes and the rules share an author

**Confirmed, and worse than the brief supposed.**

**2a — overlap, `app/ai/eval/overlap.py`.** 100% of main-set texts contain a
terminology surface; **58.9% of the average vignette's words are surfaces**;
**637 of 811 surfaces (78.5%) are never exercised** by any vignette.

The finding I did not expect: **the "249 vignettes" are 26 distinct templates**,
157 of them exact duplicates, largest group 25. And **8 of 11 presentation
classes are identifiable by a single shared phrase** appearing in ≥80% of the
class and nowhere else. Those classes' 100.0% scores are not evidence of
anything.

This also dissolves the brief's §4 question about `respiratory_infection` at
83.3%: all 12 "failures" are twelve copies of one sentence, and the class score
is really *four of five templates*.

**2b — out-of-vocabulary set.** 42 vignettes, all distinct, written against the
map: dialect, code-switching, misspellings, negation, vague somatic complaint,
event-based time, third-party reporting, minimisation, and six cases where
declining is correct. Result: **31.0% top-3, 4.5% red-flag recall**. A test
fails if anyone raises that score by adding its phrases to the map.

One good result worth stating: it **declined correctly on 10 of 12** cases where
declining was right.

**2c — adversarial red flags.** 38 cases, both directions, every one of the 19
codes. **31.6% of paraphrased dangers caught; 2.6% of decoys wrongly fired.**
Missed: ACS, stroke, airway compromise, GI bleeding, described as patients
describe them.

**2d — prompt injection.** 10 cases. Baseline: 20/20 schema, 20/20 red flags —
which I have written up as a *weak* result, because a lookup table has no
instructions to override. The meaningful run needs the model path.

---

## 3. Confidence is not a probability

Reliability tables are in `docs/EVAL_INTEGRITY.md` §5. Main set: monotone but
ECE 0.279. Out-of-vocabulary: **inverts** — 62.5% correct at stated 0.8–1.0
against 77.8% at 0.4–0.6, on buckets of 8 and 9.

I took the brief's second option. **The clinician UI no longer shows a
percentage**; it shows *kuchli / o'rtacha / zaif moslik* (strong / moderate /
weak match) with the line "how well the findings match the protocol; this is not
a probability". A widget test asserts no `%` appears in a differential card.

I did **not** fit a calibration. Fitting on 26 templates produces a number that
looks like a probability, is tuned to this project's own writing, and would be
wrong in the field invisibly.

The automated monotonicity check requires n ≥ 20 and a drop over 5 points before
calling a violation, so sampling noise is not reported as a defect. Every bucket
prints with its n so a reader can apply their own judgement — I flag this
explicitly because the threshold could otherwise look like tuning to pass.

The 0.4 `insufficient_data` threshold is unchanged and is doing real work.

---

## 4. Results the eval flagged and nobody looked at

**`respiratory_infection` 83.3%.** Investigated case by case. All 12 failures
are the same template ×6 ×2 languages, and the system **declines** on it rather
than answering wrongly — the safe failure. **No TB is confused with a benign
respiratory infection anywhere in the main set**, checked in both directions.
So: not a safety finding, but the class score is an artefact of duplication.

**False referrals 10.8%.** Characterised: **100% attributable to one rule.**
`severe_anemia` required `anemia|pallor` + `dyspnea`, and matched *exertional*
breathlessness — while the WHO guidance shipped in this repository lists
exertional breathlessness as an ordinary detection sign and reserves referral
for breathlessness **at rest**. The rule contradicted its own cited source and
fired on all 40 mild iron-deficiency cases. Fixed with a `dyspnea_at_rest`
concept: **10.8% → 0.0%**, red-flag recall unchanged at 100%.

This required changing one existing test, which asserted the defective
behaviour. Per the ground rules I am flagging it: `test_severe_anemia_fires_
with_breathlessness` was replaced by two tests covering both directions. It is
the only pre-existing test modified in this pass.

**The 100.0% cells.** Eight of eleven are trivially separable by one phrase.
Marked as such in `docs/EVAL_INTEGRITY.md` and surfaced by `make eval-overlap`.

---

## 5. The risk scorer

Every threshold now cites its protocol in the code and in `ml/README.md`.
Thresholds without a published source — the 80-year age step, the band
cut-points, the red-flag floor — are **labelled "no source"** rather than given
a plausible-looking citation. The relative weights are labelled a clinical
judgement for review, not a fitted parameter.

Operating point stated: tuned to avoid missing high-risk patients. Measured by
`python -m ml.evaluate_risk`:

| set | n | sensitivity | specificity |
|---|---|---|---|
| main | 249 | 100.0% | 97.3% |
| out-of-vocabulary | 42 | **20.0%** | 90.6% |
| adversarial | 38 | 42.1% | 94.7% |

---

## 6. Reporting integrity sweep

- `README.md`: results table replaced with a two-column in-vocabulary /
  out-of-vocabulary table carrying provider, corpus and caveat **inside the same
  block**; new **"What this repository has not shown"** section.
- `PROGRESS.md`: Sprint 5 table corrected in place, marked as corrected, with
  the caveat adjacent rather than 30 lines below; footnotes on latency and cost
  saying they measure calling no model.
- "Accuracy" is now written as **"agreement with our own answer key"** in the
  headline tables.
- Uses of "verified" were audited: all describe engineering facts that were
  verified (migrations up/down, Flutter tests, npm build, backup restores). The
  one genuinely false claim was "all four CI jobs pass" — see below — and it is
  corrected.
- Cross-file consistency checked: 97.6 / 31.0 / 4.5 / 100 / 0.0 / 26 / 58.9 /
  637 / 811 agree across `README.md`, `PROGRESS.md`, `docs/EVAL_INTEGRITY.md`,
  `docs/SAFETY_REVIEW.md` and `ml/README.md`.

**Found during the sweep: CI has never run.** `.github/workflows/ci.yml`
contained `DATABASE_URL: sqlite+pysqlite:///:memory:` — a plain scalar ending in
a colon, which YAML rejects. GitHub would have refused the file since Sprint 1.
Every previous "CI passes" statement meant *I had run the steps by hand in a
clean clone*, which is true but is not the same claim. Fixed, and
`test_ci_workflow_is_valid_yaml` now parses the workflow in the normal suite.

---

## 7. Verification

See the session transcript for full output. Summary of the real runs:

```
make test                     438 passed
make eval-all                 table below, written to results/2026-08-20-baseline-all.json
make eval-overlap             overlap.json
python -m ml.evaluate_risk    risk_operating_point.json
python -m app.ai.eval.run --provider openai      exits 1: "OPENAI_API_KEY is not set"
cd mobile && flutter analyze && flutter test     No issues found; All tests passed (53)
cd web && npm run typecheck && npm run build     clean
```

```
  set                       cases    top-3    top-1   red-flag  declined
  in-vocabulary (main)        498    97.6%    94.4%     100.0%         —
  out-of-vocabulary            84    31.0%    23.8%       4.5%     83.3%
  adversarial red flags        76    25.0%    21.1%      31.6%         —
  prompt injection             20   100.0%   100.0%     100.0%         —
```

CI jobs: `backend`, `eval`, `eval-integrity`, `eval-model` (key-gated),
`eval-model-full` (nightly), `web`, `mobile`. The workflow parses for the first
time. The model gate is present and **documented as key-blocked**, not passing.

---

## What I deliberately did not do

- **Did not add the out-of-vocabulary phrases to the terminology map.** It would
  have raised the OOV score to near the main score and changed nothing about the
  system. A test now fails if someone does.
- **Did not fit a calibration** on synthetic data.
- **Did not put an accuracy floor on the OOV or adversarial gates.** Those sets
  exist to be reported, not passed. Gating them would create pressure to game
  them. The red-flag floor still gates injection and the model path.
- **Did not estimate model-path numbers.**
- **Did not rename the schema field `confidence`.** The brief offered
  `match_strength`. The field is the *model's own claim* in a JSON contract the
  prompt asks for, and renaming it would misdescribe what the model returned.
  The honest fix belongs at the display layer, where a clinician reads it, and
  that is where I made it. I flag this as the one place I chose differently from
  the brief.
- **Did not delete the duplicated vignettes.** Deduplicating would drop 249 to
  92 and change every historical number, obscuring the comparison this document
  depends on. The duplication is now measured and published; removing it is the
  first task for whoever rebuilds the set with an advisor.

---

## What remains open

1. **The engine is unmeasured.** One command, blocked on a key.
2. **Red-flag recall is 4.5% on unfamiliar wording.** Not a coverage gap to fill
   with synonyms — an argument that keyword rules cannot be the only safety net.
   Proposed direction in `docs/SAFETY_REVIEW.md` S1.
3. **No clinician has reviewed anything.**
4. **The vignette set needs rebuilding**: 26 templates, 8 phrase-separable
   classes.
5. **Injection is untested on the path that can actually be injected.**
6. **CI has never executed.** The file parses now; the first real run will be
   the first ever.
