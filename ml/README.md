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
