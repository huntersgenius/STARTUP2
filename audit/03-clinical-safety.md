# Clinical safety

Workstreams 3 and 4. Audited as a clinician would read it, not as an engineer.

---

## 1. The clinician-in-the-loop gate — every path enumerated

The safety review found two ways an `AiSuggestion` could reach a persisted state
without a role-authorised `ClinicianDecision`. Both are fixed. Here is the full
enumeration the brief asked for.

| Path | Writes `AiSuggestion`? | Requires a decision? | Role gate | Verdict |
|---|---|---|---|---|
| `POST /consultations/{id}/analyze` | yes | consultation moves to `awaiting_decision`; the response carries `requires_clinician_review: true` | any user in clinic scope may *analyse* | **correct** — analysing is not deciding |
| `POST /suggestions/{id}/decision` | no | this *is* the decision | `PRESCRIBING_ROLES` or admin/superadmin (`ai.py:169`) | **correct** |
| `POST /sync` → `offline_assessment` | yes, with `degraded=True`, `model="offline-rules"` | writes suggestion **and** decision together | same gate (`sync.py:233-239`) | **correct** — the connectivity loophole is closed |
| `GET /consultations/{id}/suggestions` | no | returns `requires_clinician_review: row.decision is None` | clinic-scoped | **correct** |
| `GET /admin/audit/export` | no | exports audit rows only | clinic-filtered for non-superadmins | see AUD-007 |
| `GET /admin/metrics` | no | reports `undecided` counts | clinic-scoped | **correct**, and it is the right metric to surface |
| Semantic cache replay | reuses a cached model response | the replayed suggestion still goes through `ground` → `constrain_treatment` → `present`, and still needs a decision | — | **correct** |

I found no third instance of the class. The gate holds on every path that
persists or exports.

Two residual observations, neither a defect:

- `_apply_offline_assessment` trusts the device's `payload` and `decided_at`
  verbatim. The role gate applies to the *syncing* user, so a nurse cannot
  forge a doctor's decision, but a doctor's tablet can post an arbitrary
  suggestion body and an arbitrary decision timestamp. Within that user's own
  clinical authority, so it is a data-integrity note, not a gate hole.
- A suggestion may sit undecided for ever. The admin dashboard reports those,
  which is the right design — but nothing alerts on the count. See
  `audit/06-next-90-days.md`.

---

## 2. De-identification, and re-identification

### 2.1 What reaches a provider

`assert_no_pii` runs once, inside `deidentify()`, on the `scrubbed` dict
(`engine.py:236`). It never runs on the bytes actually handed to a provider.
The safety review's lesson — assert on the assembled object, not the
intermediate one — was applied to `chronic_flags` and not generalised.

Enumerating every field that reaches an outbound call:

| Field | Source | Scrubbed? |
|---|---|---|
| `chief_complaint` (prompt) | `scrubbed` | yes |
| `vitals` (prompt) | `scrubbed` | yes |
| `chronic_flags` (prompt) | `scrubbed` | yes — the review's fix |
| `concepts`, `icd10_candidates` | `case` | canonical codes, no free text |
| `age_detail` — **exact age in years** | `case.age_years` | **no** — added after the assertion |
| red-flag messages | rule table | contain vital values (SpO2, glucose); clinical, not identifying |
| **cache-key text** | **`case.chief_complaint`, raw** | **no — AUD-001** |

AUD-001 is the P0. The rest of this section assumes it fixed.

### 2.2 Even correctly de-identified, is the payload re-identifying?

The question the safety review did not ask. What leaves, per consultation, is:
exact age in years, sex, pregnancy status, language, clinic tier, the full
symptom narrative in the patient's own words, every recorded vital, and the
chronic-condition list.

In a rural QVP serving 2,000–5,000 people, `{female, 34, pregnant, goitre,
Uzbek}` is frequently unique. Add a rare condition or an unusual vital and it is
close to certainly unique. The narrative itself is the strongest quasi-identifier
of all — a free-text account of a specific illness episode is effectively a
fingerprint of that consultation.

This does not make the current scrubbing wrong; direct identifiers are the
right first target. It means the honest description to a data-protection
reviewer is "pseudonymised", not "de-identified", and the mitigations are
organisational rather than technical: a processor agreement, a retention limit,
and a decision about whether the provider may retain the payload at all.

Two concrete steps that cost little: send an age **band** rather than exact
years unless a rule needs the number (paediatric dosing already has
`weight_kg`), and record in the audit row which provider a payload went to, so
the question "what left the country and when" has an answer.

---

## 3. Red flags are deterministic, and stay that way under failure

Verified by forcing each failure mode
(`audit/adversarial/test_audit_probes.py::test_probe_red_flags_survive_every_model_failure`):

```
  provider outage            degraded=True red_flags=['acs_suspected', 'hypoxia', 'respiratory_distress']
  schema-invalid response    degraded=True red_flags=['acs_suspected', 'hypoxia', 'respiratory_distress']
  empty response             degraded=True red_flags=['acs_suspected', 'hypoxia', 'respiratory_distress']
  half-valid JSON            degraded=True red_flags=['acs_suspected', 'hypoxia', 'respiratory_distress']
  breaker states: ['open', 'open', 'open']  -> hypoxia still fires
```

Red flags are computed at `engine.py:546`, before the prompt is built and before
any provider is touched. Nothing in `red_flags.py` imports a provider. `present()`
re-attaches them after every path including a cache hit, and re-runs the
schema validator so a red flag forces referral even if a later stage changed the
referral block. This is the strongest part of the system and it does what it
claims.

The weakness is upstream, in what counts as a red flag at all — §2.4 of
`audit/02-evaluation-reality.md`, finding AUD-003.

---

## 4. The paediatric and controlled-substance blocks

**Paediatric dosing: works.** Under 12 with no recorded weight, every dose is
stripped and `blocked_reason = "pediatric_weight_required"` is set
(`engine.py:439-445`), the follow-up questions lead with the weight question,
and the block is *shown* in the UI rather than silently applied
(`mobile/lib/widgets/suggestion_view.dart:61-71`, asserted by the Flutter test
`a blocked paediatric dose is shown, not hidden`). Verified through the engine
and through the offline Dart engine (`offline_engine.dart:78`).

**Controlled substances: does not work.** AUD-002. `knowledge/formulary.csv` has
49 rows and **none** sets `controlled=true`, so the drop branch is unreachable;
a drug the formulary has never heard of returns `controlled=False`, and all five
of morphine, tramadol, diazepam, fentanyl and phenobarbital reach the clinician
annotated "Not available locally". The offline engine emits no treatment at all,
so this is an online-path defect only.

---

## 5. Formulary constraint

Works as specified for drugs that are in the list. `constrain_treatment` marks
each item `available`, `substitute_suggested` (naming the substitute) or
`unavailable` with a reason, and the UI shows the substitute rather than
silently swapping — asserted by the Flutter test `an unavailable drug shows its
substitute`. Pregnancy category D/X and `pediatric_ok` are both checked.

The gap is the same one as AUD-002: **unknown drugs fail open.** The formulary
should be a whitelist, and it is being used as a lookup.

---

## 6. Degradation honesty

`degraded` is not merely a database column. It is returned by the API, stored on
the device (`database.dart:70`), and rendered as an amber banner above the
differentials (`suggestion_view.dart:33-42`) reading `suggestion.offline`. The
offline path also sets `insufficient_data=True` and never invents a
differential, asserted by `offline assessment never invents a differential
offline`. This one is genuinely done.

---

## 7. The numbers already on the table

### 7.1 `respiratory_infection` at 83.3% (n=72)

The brief asked whether any case confuses tuberculosis with a benign
respiratory infection. **It does not.** The remediation investigated case by
case and found all 12 failures are one template × 6 duplicates × 2 languages,
and that on those the system **declines** rather than answering wrongly — the
safe failure. I confirmed the shape independently: the run reports
`Insufficient-data responses 2.4%` and `Declined when it should have answered
12`, and 12 is exactly the respiratory_infection failure count.

So the class score is an artefact of duplication, not a TB safety finding. The
real statement is "four of five templates", on n=5, which is not a number worth
reporting at all.

The TB *risk* is real but lives elsewhere: `tb_triad` requires
`cough AND (>3 weeks) AND (night_sweats|weight_loss|hemoptysis)`, all of which
are vocabulary. On the audit set, `aud-oov-003` (cough since Navro'z, wet shirt
at night, clothes now loose) missed `tb_suspected` in both languages, and
`aud-adv-005` (cough over a month, wakes up wet, lost weight) missed it in
Russian. In a country with Uzbekistan's TB burden, that is the class of miss
that matters, and it is AUD-003 again.

### 7.2 False-referral rate

Now **0.0%** on the main set, from 10.8%. The cause was real and the fix is
sound: `severe_anemia` required `anemia|pallor` + generic `dyspnea` and so fired
on all 40 mild iron-deficiency cases, while the WHO guidance shipped in this
repository reserves urgent referral for breathlessness **at rest**. A
`dyspnea_at_rest` concept was introduced and the rule narrowed. Red-flag recall
stayed at 100%. This is the best piece of work in the remediation: a rule was
contradicting its own cited source and the eval was the thing that caught it.

The residual, on the audit set, is a **7.5% false-referral rate**, of which the
negation cases (AUD-004) are the identifiable driver. Over-referral is not
free — for a rural patient it is a day of travel and a day of lost wages — and a
system that refers because a mother said "no dehydration" will be switched off
within a month.

### 7.3 The 100.0% cells

Eight of eleven are trivially separable by one shared phrase, measured and
published by `make eval-overlap`. They are not evidence of anything and should
not appear in a deck.

---

## 8. What a clinician should be told about this system today

Not "it catches danger signs". On unfamiliar wording it catches roughly a third,
and none of the ones that depend on words alone. The defensible description is:

> It writes the note, ranks a differential from structured symptoms, checks
> every drug against the national formulary, blocks paediatric doses without a
> weight, and raises an alarm when a vital sign is out of range. It does not
> read your patient's story for danger, and you must not rely on it to.

That is a smaller product than the plan describes, and it is one a clinic could
use tomorrow without anyone being harmed.
