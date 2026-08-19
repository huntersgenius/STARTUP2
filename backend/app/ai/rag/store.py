"""Vector stores.

`InMemoryVectorStore` is used by CI and by small edge deployments;
`PgVectorStore` is the cloud path. Both satisfy the same interface, so the
retriever has one code path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.embeddings import cosine
from app.models.knowledge import ProtocolChunk


@dataclass(frozen=True)
class ScoredChunk:
    chunk: ProtocolChunk
    score: float
    #: Which retrieval arm found it, for debugging poor recall.
    source: str = "vector"


class VectorStore(Protocol):
    def search(
        self,
        embedding: list[float],
        *,
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[ScoredChunk]: ...


def _passes_filters(chunk: ProtocolChunk, filters: dict | None) -> bool:
    """Filters are permissive by design.

    A chunk with no age-band metadata is a general protocol and stays eligible;
    only an explicit mismatch excludes it. Silently dropping unlabelled
    protocols would quietly shrink the knowledge base.
    """
    if not filters:
        return True
    chunk_filters = chunk.filters or {}

    language = filters.get("language")
    if language and chunk.language != language and not filters.get("any_language"):
        return False

    age_band = filters.get("age_band")
    bands = chunk_filters.get("age_bands")
    if age_band and bands and age_band not in bands:
        return False

    sex = filters.get("sex")
    sexes = chunk_filters.get("sex")
    if sex and sexes and sex not in sexes:
        return False

    codes = filters.get("icd10")
    chunk_codes = chunk_filters.get("icd10")
    return not (codes and chunk_codes and not set(codes) & set(chunk_codes))


class InMemoryVectorStore:
    """Exact cosine search over every chunk. Fine to a few thousand chunks."""

    name = "in-memory"

    def __init__(self, db: Session) -> None:
        self.db = db

    def all_chunks(self, filters: dict | None = None) -> list[ProtocolChunk]:
        chunks = list(self.db.execute(select(ProtocolChunk)).scalars())
        return [c for c in chunks if _passes_filters(c, filters)]

    def search(
        self, embedding: list[float], *, limit: int = 10, filters: dict | None = None
    ) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk=chunk, score=cosine(embedding, chunk.embedding or []))
            for chunk in self.all_chunks(filters)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return [s for s in scored[:limit] if s.score > 0]


class PgVectorStore:
    """pgvector-backed ANN search. Falls back to exact scan without pgvector."""

    name = "pgvector"

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self, embedding: list[float], *, limit: int = 10, filters: dict | None = None
    ) -> list[ScoredChunk]:
        try:
            from pgvector.sqlalchemy import Vector as PGVector  # noqa: F401
        except ImportError:
            return InMemoryVectorStore(self.db).search(embedding, limit=limit, filters=filters)

        stmt = select(
            ProtocolChunk,
            ProtocolChunk.embedding.cosine_distance(embedding).label("distance"),
        )
        language = (filters or {}).get("language")
        if language and not (filters or {}).get("any_language"):
            stmt = stmt.where(ProtocolChunk.language == language)
        # Over-fetch, then apply the JSON metadata filters in Python: the
        # index only helps with the vector ordering.
        stmt = stmt.order_by("distance").limit(limit * 4)

        results: list[ScoredChunk] = []
        for chunk, distance in self.db.execute(stmt):
            if _passes_filters(chunk, filters):
                results.append(ScoredChunk(chunk=chunk, score=1.0 - float(distance)))
        return results[:limit]


def get_store(db: Session) -> VectorStore:
    from app.core.config import get_settings

    return PgVectorStore(db) if get_settings().is_postgres else InMemoryVectorStore(db)
