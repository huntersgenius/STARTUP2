# ADR 0001 — Provider and store abstractions instead of direct SDK calls

Status: accepted · 2026-08-19

## Context

The master spec names GPT-4o, Claude, self-hosted Llama, pgvector in cloud and
ChromaDB on the edge. Three facts follow from the product, not the stack:

1. The same code must run in a Tashkent data centre and on a mini-PC in a
   Chinoz clinic with no internet.
2. CI must run the full pipeline with no API keys and no network, on every PR,
   including the safety suites.
3. The evaluation harness has to replay identical inputs across models to be
   worth anything.

Calling vendor SDKs directly from `engine.py` makes all three impossible.

## Decision

Three protocols, defined in `app/ai/providers/base.py`:

- `LlmProvider` — `OpenAIProvider`, `AnthropicProvider`, `LocalLlamaProvider`
  (Ollama/vLLM), `ScriptedProvider` (cassette playback for tests and eval).
- `EmbeddingProvider` — `OpenAIEmbeddings` in production; `HashingEmbeddings`,
  a deterministic dependency-free embedder, offline and in CI.
- `VectorStore` — `PgVectorStore` in the cloud, `InMemoryVectorStore` for CI
  and small edge deployments.

`app/ai/router.py` selects an `LlmProvider` per request; nothing else in the
codebase imports a vendor SDK.

## Consequences

- Tests never touch the network, so the de-identification red-team suite and
  the eval gate can run on every PR.
- Swapping a model is a routing change, not a rewrite.
- `HashingEmbeddings` gives stable-but-not-semantic vectors: offline retrieval
  leans on BM25, and the eval report tracks the two embedders separately so an
  offline pass is never mistaken for a production-quality one.
