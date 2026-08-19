"""Hybrid retrieval: concept + lexical + vector, with filters and citations.

Three arms, fused with reciprocal rank fusion (no score calibration needed):

- **concept** — the query rewritten through the terminology map into every
  language the corpus uses, plus ICD-10 codes. This is the arm that makes an
  Uzbek query reach an English WHO protocol, and it carries most of the
  cross-lingual weight.
- **lexical** (BM25) — the query as typed. Catches rare exact tokens that no
  embedding handles well: drug names, "GeneXpert", dosages.
- **vector** — semantic similarity in production; lexical-ish offline, where
  the embedder is a hashing projection (ADR 0001).

Measured on the Sprint 2 seed set, the concept arm alone answers 18/20 queries
and the raw lexical arm 6/20 — the query's own function words ("kerak",
"davolash", "лечение") otherwise drown the clinical terms.

Every returned chunk carries its citation. A differential that cannot cite a
retrieved chunk is dropped upstream in `engine.py` rather than shown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from knowledge.terminology import get_terminology
from sqlalchemy.orm import Session

from app.ai.providers.base import EmbeddingProvider
from app.ai.providers.embeddings import get_embeddings
from app.ai.rag.store import InMemoryVectorStore, ScoredChunk, get_store
from app.ai.rag.textnorm import tokenize
from app.models.knowledge import ProtocolChunk

#: Reciprocal-rank-fusion constant, from the original RRF paper.
RRF_K = 60

#: Arm weights. Plain RRF weights every arm equally, which is wrong here: the
#: concept arm is measurably the most reliable (18/20 on the Sprint 2 seed set
#: against 6/20 for raw lexical), and equal weighting lets two noisier arms
#: outvote it. Re-measure these against the seed set before changing them.
ARM_WEIGHTS = {"concept": 3.0, "bm25": 1.0, "vector": 1.0}


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk plus everything needed to cite and audit it."""

    id: str
    text: str
    citation: str
    source_id: str
    publisher: str
    version: str
    language: str
    section: str | None
    page: int | None
    score: float
    arms: tuple[str, ...]

    @classmethod
    def from_chunk(
        cls, chunk: ProtocolChunk, score: float, arms: tuple[str, ...]
    ) -> RetrievedChunk:
        return cls(
            id=str(chunk.id),
            text=chunk.text,
            citation=chunk.citation,
            source_id=chunk.source_id,
            publisher=chunk.publisher,
            version=chunk.version,
            language=chunk.language,
            section=chunk.section,
            page=chunk.page,
            score=score,
            arms=arms,
        )


class Reranker:
    """Cross-encoder reranking slot.

    Stubbed deliberately: a real reranker is a second model call per query and
    has to earn its cost against the Sprint 5 metrics before it ships. The
    identity implementation keeps the call site honest.
    """

    name = "identity"

    def rerank(self, query: str, chunks: list[ScoredChunk], limit: int) -> list[ScoredChunk]:
        return chunks[:limit]


class HybridRetriever:
    def __init__(
        self,
        db: Session,
        *,
        embeddings: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        expand: bool = True,
    ) -> None:
        self.db = db
        self.embeddings = embeddings or get_embeddings()
        self.store = get_store(db)
        self.reranker = reranker or Reranker()
        self.expand = expand
        self.terminology = get_terminology()

    # --- BM25 arm --------------------------------------------------------
    def _bm25(self, query: str, filters: dict | None, limit: int) -> list[ScoredChunk]:
        corpus = InMemoryVectorStore(self.db).all_chunks(filters)
        if not corpus:
            return []
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:  # pragma: no cover - dependency is pinned
            return []

        tokenized = [tokenize(c.text) for c in corpus]
        scores = BM25Okapi(tokenized).get_scores(tokenize(query))
        ranked = sorted(
            (
                ScoredChunk(chunk=c, score=float(s), source="bm25")
                for c, s in zip(corpus, scores, strict=True)
            ),
            key=lambda s: s.score,
            reverse=True,
        )
        return [r for r in ranked[:limit] if r.score > 0]

    # --- fusion ----------------------------------------------------------
    def _concept_query(self, query: str) -> str:
        """The query expressed purely as clinical concepts, no filler words."""
        return " ".join(self.terminology.expand(query))

    def _concept_arm(self, query: str, filters: dict | None, limit: int) -> list[ScoredChunk]:
        """Rank by shared clinical concepts rather than shared words.

        Text-level expansion drags in the common words inside colloquial
        Uzbek terms — "suv" from "suv yo'qotish", "ich" from "ich ketishi" —
        and those words match unrelated protocols. Concepts do not have that
        problem: a chunk about dehydration and a chunk about polydipsia share
        no concept even though both talk about drinking water.

        Rarer concepts count for more (inverse document frequency), so
        "dehydration" outweighs a concept every protocol mentions.
        """
        query_concepts = set(self.terminology.clinical_concepts(query))
        if not query_concepts:
            return []

        corpus = InMemoryVectorStore(self.db).all_chunks(filters)
        if not corpus:
            return []

        document_frequency: dict[str, int] = {}
        for chunk in corpus:
            for concept in set((chunk.filters or {}).get("concepts") or []):
                document_frequency[concept] = document_frequency.get(concept, 0) + 1

        total = len(corpus)
        scored: list[ScoredChunk] = []
        for chunk in corpus:
            shared = query_concepts & set((chunk.filters or {}).get("concepts") or [])
            if not shared:
                continue
            counts = (chunk.filters or {}).get("concept_counts") or {}
            score = sum(
                math.log(1 + counts.get(concept, 1))
                * math.log(1 + total / document_frequency.get(concept, 1))
                for concept in shared
            )
            scored.append(ScoredChunk(chunk=chunk, score=score, source="concept"))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 6,
        language: str | None = None,
        age_band: str | None = None,
        sex: str | None = None,
        icd10: list[str] | None = None,
        any_language: bool = True,
    ) -> list[RetrievedChunk]:
        """Retrieve protocol chunks for a query.

        `any_language` defaults to True on purpose: the corpus mixes WHO
        guidance in English with MoH protocols in Uzbek, and a clinician asking
        in Uzbek still needs the WHO IMCI chunk. Language is used for ranking
        preference, not exclusion.
        """
        filters = {
            "language": language,
            "age_band": age_band,
            "sex": sex,
            "icd10": icd10,
            "any_language": any_language,
        }
        over_fetch = max(limit * 3, 12)

        # The vector arm sees the query plus its cross-lingual expansions, so
        # an Uzbek query has some lexical purchase on an English protocol.
        vector_text = f"{query} {self._concept_query(query)}".strip() if self.expand else query

        vector_hits = self.store.search(
            self.embeddings.embed([vector_text])[0], limit=over_fetch, filters=filters
        )
        lexical_hits = self._bm25(query, filters, over_fetch)
        concept_hits = self._concept_arm(query, filters, over_fetch) if self.expand else []

        fused: dict[str, float] = {}
        arms: dict[str, set[str]] = {}
        holder: dict[str, ProtocolChunk] = {}
        for hits, arm in (
            (concept_hits, "concept"),
            (lexical_hits, "bm25"),
            (vector_hits, "vector"),
        ):
            weight = ARM_WEIGHTS[arm]
            for rank, hit in enumerate(hits, start=1):
                key = str(hit.chunk.id)
                fused[key] = fused.get(key, 0.0) + weight / (RRF_K + rank)
                arms.setdefault(key, set()).add(arm)
                holder[key] = hit.chunk

        # Prefer a chunk written in the clinician's language when scores tie.
        if language:
            for key, chunk in holder.items():
                if chunk.language == language:
                    fused[key] += 1.0 / (RRF_K * 4)

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
        candidates = [
            ScoredChunk(chunk=holder[key], score=score, source="fused") for key, score in ordered
        ]
        top = self.reranker.rerank(query, candidates, limit)
        return [
            RetrievedChunk.from_chunk(c.chunk, c.score, tuple(sorted(arms[str(c.chunk.id)])))
            for c in top
        ]
