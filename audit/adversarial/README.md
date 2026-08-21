# Reproducing the audit

Everything numeric in `audit/` comes out of one of the three commands below.
All of them run offline, with no API key, against the project's own code paths.

```bash
cd backend

# 1. The audit's own out-of-vocabulary set: 44 vignettes written without
#    reference to knowledge/terminology.csv. Produces the 0-of-10 text-only
#    red-flag result and the negation false positives.
PYTHONPATH=..:. ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///:memory:" \
  python ../audit/adversarial/run_audit_set.py

# 2. Behavioural probes. test_probe_* pass and print what they observed;
#    test_defect_* fail on purpose — each reproduces a finding.
PYTHONPATH=.. ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///:memory:" \
  python -m pytest ../audit/adversarial/test_audit_probes.py -v -s

# 3. The P0. Two failing tests, left in the project's own suite so `make test`
#    reports them until the defect is fixed.
PYTHONPATH=.. ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///:memory:" \
  python -m pytest tests/test_audit_p0.py -v
```

`make test` therefore reports **438 passed, 2 failed** rather than 438 passed.
That is not a regression: the two failures are `tests/test_audit_p0.py`,
reproducing AUD-001. Delete them together with the fix, not before.

## Files

| File | What it is |
|---|---|
| `vignettes_audit_oov.json` | 44 vignettes. Group A: how people actually speak. Group B: red-flag evasion, half backed by an abnormal vital sign and half text-only, so the run separates rules that key on numbers from rules that key on words. Group C: decoys, mostly negation. |
| `run_audit_set.py` | Runs them through `app.ai.eval.runner.run_suite` and `app.ai.eval.metrics` unchanged. Only the vignette file differs from `make eval`. |
| `test_audit_probes.py` | The controlled-substance, audit-trigger and sync-tenancy findings, plus passing probes for red-flag survival under model failure and the paediatric block. |
| `conftest.py` | Loads `backend/tests/conftest.py` as a plugin, so the audit uses the project's fixtures rather than a second harness. |
| `audit_oov_results.json` | Output of `run_audit_set.py`, committed so the numbers in the reports can be checked without re-running. |

## Provenance of the vignettes

Written on 2026-08-21 for this audit, without consulting
`knowledge/terminology.csv` or anything under `backend/app/ai/eval/data/`.
Ground truths are restricted to presentations that are unambiguous at
primary-care level; anything needing clinical judgement beyond that is marked
`expect_insufficient_data` rather than given an answer.

**These are synthetic and no clinician has reviewed them.** They are evidence
about whether the *mechanism* can see a danger sign described in ordinary
words. They are not a clinical benchmark and no accuracy claim should rest on
them.
