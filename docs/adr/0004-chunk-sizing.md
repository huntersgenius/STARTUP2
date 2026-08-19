# ADR 0004 — Chunk sizing prioritises citation quality over the 400-token floor

Status: accepted · 2026-08-19

## Context

The build spec asks for 400-800 token, header-aware chunks. Applied literally
to the committed corpus, a 400-token floor merges adjacent sections of a
protocol — "When to start drug treatment" absorbs "Choice of drug" — because
the individual sections are shorter than the floor.

That has two costs. Retrieval precision drops, because one chunk now answers
several different questions. More importantly the *citation* degrades: the
clinician is shown a section heading that does not name the advice they are
reading, which defeats the point of citing at all.

## Decision

- `MAX_TOKENS = 800` stays a hard ceiling.
- `TARGET_TOKENS = 500` is what long prose aims for; splits happen at paragraph
  boundaries so a dose is never cut in half.
- `MIN_TOKENS = 60` only prevents a stray one-line fragment from becoming
  independently retrievable. Natural sections shorter than 400 tokens are kept
  as their own chunk.

## Consequences

- Chunks from the committed corpus range from roughly 80 to 500 estimated
  tokens, below the spec's floor for short sections.
- Every chunk's `section` names the advice it contains, so the citation shown
  to a clinician is checkable.
- Long MoH PDF protocols, once ingested, will produce chunks in the specified
  400-800 range, because their sections are long enough. The behaviour differs
  by document, which is the intent.
