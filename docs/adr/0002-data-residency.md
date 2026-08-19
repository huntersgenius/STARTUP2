# ADR 0002 — Data residency and the de-identification boundary

Status: accepted, with an open question for legal · 2026-08-19

## Context

The spec requires that no patient identifier leaves the country boundary or
reaches a third-party LLM, while also naming AWS ap-south-1 (Mumbai) for
staging. Those two things cannot both be true of a database holding
identifiers.

## Decision

Separate the two boundaries:

1. **Identifiers never leave the process.** `Patient.pii_blob` is AES-256-GCM
   encrypted, bound to the patient's row id. `app/ai/deident.py` runs on every
   outbound payload and its red-team suite must show zero leakage. Identifiers
   are re-attached locally after the model call. This makes the *LLM* boundary
   compliant regardless of where compute sits.
2. **The datastore is a residency decision, not an engineering one.** Mumbai is
   acceptable for staging against synthetic data. Production must run on
   domestically hosted infrastructure, or under an explicit legal opinion.
   `infra/terraform` parameterises the region for exactly this reason.

## Consequences

- Staging can run in ap-south-1 today with synthetic patients.
- Production deployment is blocked on a legal answer, tracked as open question
  #3 in `docs/PLAN.md`. This is a business blocker, not a technical one, and
  it must not be resolved by an engineer choosing a region.
