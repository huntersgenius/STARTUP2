# Adversarial safety review — 2026-08-19

Conducted after Sprint 6, against the five questions in the build prompt pack,
as a hostile senior engineer and a medical safety reviewer.

Five defects found. All five are fixed, and each has a regression test that
names the defect so it is not deleted in a later refactor.

---

## 1. Can patient PII reach a third-party API?

**Finding — confirmed defect.** `DiagnosticEngine.build_prompt` interpolated
`case.chronic_flags` directly from the patient row, while every other field
came from the de-identified payload. Chronic flags are free text a clinician
types, so a note like `diabet (onasi Zulfiya Ismoilova ham kasal)` would have
been sent verbatim to OpenAI or Anthropic.

The red-team suite did not catch it because it tests `deidentify` in isolation,
not what `build_prompt` actually assembles.

*Fix:* `app/ai/engine.py` reads chronic flags from `scrubbed`.
*Test:* `tests/test_safety_review.py::test_chronic_flags_are_scrubbed_before_reaching_the_prompt`
asserts on the assembled prompt string, not on the scrubber.

**Also verified clean:** `deidentify` is the single chokepoint before every
outbound call; no module outside `app/ai/providers/` imports a vendor SDK;
`assert_no_pii` runs on the exact object about to be serialised; Sentry has a
`before_send` hook that strips identifiers by key and by pattern and never
sends request bodies.

---

## 2. Can the app lose data on network failure?

**Finding — confirmed defect, the most serious of the five.** A clinician's
accept / edit / reject decision on an **offline** suggestion was silently
discarded. `ConsultationScreen._decide` only recorded a decision when
`_storedSuggestion` was set, and that is only set when the *server* returned a
suggestion. In airplane mode the suggestion came from `OfflineEngine`, so:

- the UI showed "done",
- nothing was written to the device,
- the consultation later reached the server with **no evidence that a clinician
  had ever reviewed the output**.

That breaks the offline-first guarantee and the clinician-in-the-loop
guarantee at the same time, and it breaks them precisely in the setting the
product exists for — a rural clinic with no signal.

*Fix:* three parts.
- The device now persists an offline suggestion as a `LocalSuggestion` row
  (`model: 'offline-rules'`, `degraded: true`) before showing it, so the
  decision has something to attach to.
- `recordDecision` queues an `offline_assessment` outbox operation carrying the
  suggestion, the red flags the clinician actually saw, and the decision.
- The server accepts `offline_assessment` in `POST /sync`, creating the
  `AiSuggestion` + `ClinicianDecision` pair and an `ai.offline_decision` audit
  row, labelled honestly as a device rule output rather than a model one.

*Tests:* the airplane-mode widget test now asserts the decision is on disk and
queued; `tests/test_sync.py::test_offline_decision_is_not_lost` covers the
server side, with rejection cases for an unknown consultation and a bad action.

**Also verified clean:** the outbox row and its data are written in one
transaction; an outbox row is deleted only after the server confirms it; a
transient failure backs off and never deletes; a rejected operation is kept and
surfaced rather than dropped.

---

## 3. Does any AI output reach the clinician without the accept/edit/reject gate?

**Finding — confirmed defect.** `POST /suggestions/{id}/decision` refuses a
nurse, but the sync path did not. A nurse's tablet could therefore close the
clinical gate simply by having been offline when the decision was made. A rule
that depends on connectivity is not a rule.

*Fix:* `_apply_offline_assessment` applies the same `PRESCRIBING_ROLES` check.
*Test:* `tests/test_sync.py::test_a_nurse_cannot_close_the_clinical_gate_by_syncing`.

**Also verified clean:** `/analyze` always returns `requires_clinician_review`
and the localised disclaimer; the response carries an ASCII disclaimer header
that the Flutter client *refuses the response without*; suggestions with no
decision are reported as `undecided` on the dashboard; the suggestion view
renders red flags above any differential, asserted by widget test.

---

## 4. Does any red-flag rule depend on the LLM behaving correctly?

**No defect.** Rules are pure functions of the normalised case, evaluated
before any model call, and merged into the response after it.
`tests/test_red_flags.py::test_rules_do_not_depend_on_any_model` reads
`red_flags.py` and asserts it contains no reference to a provider, the router
or the engine. The all-providers-down test asserts the referral banner still
appears. The device mirrors the rules locally, and a test asserts every device
rule code exists in the server table.

One structural weakness was found and fixed during Sprint 5 rather than here:
longest-match retrieval yields `pediatric_diarrhea` and never plain `diarrhea`,
so a rule written against the general concept silently failed in Uzbek while
passing in Russian. Rules now expand specialised concepts via `CONCEPT_IMPLIES`.

---

## 5. Is any test asserting something trivially true?

**No defect found, one weakness noted.** An AST scan for assertion-free tests
returned five in the red-team suite; all five call `assert_no_pii`, which
raises. That helper is itself proven to work by
`test_assert_no_pii_actually_catches_a_leak`, which fails if the detector
becomes a no-op — the mutation test that makes the other five meaningful.

Noted weakness, not fixed: the evaluation set is written by the same team that
wrote the system, so 97.6% top-3 measures internal consistency. Advisor-reviewed
vignettes are the fix, and that is open question #1 in `docs/PLAN.md`.

---

## Findings not fixed

**Audit metadata carried the full raw model output.** The engine trace included
the model's complete response, and the API writes that trace into
`AuditLog.metadata_json`, which is exported to the regulator as CSV. It was not
a leak — the input was de-identified — but it bloated every audit row with
model prose. Now the trace carries `response_chars` and the output stays in the
column built for it, `AiSuggestion.raw_output`. Regression test asserts audit
metadata stays under 4 KB.

*(Listed here rather than above because it is a hygiene defect, not a safety
one — but it would have made the sandbox export unreadable.)*
