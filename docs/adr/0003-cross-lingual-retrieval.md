# ADR 0003 — Concepts as the interlingua for cross-lingual retrieval

Status: accepted · 2026-08-19

## Context

The corpus is trilingual by necessity: WHO guidance exists in English, MoH
protocols in Uzbek, and some material in Russian. Queries arrive in Uzbek or
Russian. A clinician asking about *bolada ich ketishi* must reach the WHO IMCI
diarrhoea protocol, which contains none of those words.

The first implementation — vector + BM25 over the raw query — retrieved the
correct protocol for **5 of 20** seeded queries. Adding the query's
translations as extra search text raised that to 11/20, then stalled: the
colloquial Uzbek terms contain very common words ("suv" from *suv yo'qotish*,
"ich" from *ich ketishi*), and those words match unrelated protocols. Expanding
the text made the query noisier as fast as it made it richer.

## Decision

Concepts, not words, are the interlingua. Three changes:

1. **Chunks are tagged with clinical concepts at ingestion**, by running the
   terminology map over the chunk text, storing both the concept set and
   per-concept frequencies.
2. **Retrieval gains a third arm** that ranks by concept overlap with tf-idf
   weighting, alongside BM25 (raw query) and vector similarity. The three are
   fused with weighted reciprocal rank fusion; the concept arm carries weight
   3.0 against 1.0 for the others, because it is measurably the most reliable.
3. **Three matching problems are fixed in the terminology map itself**, since
   all of them are vocabulary problems:
   - *Agglutination.* Uzbek suffixes attach to the stem, so real protocol text
     says "pnevmoniyani", "pnevmoniyaning". A term may now be followed by up to
     5 alphanumeric characters inside the same token.
   - *Spelling.* WHO writes "anaemia", "diarrhoea", "paediatric"; clinicians
     write the other form. British/American digraphs are folded before lookup.
   - *Numbers.* "qon bosimi 160/95" means hypertension, and no word map can see
     that. Numeric findings — blood pressure, temperature, SpO2, glucose — map
     to concepts against the thresholds stated in the committed protocols, in
     the abnormal direction only.

## Consequences

- 20 of 20 seeded queries retrieve the correct protocol, in Uzbek and Russian.
- The terminology map is now load-bearing for retrieval, not only for prompt
  construction. A missing term degrades retrieval measurably, which is the
  right incentive: it makes the map's coverage a tracked metric rather than a
  nice-to-have.
- Suffix tolerance can over-match in principle. It is bounded at 5 characters
  and the left boundary stays strict, so "isitmasizlikxyz" is still not a
  fever; the eval suite in Sprint 5 is where any real precision cost shows up.
- Concept tagging happens at ingestion, so changing the terminology map
  requires re-ingestion. `make ingest` is idempotent and replaces a source
  wholesale for exactly this reason.

## Alternative rejected

A translation model in the request path (NLLB-200 or an LLM call) would handle
vocabulary we have not mapped, but it adds latency and cost to every query,
cannot run on an edge box, and makes retrieval quality depend on a model that
is not evaluated by the clinical eval suite. The map is auditable; a translation
model is not.
